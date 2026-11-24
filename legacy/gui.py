"""场景任务码生成器 —— 图形界面（tkinter）。"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from .core import (
    DEFAULT_BASE_TOKEN,
    DEFAULT_SITE_TABLE,
    DEFAULT_TASK_TABLE,
    FeishuAPI,
    FileSource,
    LarkCLISource,
    Task,
    friendly_error,
    generate_files,
    preflight,
    stage_upload_file,
    sync_all_tables,
)
from .label import TaskLabel, png_bytes, render_label

APP_TITLE = "场景任务码生成器"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ScenarioQRCode"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"


def resource_path(relative: str) -> Path:
    """兼容源码运行与 PyInstaller 打包后的资源定位。"""
    import sys

    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parent.parent / relative


def write_log(text: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = __import__("datetime").datetime.now().strftime("%Y%m%d")
        with (LOG_DIR / f"run-{stamp}.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
    except Exception:
        pass

SOURCE_API = "飞书开放平台（App ID / Secret）"
SOURCE_CLI = "本机 lark-cli（已登录）"
SOURCE_FILE = "本地文件（Excel / CSV / JSON）"


# ---------------------------------------------------------------- 配置
DEFAULT_PROFILES = [
    {"name": "示例区域 1",
     "base_token": "<FILL_ME_BASE_TOKEN>",
     "task_table": "<FILL_ME_TASK_TABLE>",
     "site_table": "<FILL_ME_SITE_TABLE>"},
    {"name": "示例区域 2",
     "base_token": "<FILL_ME_BASE_TOKEN_2>",
     "task_table": "<FILL_ME_TASK_TABLE_2>",
     "site_table": "<FILL_ME_SITE_TABLE_2>"},
    {"name": "示例区域 3",
     "base_token": "<FILL_ME_BASE_TOKEN_3>",
     "task_table": "<FILL_ME_TASK_TABLE_3>",
     "site_table": "<FILL_ME_SITE_TABLE_3>"},
]


def load_config() -> dict:
    defaults = {
        "source": SOURCE_CLI,
        "app_id": "",
        "app_secret": "",
        "user_token": "",
        "base_token": DEFAULT_BASE_TOKEN,
        "task_table": DEFAULT_TASK_TABLE,
        "site_table": DEFAULT_SITE_TABLE,
        "out_dir": str(Path.home() / "Desktop" / "场景任务码"),
        "last_file": "",
        "auto_load": True,
        "profiles": [
            {"name": "示例区域 1",
             "base_token": "<FILL_ME_BASE_TOKEN>",
             "task_table": "<FILL_ME_TASK_TABLE>",
             "site_table": "<FILL_ME_SITE_TABLE>"},
            {"name": "示例区域 2",
             "base_token": "<FILL_ME_BASE_TOKEN_2>",
             "task_table": "<FILL_ME_TASK_TABLE_2>",
             "site_table": "<FILL_ME_SITE_TABLE_2>"},
            {"name": "示例区域 3",
             "base_token": "<FILL_ME_BASE_TOKEN_3>",
             "task_table": "<FILL_ME_TASK_TABLE_3>",
             "site_table": "<FILL_ME_SITE_TABLE_3>"},
        ],
        "active_profile": "示例区域 1",
        "only_missing": False,
    }
    try:
        if CONFIG_FILE.exists():
            defaults.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    # 以预置表格为准去重合并（升级后旧配置里的重复项会被自动清理）
    def _key(p: dict) -> tuple[str, str]:
        return (p.get("base_token", ""), p.get("task_table", ""))

    merged: list[dict] = []
    known: set[tuple[str, str]] = set()
    for preset in DEFAULT_PROFILES:
        if _key(preset) not in known:
            merged.append(dict(preset))
            known.add(_key(preset))
    for prof in defaults.get("profiles") or []:
        if not prof.get("base_token") or not prof.get("task_table"):
            continue
        if _key(prof) in known:
            continue
        merged.append(dict(prof))
        known.add(_key(prof))
    defaults["profiles"] = merged
    return defaults


def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- 主窗口
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        self.tasks: list[Task] = []
        self.selected: set[str] = set()
        self._preview_img: ImageTk.PhotoImage | None = None
        self._events: queue.Queue = queue.Queue()
        self._busy = False
        self._cancel = threading.Event()

        self.title(APP_TITLE)
        self.geometry("1240x880")
        self.minsize(1080, 800)
        try:
            ico = resource_path("assets/icon.ico")
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass
        self._build_ui()
        self.after(120, self._pump_events)
        self.after(200, self._preflight)
        if self.cfg.get("auto_load", True):
            self.after(1200, self._auto_load)

    # ------------------------------------------------------------ 构建 UI
    def _build_ui(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Hint.TLabel", foreground="#666666")

        # ---- 状态栏（先占位，避免被主体挤出窗口）
        status = ttk.Frame(self, padding=(12, 3, 12, 5))
        status.pack(fill="x", side="bottom")
        self.lbl_status = ttk.Label(status, text="就绪", style="Hint.TLabel")
        self.lbl_status.pack(side="left")
        self.lbl_version = ttk.Label(status, text="v1.1 · A4@144dpi · 二维码内容=任务ID",
                                     style="Hint.TLabel")
        self.lbl_version.pack(side="right")

        outer = ttk.Frame(self, padding=(12, 10, 12, 8))
        outer.pack(fill="both", expand=True)

        # ---- 表格选择（主界面只保留这一行）
        src_box = ttk.LabelFrame(outer, text=" 选择区域 ", padding=(10, 8))
        src_box.pack(fill="x")

        row0 = ttk.Frame(src_box)
        row0.pack(fill="x")
        self.source_var = tk.StringVar(value=self.cfg.get("source", SOURCE_CLI))
        self.var_pick = tk.StringVar()
        self.cbo_pick = ttk.Combobox(row0, textvariable=self.var_pick, state="readonly", width=38)
        self.cbo_pick.pack(side="left")
        self.cbo_pick.bind("<<ComboboxSelected>>", lambda e: self._on_pick_change())

        self.btn_load = ttk.Button(row0, text="刷新", command=self.on_load, width=6)
        self.btn_load.pack(side="left", padx=(8, 0))
        self.btn_login = ttk.Button(row0, text="登录飞书", command=self.on_login, width=12)
        self.btn_login.pack(side="left", padx=(6, 0))
        ttk.Button(row0, text="表设置…", command=self._open_table_settings, width=9).pack(
            side="left", padx=(6, 0))
        self.lbl_source = ttk.Label(row0, text="", style="Hint.TLabel")
        self.lbl_source.pack(side="left", padx=(12, 0))

        # 隐藏的技术字段（仍参与配置保存）
        self.var_app_id = tk.StringVar(value=self.cfg.get("app_id", ""))
        self.var_app_secret = tk.StringVar(value=self.cfg.get("app_secret", ""))
        self.var_user_token = tk.StringVar(value=self.cfg.get("user_token", ""))
        self.var_base = tk.StringVar(value=self.cfg.get("base_token", DEFAULT_BASE_TOKEN))
        self.var_task_table = tk.StringVar(value=self.cfg.get("task_table", DEFAULT_TASK_TABLE))
        self.var_site_table = tk.StringVar(value=self.cfg.get("site_table", DEFAULT_SITE_TABLE))
        self.var_file = tk.StringVar(value=self.cfg.get("last_file", ""))

        # 只有选了「本地文件」才出现
        self.file_frame = ttk.Frame(src_box)
        ttk.Entry(self.file_frame, textvariable=self.var_file, width=70).pack(side="left")
        ttk.Button(self.file_frame, text="选择文件…", command=self.on_pick_file).pack(side="left", padx=(6, 0))
        ttk.Label(self.file_frame, text="  需要包含列：任务ID、任务名称、采集点",
                  style="Hint.TLabel").pack(side="left")

        # ---- 工具栏
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(10, 6))
        ttk.Label(bar, text="搜索").pack(side="left")
        self.var_search = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.var_search, width=22)
        entry.pack(side="left", padx=(4, 8))
        entry.bind("<KeyRelease>", lambda e: self.refresh_tree())
        ttk.Label(bar, text="采集点").pack(side="left")
        self.var_site = tk.StringVar(value="全部")
        self.cbo_site = ttk.Combobox(bar, textvariable=self.var_site, state="readonly", width=20, values=["全部"])
        self.cbo_site.pack(side="left", padx=(4, 8))
        self.cbo_site.bind("<<ComboboxSelected>>", lambda e: self.refresh_tree())
        ttk.Button(bar, text="全选", command=lambda: self.select_all(True)).pack(side="left")
        ttk.Button(bar, text="全不选", command=lambda: self.select_all(False)).pack(side="left", padx=(6, 0))
        self.var_only_missing = tk.BooleanVar(value=bool(self.cfg.get("only_missing")))
        ttk.Checkbutton(bar, text="只看缺二维码", variable=self.var_only_missing,
                        command=self._on_only_missing).pack(side="left", padx=(12, 0))
        self.lbl_sel = ttk.Label(bar, text="已选 0 / 0")
        self.lbl_sel.pack(side="left", padx=(12, 0))

        # ---- 主体：任务表 + 预览
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        cols = ("sel", "task_id", "task_name", "site", "status", "code")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        heads = {
            "sel": ("选择", 56), "task_id": ("任务ID", 110), "task_name": ("任务名称", 300),
            "site": ("采集点", 215), "status": ("状态", 80), "code": ("已有码", 70),
        }
        for c, (text, width) in heads.items():
            self.tree.heading(c, text=text)
            self.tree.column(c, width=width, anchor="w" if c in ("task_name", "site") else "center",
                             stretch=(c in ("task_name", "site")))
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_preview())

        right = ttk.LabelFrame(body, text=" 版式预览 ", padding=8)
        right.pack(side="left", fill="y", padx=(10, 0))
        self.preview = ttk.Label(right, text="选择一条任务查看预览", anchor="center")
        self.preview.pack(fill="both", expand=True)
        self.lbl_preview = ttk.Label(right, text="", style="Hint.TLabel", wraplength=360, justify="left")
        self.lbl_preview.pack(fill="x", pady=(6, 0))

        # ---- 操作（只做同步）
        act = ttk.Frame(outer)
        act.pack(fill="x", pady=(10, 4))
        self.btn_sync = ttk.Button(act, text="一键补齐全部区域", command=self.on_sync_all, width=20)
        self.btn_sync.pack(side="left")
        self.btn_sync_one = ttk.Button(act, text="只补当前区域", command=self.on_sync_current, width=14)
        self.btn_sync_one.pack(side="left", padx=(8, 0))
        self.btn_stop = ttk.Button(act, text="停止", command=self.on_stop_sync, width=8)
        self.btn_stop.pack(side="left", padx=(8, 0))
        self.btn_stop.state(["disabled"])
        ttk.Button(act, text="打开输出文件夹", command=self.open_out_dir).pack(side="left", padx=(8, 0))
        self.progress = ttk.Progressbar(act, length=260, mode="determinate")
        self.progress.pack(side="right")
        self.lbl_progress = ttk.Label(act, text="", style="Hint.TLabel")
        self.lbl_progress.pack(side="right", padx=(0, 10))

        # ---- 日志
        self.log = tk.Text(outer, height=4, font=("Consolas", 9), wrap="word",
                           background="#fbfbfb", relief="solid", borderwidth=1)
        self.log.pack(fill="x", pady=(6, 0))
        self.log.configure(state="disabled")

        self._init_table_ui()
        self._update_sel_label()

    # ------------------------------------------------------------ 表格选择
    FILE_CHOICE = "本地文件（Excel / CSV）"

    def _init_table_ui(self) -> None:
        """初始化下拉框：预置表格 + 本地文件。"""
        names = [p["name"] for p in self._profiles()]
        self.cbo_pick.configure(values=names + [self.FILE_CHOICE])
        current = self.var_base.get().strip()
        picked = ""
        for prof in self._profiles():
            if prof.get("base_token") == current and prof.get("task_table") == self.var_task_table.get().strip():
                picked = prof["name"]
                break
        if self.source_var.get() == SOURCE_FILE:
            picked = self.FILE_CHOICE
        self.var_pick.set(picked or (names[0] if names else self.FILE_CHOICE))
        self._on_pick_change(auto=False)

    def _on_pick_change(self, auto: bool = True) -> None:
        name = self.var_pick.get()
        if name == self.FILE_CHOICE:
            self.source_var.set(SOURCE_FILE)
            self.file_frame.pack(fill="x", pady=(8, 0))
            self.lbl_source.configure(text="离线模式：不改动飞书，只出图")
            if auto and not self._busy:
                self.on_load()
            return

        self.file_frame.pack_forget()
        self.source_var.set(SOURCE_CLI)
        for prof in self._profiles():
            if prof.get("name") == name:
                self.var_base.set(prof.get("base_token", ""))
                self.var_task_table.set(prof.get("task_table", ""))
                self.var_site_table.set(prof.get("site_table", ""))
                self.cfg["active_profile"] = name
                break
        self._save_cfg()
        self._refresh_login_hint()
        if auto and not self._busy:
            self.on_load()

    def _refresh_login_hint(self) -> None:
        source = LarkCLISource(cli_path="")
        if not source.available:
            self.lbl_source.configure(text="未找到 lark-cli（请用独立版）")
            return
        ok, info = source.auth_status()
        if ok:
            self.btn_login.configure(text=f"已登录：{info}")
            self.lbl_source.configure(text="选好区域 → 点下方「一键补齐全部区域」")
        else:
            self.btn_login.configure(text="登录飞书")
            self.lbl_source.configure(text="还没登录，点左边「登录飞书」扫码（只需一次）")

    def _open_table_settings(self) -> None:
        """表设置：改当前表的三项 ID，或另存为新表。"""
        win = tk.Toplevel(self)
        win.title("表设置")
        win.geometry("560x300")
        win.transient(self)
        win.grab_set()
        f = ttk.Frame(win, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="App Token（链接 /base/ 后面那串）").grid(row=0, column=0, sticky="w", pady=(0, 2))
        e_base = ttk.Entry(f, textvariable=self.var_base, width=52)
        e_base.grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="任务表 ID（tbl…，作业任务管理）").grid(row=2, column=0, sticky="w", pady=(10, 2))
        e_task = ttk.Entry(f, textvariable=self.var_task_table, width=30)
        e_task.grid(row=3, column=0, sticky="w")
        ttk.Label(f, text="采集点表 ID").grid(row=2, column=1, sticky="w", padx=(16, 0), pady=(10, 2))
        e_site = ttk.Entry(f, textvariable=self.var_site_table, width=24)
        e_site.grid(row=3, column=1, sticky="w", padx=(16, 0))

        ttk.Label(f, text="改完点「保存」；想让新表出现在下拉框里，点「另存为新表」。",
                  style="Hint.TLabel", wraplength=500).grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))

        btns = ttk.Frame(f)
        btns.grid(row=5, column=0, columnspan=2, sticky="w", pady=(14, 0))

        def save_current() -> None:
            self._save_cfg()
            self._init_table_ui()
            win.destroy()
            if not self._busy:
                self.on_load()

        def save_as_new() -> None:
            name = simpledialog.askstring(APP_TITLE, "给这张表起个名字", parent=win)
            if not name:
                return
            name = name.strip()
            profiles = [p for p in self._profiles() if p.get("name") != name]
            profiles.append({
                "name": name,
                "base_token": self.var_base.get().strip(),
                "task_table": self.var_task_table.get().strip(),
                "site_table": self.var_site_table.get().strip(),
            })
            self.cfg["profiles"] = profiles
            self.cfg["active_profile"] = name
            self._save_cfg()
            self._init_table_ui()
            self.var_pick.set(name)
            win.destroy()

        ttk.Button(btns, text="保存", command=save_current).pack(side="left")
        ttk.Button(btns, text="另存为新表", command=save_as_new).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="取消", command=win.destroy).pack(side="left", padx=(8, 0))
    # ------------------------------------------------------------ 表格配置
    def _profiles(self) -> list[dict]:
        profiles = self.cfg.setdefault("profiles", [])
        return profiles

    def on_pick_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择任务表格",
            filetypes=[("表格文件", "*.xlsx *.xlsm *.csv *.json *.ndjson"), ("所有文件", "*.*")],
        )
        if path:
            self.var_file.set(path)
            self._save_cfg()

    def _save_cfg(self) -> None:
        self.cfg.update({
            "source": self.source_var.get(),
            "app_id": self.var_app_id.get().strip(),
            "app_secret": self.var_app_secret.get().strip(),
            "user_token": self.var_user_token.get().strip(),
            "base_token": self.var_base.get().strip(),
            "task_table": self.var_task_table.get().strip(),
            "site_table": self.var_site_table.get().strip(),
            "last_file": self.var_file.get().strip(),
        })
        save_config(self.cfg)

    # ------------------------------------------------------------ 数据源实例
    def _make_source(self):
        source = self.source_var.get()
        base = self.var_base.get().strip()
        table = self.var_task_table.get().strip()
        if source == SOURCE_API:
            return FeishuAPI(
                self.var_app_id.get(), self.var_app_secret.get(),
                base_token=base, task_table=table, site_table=self.var_site_table.get().strip(),
                user_token=self.var_user_token.get(),
            )
        if source == SOURCE_CLI:
            return LarkCLISource(base_token=base, task_table=table,
                                 site_table=self.var_site_table.get().strip())
        if not self.var_file.get().strip():
            raise RuntimeError("请先选择要导入的表格文件")
        return FileSource(self.var_file.get().strip())

    # ------------------------------------------------------------ 后台任务
    def run_bg(self, fn: Callable, on_done: Callable | None = None) -> None:
        if self._busy:
            messagebox.showinfo(APP_TITLE, "上一个任务还在执行中，请稍候")
            return
        self._busy = True
        self._set_buttons(False)

        def worker() -> None:
            try:
                result = fn()
                self._events.put(("done", on_done, result))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("error", exc, traceback.format_exc()))

        threading.Thread(target=worker, daemon=True).start()

    def _pump_events(self) -> None:
        try:
            while True:
                kind, a, b = self._events.get_nowait()
                if kind == "log":
                    self.log_line(str(a))
                    if isinstance(b, (int, float)):
                        self.progress["value"] = b * 100
                    continue
                self._busy = False
                self._set_buttons(True)
                if kind == "done":
                    if a:
                        a(b)
                else:
                    self.log_line(f"[错误] {a}")
                    self.progress["value"] = 0
                    messagebox.showerror(APP_TITLE, friendly_error(a)[:900])
        except queue.Empty:
            pass
        self.after(120, self._pump_events)

    def _set_buttons(self, enabled: bool) -> None:
        state = ["!disabled"] if enabled else ["disabled"]
        for btn in (self.btn_load, self.btn_sync, self.btn_sync_one):
            btn.state(state)
        self.btn_stop.state(["disabled"] if enabled else ["!disabled"])

    # ------------------------------------------------------------ 动作
    def _preflight(self) -> None:
        """启动自检：环境受限时直接说明原因，避免后面看到一堆英文报错。"""
        problems = preflight()
        if not problems:
            return
        for item in problems:
            self.log_line(f"[环境自检] {item}")
        self.lbl_status.configure(text="环境受限：部分功能不可用")
        messagebox.showwarning(
            APP_TITLE,
            "检测到当前启动方式受限：\n\n· " + "\n· ".join(problems) +
            "\n\n这通常是因为程序是从聊天窗口 / 文件预览器里直接点开的。\n"
            "请把整个文件夹解压到本地磁盘，再从「资源管理器」双击 exe 启动。",
        )

    def on_login(self) -> None:
        """扫码登录飞书（设备码流程），用于全新电脑首次使用。"""
        if self.source_var.get() != SOURCE_CLI:
            messagebox.showinfo(APP_TITLE, "只有「本机 lark-cli」数据源需要登录。")
            return
        self._save_cfg()
        try:
            source = self._make_source()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, str(exc))
            return
        if not isinstance(source, LarkCLISource):
            return
        if not source.available:
            messagebox.showerror(
                APP_TITLE,
                "没有找到 lark-cli。\n请使用「独立版」（已内置 lark-cli），"
                "或先安装：npm i -g @larksuite/cli",
            )
            return
        self.log_line("① 检查飞书登录状态…")
        self.run_bg(lambda: self._login_probe(source), self._handle_login_state)

    def _notify(self, text: str) -> None:
        """从后台线程安全地把进度写到日志区。"""
        self._events.put(("log", text, None))

    def _login_probe(self, source) -> dict:
        """返回当前该走哪一步：ok / config（首次初始化） / login（扫码）。"""
        state = source.config_state()
        self._notify(f"   状态：{'未初始化' if state == 'unconfigured' else state}")
        if state == "unconfigured":
            self._notify("② 正在生成应用初始化链接…")
            proc, url = source.config_init_start()
            return {"stage": "config", "proc": proc, "url": url, "source": source}
        self._notify("② 读取登录凭据…")
        ok, info = source.auth_status()
        if ok:
            return {"stage": "ok", "info": info, "source": source}
        self._notify(f"   未登录（{info}），③ 正在生成登录二维码…")
        return {"stage": "login", "data": source.login_start(), "source": source}

    def _handle_login_state(self, result: dict) -> None:
        stage = result.get("stage")
        source = result.get("source")
        if stage == "ok":
            self.btn_login.configure(text="已登录")
            self.log_line(f"飞书已登录：{result.get('info')}")
            messagebox.showinfo(APP_TITLE, f"已登录飞书：{result.get('info')}")
            self.on_load()
        elif stage == "config":
            self._show_config_dialog(source, result["proc"], result["url"])
        elif stage == "login":
            self._show_login_dialog(source, result["data"])

    def _show_config_dialog(self, source, proc, url: str) -> None:
        """新电脑首次使用：先完成应用初始化（浏览器一次）。"""
        win = tk.Toplevel(self)
        win.title("首次使用：初始化飞书应用")
        win.geometry("500x420")
        win.transient(self)
        win.grab_set()
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="第一步：在浏览器里完成应用初始化",
                  font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, text="点下面的按钮打开页面，按提示确认即可（只需一次）。",
                  style="Hint.TLabel").pack(anchor="w", pady=(2, 10))

        url_var = tk.StringVar(value=url)
        ttk.Label(frame, textvariable=url_var, wraplength=450, justify="left",
                  relief="solid", borderwidth=1, padding=6,
                  foreground="#1a4d8f").pack(fill="x")

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(8, 12))

        def open_url() -> None:
            import webbrowser
            webbrowser.open(url)

        def copy_url() -> None:
            self.clipboard_clear()
            self.clipboard_append(url)

        ttk.Button(row, text="打开授权页面", command=open_url).pack(side="left")
        ttk.Button(row, text="复制链接", command=copy_url).pack(side="left", padx=(8, 0))

        status = ttk.Label(frame, text="完成后回到这里点「下一步」", style="Hint.TLabel")
        status.pack(anchor="w")

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(16, 0))

        def next_step() -> None:
            status.configure(text="正在确认初始化结果…")

            def done(ok: bool) -> None:
                if ok:
                    win.destroy()
                    self.log_line("应用初始化完成，继续扫码登录…")
                    self.run_bg(lambda: {"stage": "login", "data": source.login_start(),
                                         "source": source}, self._handle_login_state)
                else:
                    status.configure(text="还没检测到完成，请先在浏览器里确认后再点一次。")

            self.run_bg(lambda: source.config_init_finish(proc), done)

        ttk.Button(actions, text="下一步", command=next_step).pack(side="left")
        ttk.Button(actions, text="取消", command=lambda: (proc.kill(), win.destroy())).pack(side="left", padx=(8, 0))

    def _show_login_dialog(self, source, data: dict) -> None:
        win = tk.Toplevel(self)
        win.title("登录飞书")
        win.geometry("480x700")
        win.transient(self)
        win.grab_set()
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="用飞书扫下面的二维码，或打开链接授权",
                  font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, text="授权后回到这里点「我已完成授权」", style="Hint.TLabel").pack(anchor="w", pady=(2, 10))

        url_var = tk.StringVar(value=data["url"])
        url_box = ttk.Label(frame, textvariable=url_var, wraplength=430, justify="left",
                            relief="solid", borderwidth=1, padding=6,
                            foreground="#1a4d8f")
        url_box.pack(fill="x")

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(8, 10))

        def copy_url() -> None:
            self.clipboard_clear()
            self.clipboard_append(data["url"])
            ttk.Label(btns, text="已复制").pack(side="left", padx=(8, 0))

        def open_url() -> None:
            import webbrowser
            webbrowser.open(data["url"])

        ttk.Button(btns, text="打开授权页面", command=open_url).pack(side="left")
        ttk.Button(btns, text="复制链接", command=copy_url).pack(side="left", padx=(8, 0))

        from .label import qr_image
        qr = qr_image(data["url"], 300)
        photo = ImageTk.PhotoImage(qr)
        qr_label = ttk.Label(frame, image=photo)
        qr_label.image = photo  # type: ignore[attr-defined]
        qr_label.pack(pady=(4, 10))

        status = ttk.Label(frame, text=f"链接 {data.get('expires_in', 600) // 60} 分钟内有效",
                           style="Hint.TLabel")
        status.pack(anchor="w")

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(14, 0))

        def finish() -> None:
            status.configure(text="正在确认授权，请稍候…")
            win.update_idletasks()

            def done(ok: bool) -> None:
                if ok:
                    win.destroy()
                    self.btn_login.configure(text="已登录")
                    self.log_line("飞书登录成功")
                    messagebox.showinfo(APP_TITLE, "登录成功，开始加载任务。")
                    self.on_load()
                else:
                    status.configure(text="还没检测到授权，请先在飞书里确认后重试。")

            def job() -> bool:
                try:
                    return source.login_finish(data["code"])
                except Exception as exc:  # noqa: BLE001
                    self.log_line(f"登录失败：{exc}")
                    return False

            self.run_bg(job, done)

        ttk.Button(actions, text="我已完成授权", command=finish).pack(side="left")
        ttk.Button(actions, text="取消", command=win.destroy).pack(side="left", padx=(8, 0))

    def _auto_load(self) -> None:
        """启动后自动拉取任务：先确认已登录，未登录就只提示、不报错。"""
        name = self.source_var.get()
        if name == SOURCE_CLI:
            source = LarkCLISource(cli_path="")
            if not source.available:
                self.log_line("未检测到 lark-cli，跳过自动加载")
                return
            if self._busy:
                return

            def probe():
                if source.config_state() == "unconfigured":
                    return "config"
                ok, _info = source.auth_status()
                return "ok" if ok else "login"

            self.run_bg(probe, self._after_auto_probe)
            return
        if name == SOURCE_API:
            if not (self.var_app_id.get().strip() and self.var_app_secret.get().strip()):
                self.log_line("未配置 App ID / App Secret，跳过自动加载")
                return
        elif name != SOURCE_CLI:
            return
        if not self._busy:
            self.on_load()

    def _after_auto_probe(self, state: str) -> None:
        if state == "ok":
            self._refresh_login_hint()
            if not self.tasks and not self._busy:
                self.on_load()
            return
        if state == "config":
            tip = "这台电脑还没初始化飞书应用，点【飞书登录】按提示完成（只需一次）"
        else:
            tip = "还没登录飞书，点【飞书登录】扫码即可"
        self.log_line(tip)
        self.lbl_status.configure(text=tip)

    def on_test(self) -> None:
        self._save_cfg()
        try:
            source = self._make_source()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.log_line("正在测试连接…")
        self.run_bg(source.check, lambda msg: (self.log_line(msg), messagebox.showinfo(APP_TITLE, msg)))

    def on_load(self) -> None:
        if self._busy:
            return
        self._save_cfg()
        try:
            source = self._make_source()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.log_line("正在加载任务…")
        self.btn_load.state(["disabled"])

        def done(tasks: list[Task]) -> None:
            self.btn_load.state(["!disabled"])
            self.tasks = tasks
            self.selected = {self._row_key(t) for t in tasks}
            sites = sorted({t.site_name for t in tasks if t.site_name})
            self.cbo_site.configure(values=["全部"] + sites)
            self.var_site.set("全部")
            self.refresh_tree()
            self.log_line(f"加载完成：{len(tasks)} 条任务，{len(sites)} 个采集点")
            children = self.tree.get_children()
            if children:
                self.tree.focus(children[0])
                self.tree.selection_set(children[0])
                self.update_preview()

        self.run_bg(source.list_tasks, done)

    def refresh_tree(self) -> None:
        keyword = self.var_search.get().strip()
        site = self.var_site.get()
        only_missing = bool(self.var_only_missing.get())
        self.tree.delete(*self.tree.get_children())
        for task in self.tasks:
            if keyword and keyword not in f"{task.task_id}{task.task_name}{task.site_name}":
                continue
            if site and site != "全部" and task.site_name != site:
                continue
            if only_missing and task.has_code:
                continue
            mark = "☑" if self._row_key(task) in self.selected else "☐"
            self.tree.insert("", "end", iid=self._row_key(task), values=(
                mark, task.task_id, task.task_name, task.site_name,
                task.status, "有" if task.has_code else "无",
            ))
        self._update_sel_label()

    @staticmethod
    def _row_key(task: Task) -> str:
        return task.record_id or task.task_id

    def _on_only_missing(self) -> None:
        self.cfg["only_missing"] = bool(self.var_only_missing.get())
        save_config(self.cfg)
        self.refresh_tree()

    def _update_sel_label(self) -> None:
        visible = self.tree.get_children()
        visible_selected = sum(1 for i in visible if i in self.selected)
        self.lbl_sel.configure(text=f"已选 {len(self.selected)} / {len(self.tasks)}（当前列表 {visible_selected}）")
        self.lbl_status.configure(
            text=f"共 {len(self.tasks)} 条任务 · 已有码 {sum(1 for t in self.tasks if t.has_code)} 条"
        )

    def select_all(self, value: bool) -> None:
        for task in self.tasks:
            if value:
                self.selected.add(self._row_key(task))
            else:
                self.selected.discard(self._row_key(task))
        self.refresh_tree()

    def _on_tree_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if row in self.selected:
            self.selected.discard(row)
        else:
            self.selected.add(row)
        self.tree.set(row, "sel", "☑" if row in self.selected else "☐")
        self._update_sel_label()

    def _on_space(self, _event) -> None:
        row = self.tree.focus()
        if not row:
            return
        if row in self.selected:
            self.selected.discard(row)
        else:
            self.selected.add(row)
        self.tree.set(row, "sel", "☑" if row in self.selected else "☐")
        self._update_sel_label()

    def update_preview(self) -> None:
        row = self.tree.focus()
        task = next((t for t in self.tasks if self._row_key(t) == row), None)
        if not task:
            return
        img = render_label(TaskLabel(task.task_id, task.task_name, task.site_name))
        thumb = img.copy()
        thumb.thumbnail((296, 430), Image.LANCZOS)
        self._preview_img = ImageTk.PhotoImage(thumb)
        self.preview.configure(image=self._preview_img, text="")
        self.lbl_preview.configure(
            text=f"{task.task_id}  {task.task_name}\n采集点：{task.site_name or '（空）'}"
        )

    def selected_tasks(self) -> list[Task]:
        return [t for t in self.tasks if self._row_key(t) in self.selected]

    def _on_tree_double_click(self, event) -> None:
        """双击某行：生成大图并用系统看图程序打开。"""
        if self.tree.identify_column(event.x) == "#1":
            return
        row = self.tree.identify_row(event.y)
        task = next((t for t in self.tasks if self._row_key(t) == row), None)
        if not task:
            return
        out_dir = Path(self.cfg.get("out_dir") or (Path.home() / "Desktop" / "场景任务码"))
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{task.task_id}.png"
        path.write_bytes(png_bytes(render_label(task.to_label())))
        self.log_line(f"已生成大图：{path}")
        try:
            os.startfile(str(path))  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"打开图片失败：{exc}")

    # ------------------------------------------------------------ 同步
    def _current_profile(self) -> dict | None:
        name = self.var_pick.get()
        for prof in self._profiles():
            if prof.get("name") == name:
                return prof
        return None

    def on_stop_sync(self) -> None:
        if self._cancel.is_set():
            return
        self._cancel.set()
        self.lbl_progress.configure(text="正在停止…（当前这张传完就停）")
        self.log_line("已请求停止同步")

    def on_sync_current(self) -> None:
        profile = self._current_profile()
        if not profile:
            messagebox.showinfo(APP_TITLE, "当前选的是本地文件，不能同步飞书。请先选一个区域。")
            return
        self._start_sync([profile])

    def on_sync_all(self) -> None:
        profiles = [p for p in self._profiles() if p.get("base_token") and p.get("task_table")]
        if not profiles:
            messagebox.showwarning(APP_TITLE, "还没有配置任何表格。")
            return
        self._start_sync(profiles)

    def _start_sync(self, profiles: list[dict]) -> None:
        """同步执行入口：确认 → 后台跑 → 汇总。"""
        source = LarkCLISource(cli_path="")
        if not source.available:
            messagebox.showerror(APP_TITLE, "没有找到 lark-cli，请使用独立版。")
            return
        names = "\n".join(f"· {p['name']}" for p in profiles)
        if not messagebox.askyesno(
            APP_TITLE,
            f"将为以下 {len(profiles)} 个区域补齐「还没有二维码」的任务：\n\n{names}\n\n"
            "生成后自动上传并写回「场景任务码」，中途可以点「停止」。开始吗？",
        ):
            return
        self._save_cfg()
        out_dir = Path(self.cfg.get("out_dir") or (Path.home() / "Desktop" / "场景任务码"))
        out_dir.mkdir(parents=True, exist_ok=True)
        self._cancel.clear()
        self.progress["value"] = 0
        self.lbl_progress.configure(text="准备中…")
        self.log_line(f"开始同步 {len(profiles)} 个区域…")

        def progress(i: int, total: int, msg: str) -> None:
            self._events.put(("log", msg, i / max(total, 1)))

        def job():
            ok, _info = source.auth_status()
            if not ok:
                raise RuntimeError("还没有登录飞书，请先点右上角【登录飞书】。")
            return sync_all_tables(profiles, out_dir, only_missing=True,
                                   progress=progress, cancel=self._cancel.is_set)

        def done(results) -> None:
            self.progress["value"] = 0
            self.lbl_progress.configure(text="")
            if not results:
                self.log_line("同步结束（未处理任何区域）")
                messagebox.showinfo(APP_TITLE, "没有需要处理的内容。")
                return
            report = None
            try:
                report = write_sync_report(results, out_dir)
            except Exception:  # noqa: BLE001
                pass
            total_ok = sum(r["ok"] for r in results)
            total_fail = sum(len(r["failed"]) for r in results)
            lines = []
            for r in results:
                line = (f"{r['name']}：本次补 {r['ok']}/{r['pending']}，"
                        f"现有 {r['verified']}/{r['total']}")
                if r["failed"]:
                    line += f"，失败 {len(r['failed'])}"
                if r["skipped"]:
                    line += "（中途停止）"
                lines.append(line)
            self.log_line("同步完成：" + "；".join(lines))
            msg = "\n".join(lines) + f"\n\n合计成功 {total_ok} 张"
            if total_fail:
                first = next(r["failed"] for r in results if r["failed"])
                msg += f"，失败 {total_fail} 张。\n首个失败：{first[0]} → {first[1][:120]}"
            if report:
                msg += f"\n\n明细：{report}"
            messagebox.showinfo(APP_TITLE, msg)
            if not self._busy:
                self.on_load()

        self.run_bg(job, done)

    def open_out_dir(self) -> None:
        out_dir = Path(self.cfg.get("out_dir") or (Path.home() / "Desktop" / "场景任务码"))
        out_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(out_dir))  # noqa: S606

    # ------------------------------------------------------------ 日志
    def log_line(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        write_log(text.strip())


def main() -> None:
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = App()
    app.mainloop()
