"""离线批量出图（PNG + PDF）（拆分自 core.py）"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .label import png_bytes, render_label, render_pdf
from .core_models import Task

# ---------------------------------------------------------------- 批量流程
def generate_files(
    tasks: list[Task],
    out_dir: Path,
    make_pdf: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    png_paths: list[Path] = []
    total = len(tasks)
    for i, task in enumerate(tasks, 1):
        img = render_label(task.to_label())
        path = out_dir / f"{task.task_id}.png"
        path.write_bytes(png_bytes(img))
        png_paths.append(path)
        if progress:
            progress(i, total, f"生成 {task.task_id}.png")
    pdf_path = None
    if make_pdf and tasks:
        pdf_path = out_dir / f"场景任务码_{len(tasks)}张.pdf"
        pdf_path.write_bytes(render_pdf([t.to_label() for t in tasks]))
        if progress:
            progress(total, total, f"生成 {pdf_path.name}")
    return {"png": png_paths, "pdf": pdf_path}
