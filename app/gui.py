"""图形界面入口：App 只保留窗口装配，行为分散在 gui_* mixin（拆分自 gui.py）。

拆分结构：

    gui_config.py   常量、resource_path、write_log、load_config/save_config
    gui_settings.py TableSettingsMixin  选择区域 / 表设置 / 配置落盘 / 数据源工厂
    gui_login.py    LoginMixin          飞书登录、应用初始化、自动加载探测
    gui_table.py    TablePreviewMixin   任务表渲染 / 勾选 / 右侧版式预览
    gui_worker.py   WorkerMixin         线程泵、加载任务、一键补齐同步
    gui.py          App（窗口装配 + 视觉层级）+ main()

注意：mixin 方法体逐字保留原 `App` 类实现，只改变所在文件，不改变行为。
"""

from __future__ import annotations

import queue
import threading

import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from .core import DEFAULT_BASE_TOKEN, DEFAULT_SITE_TABLE, DEFAULT_TASK_TABLE, Task
from .gui_config import (
    APP_TITLE,
    SOURCE_API,
    SOURCE_CLI,
    SOURCE_FILE,
    load_config,
    resource_path,
)
from .gui_login import LoginMixin
from .gui_settings import TableSettingsMixin
from .gui_table import TablePreviewMixin
from .gui_worker import WorkerMixin


class App(LoginMixin, TableSettingsMixin, TablePreviewMixin, WorkerMixin, tk.Tk):
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


def main() -> None:
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = App()
    app.mainloop()
