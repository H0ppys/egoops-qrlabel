"""场景任务码生成器（GUI + 命令行）。

模块化结构见 docs/ARCHITECTURE.md；拆分映射见 docs/SPLIT.md。
``app.core`` 仍在原路径提供全部公共符号（第 1 条要求：``import app`` 后原符号可用）。
"""

from __future__ import annotations

__version__ = "1.0.0"

from .core import (  # noqa: F401
    DEFAULT_BASE_TOKEN,
    DEFAULT_SITE_TABLE,
    DEFAULT_TASK_TABLE,
    F_CODE,
    F_ID,
    F_NAME,
    F_SITE,
    F_STATUS,
    FEISHU_HOST,
    FeishuAPI,
    FeishuError,
    FileSource,
    LarkCLISource,
    Task,
    friendly_error,
    generate_files,
    preflight,
    stage_upload_file,
    sync_all_tables,
    work_dir,
    write_sync_report,
)
from .label import (  # noqa: F401
    DPI,
    PAGE_H,
    PAGE_W,
    QR_SIZE,
    TaskLabel,
    png_bytes,
    qr_image,
    render_label,
    render_pdf,
    render_sheet_pdf,
)

__all__ = [
    "DEFAULT_BASE_TOKEN",
    "DEFAULT_SITE_TABLE",
    "DEFAULT_TASK_TABLE",
    "DPI",
    "F_CODE",
    "F_ID",
    "F_NAME",
    "F_SITE",
    "F_STATUS",
    "FEISHU_HOST",
    "FeishuAPI",
    "FeishuError",
    "FileSource",
    "LarkCLISource",
    "PAGE_H",
    "PAGE_W",
    "QR_SIZE",
    "Task",
    "TaskLabel",
    "__version__",
    "friendly_error",
    "generate_files",
    "png_bytes",
    "preflight",
    "qr_image",
    "render_label",
    "render_pdf",
    "render_sheet_pdf",
    "stage_upload_file",
    "sync_all_tables",
    "work_dir",
    "write_sync_report",
]


def __getattr__(name):
    """GUI 相关符号按需导入，避免 `import app`（CLI/无桌面场景）拉起 tkinter。"""
    if name in ("App", "gui", "gui_main"):
        from . import gui as _gui

        return {"App": _gui.App, "gui": _gui, "gui_main": _gui.main}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
