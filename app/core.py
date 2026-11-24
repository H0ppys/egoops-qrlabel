"""核心逻辑兼容层（拆分自 core.py）。

原始 41KB 单文件已按职责拆成九个子模块：

    core_config.py   常量 / 字段名 / FeishuError
    core_models.py   Task 模型 + 多维表格单元格解析
    core_paths.py    可写临时目录、调试日志、锁清理、上传暂存
    core_api.py      飞书开放平台客户端 FeishuAPI
    core_larkcli.py  本机 lark-cli 数据源 LarkCLISource
    core_files.py    本地文件数据源 FileSource
    core_env.py      启动自检 preflight + friendly_error
    core_batch.py    离线批量出图 generate_files
    core_sync.py     回传同步 sync_all_tables + write_sync_report

本文件只做符号重导出，保证 ``from .core import X`` / ``app.core.X`` 与拆分前完全一致。
"""

from __future__ import annotations

from .core_api import FeishuAPI
from .core_batch import generate_files
from .core_config import (
    DEFAULT_BASE_TOKEN,
    DEFAULT_SITE_TABLE,
    DEFAULT_TASK_TABLE,
    F_CODE,
    F_ID,
    F_NAME,
    F_SITE,
    F_STATUS,
    FEISHU_HOST,
    FeishuError,
)
from .core_env import friendly_error, preflight
from .core_files import FileSource, _pick
from .core_larkcli import LarkCLISource
from .core_models import (
    Task,
    _attachment_tokens,
    _find_tokens,
    _link_record_ids,
    _text_of,
)
from .core_paths import (
    _clear_stale_locks,
    _debug_log,
    _exe_dir,
    _lock_state,
    _profile_mirror,
    stage_upload_file,
    work_dir,
)
from .core_sync import _sync_one_table, sync_all_tables, write_sync_report

__all__ = [
    "DEFAULT_BASE_TOKEN",
    "DEFAULT_SITE_TABLE",
    "DEFAULT_TASK_TABLE",
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
    "Task",
    "_attachment_tokens",
    "_clear_stale_locks",
    "_debug_log",
    "_exe_dir",
    "_find_tokens",
    "_link_record_ids",
    "_lock_state",
    "_pick",
    "_profile_mirror",
    "_sync_one_table",
    "_text_of",
    "friendly_error",
    "generate_files",
    "preflight",
    "stage_upload_file",
    "sync_all_tables",
    "work_dir",
    "write_sync_report",
]
