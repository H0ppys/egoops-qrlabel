# legacy/ —— 原始 app/*.py 只读镜像

本目录是拆分前 `qr-label/app/` 的镜像，用于对照阅读，**不参与运行**，也不要修改。

| 文件 | 原始大小 | 说明 |
| --- | --- | --- |
| `core.py` | 42,223 B / 1040 行 | 已拆成 `app/core_*.py` 九个模块 + `app/core.py` 兼容层 |
| `gui.py` | 44,519 B / 1015 行 | 已拆成 `app/gui_config.py` + 四个 mixin + `app/gui.py` 装配层 |
| `label.py` | 11,548 B / 351 行 | 原样复用为 `app/label.py`（仅 `_font_dirs` 增加 `assets/fonts` 候选目录） |
| `cli.py` | 7,581 B / 170 行 | 原样复用为 `app/cli.py` |
| `__init__.py` | 78 B / 3 行 | 原样复用为 `app/__init__.py` 的版本号部分（新增了公共符号重导出） |

## 与原始文件的唯一偏差（脱敏）

原 `core.py` / `gui.py` 里硬编码了 3 张生产多维表格的 base_token、table_id 与区域名。
为了让仓库可以公开推送，这里与 `app/` 做了**同一套字符串替换**（共 28 处，逻辑与结构未变）：

| 原值类型 | 替换为 |
| --- | --- |
| `RmXtbn4…`（default base_token） | `<FILL_ME_BASE_TOKEN>` |
| `tbltCUZ…` / `tblL4vI…` | `<FILL_ME_TASK_TABLE>` / `<FILL_ME_SITE_TABLE>` |
| 另两张表的 base_token / table_id | `<FILL_ME_BASE_TOKEN_2..3>` / `<FILL_ME_TASK_TABLE_2..3>` / `<FILL_ME_SITE_TABLE_2..3>` |
| `广州（原表 · 65 条 / 23 点）` 等三个区域名 | `示例区域 1` / `示例区域 2` / `示例区域 3` |

真实值请从原始工作区 `qr-label/app/core.py`、`qr-label/app/gui.py` 取，
或直接使用本机运行期配置 `%APPDATA%\ScenarioQRCode\config.json`。

> 说明：规范要求 legacy 逐字节镜像，而仓库规范同时禁止提交 token。
> 这里选择脱敏（与 `app/` 一致），保证仓库可直接推送；除上述字符串外，其余内容与原始文件逐字节一致。

## 阅读提示

这些文件的包内相对导入（`from .label import ...`）在 `legacy/` 平铺布局下不可直接运行；
需要跑原始版本请回到源目录 `qr-label/`，或在仓库根用 `python -c "import legacy.core"` 之外的方式验证。
