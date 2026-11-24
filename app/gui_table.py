"""任务表格、筛选与版式预览组件（拆分自 gui.py）"""

from __future__ import annotations

import os
from pathlib import Path

from tkinter import messagebox

from PIL import Image, ImageTk

from .core import Task
from .gui_config import APP_TITLE, save_config
from .label import TaskLabel, png_bytes, render_label


class TablePreviewMixin:
    """任务表渲染、勾选状态与右侧预览。"""

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
