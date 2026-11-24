"""表设置、配置持久化与数据源工厂（拆分自 gui.py）"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, simpledialog, ttk

from .core import (
    DEFAULT_BASE_TOKEN,
    DEFAULT_SITE_TABLE,
    DEFAULT_TASK_TABLE,
    FeishuAPI,
    FileSource,
    LarkCLISource,
)
from .gui_config import APP_TITLE, SOURCE_API, SOURCE_CLI, SOURCE_FILE, save_config


class TableSettingsMixin:
    """选择区域 / 表设置 / 配置落盘 / 数据源实例化。"""

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

    # ------------------------------------------------------------ 同步
    def _current_profile(self) -> dict | None:
        name = self.var_pick.get()
        for prof in self._profiles():
            if prof.get("name") == name:
                return prof
        return None
