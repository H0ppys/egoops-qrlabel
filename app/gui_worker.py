"""后台线程、加载与同步批处理（拆分自 gui.py）"""

from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
from typing import Callable

from tkinter import messagebox

from .core import (
    LarkCLISource,
    Task,
    friendly_error,
    preflight,
    sync_all_tables,
    write_sync_report,
)
from .gui_config import APP_TITLE


class WorkerMixin:
    """线程泵、按钮状态、加载任务与一键同步。"""

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
