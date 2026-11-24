"""常量与字段名（拆分自 core.py）

脱敏说明：原始 `core.py` 里硬编码了生产多维表格的 base_token / table_id，
推仓库时已替换为 `<FILL_ME_*>` 占位符，并允许用环境变量覆盖（部署时无需改源码）。
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------- 默认配置
DEFAULT_BASE_TOKEN = os.environ.get("QRLABEL_BASE_TOKEN", "<FILL_ME_BASE_TOKEN>")
DEFAULT_TASK_TABLE = os.environ.get("QRLABEL_TASK_TABLE", "<FILL_ME_TASK_TABLE>")
DEFAULT_SITE_TABLE = os.environ.get("QRLABEL_SITE_TABLE", "<FILL_ME_SITE_TABLE>")

F_NAME = "任务名称"
F_ID = "任务ID"
F_SITE = "所属采集点"
F_STATUS = "任务状态"
F_CODE = "场景任务码"

FEISHU_HOST = "https://open.feishu.cn"


class FeishuError(RuntimeError):
    pass
