"""飞书登录引导与初始化弹窗（拆分自 gui.py）"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from PIL import ImageTk

from .core import LarkCLISource
from .gui_config import APP_TITLE, SOURCE_API, SOURCE_CLI, SOURCE_FILE


class LoginMixin:
    """登录 / 初始化 / 自动加载探测。"""

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
