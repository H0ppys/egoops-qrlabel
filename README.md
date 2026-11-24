# 场景任务码生成器（qr-label）

## 1. 一句话定位

把飞书多维表格里的采集任务，一键生成 **A4 竖版「场景任务码」标签**（PNG + 打印版 PDF），
并把二维码**自动回传**到表格的「场景任务码」附件字段；同时提供 tkinter 图形界面与可挂计划任务的 CLI。

生成的版式与表里已有的 42 张标签像素级一致：A4 @144dpi（1190×1684）、白底黑字、标题自动缩放、
二维码内容为**纯数字任务 ID**（手机相机 / 扫码枪 / 微信均可直接扫出）。

## 2. 原始来源

| 项目 | 值 |
| --- | --- |
| 工作区路径 | `C:\Users\Administrator\Documents\deepseek-harness\default-workspace\qr-label\` |
| 原始文件 | `app\core.py`（42,223 B / 1040 行）、`app\gui.py`（44,519 B / 1015 行）、`app\label.py`、`app\cli.py`、`app\__init__.py` |
| 打包配置 | 根目录 `场景任务码生成器*.spec` 四份、`version_info.txt`、`build.py` |
| 版本 | 界面标注 `v1.1 · A4@144dpi · 二维码内容=任务ID`；文档标注 `v2.5（独立版）`；`app.__version__ = 1.0.0` |
| 原始入口 | `run.py`（默认 GUI，带 `--cli` 走 CLI）、`run_cli.py`（纯 CLI 打包入口） |

本仓库**只做模块化拆分与脱敏**，不改渲染参数、不改业务流程。原文件逐字节镜像在 `legacy/`。

## 3. 目录结构

```
egoops-qrlabel/
├── README.md                  # 本文
├── LICENSE                    # MIT
├── .gitignore
├── requirements.txt
├── main.py                    # 入口：python main.py（GUI） / python main.py --cli ...（CLI）
├── run_cli.py                 # 纯 CLI 打包入口（等价原 run_cli.py）
├── app/
│   ├── __init__.py            # 版本号 + 公共符号重导出（import app 后原符号可用）
│   ├── core.py                # 兼容层：重导出 core_* 全部符号（88 行，原 1040 行）
│   ├── core_config.py         # 常量 / 字段名 / FeishuError
│   ├── core_models.py         # Task 模型 + 多维表格单元格解析
│   ├── core_paths.py          # 可写临时目录 / 调试日志 / 锁清理 / 上传暂存
│   ├── core_api.py            # 飞书开放平台客户端 FeishuAPI
│   ├── core_larkcli.py        # 本机 lark-cli 数据源 LarkCLISource
│   ├── core_files.py          # 本地 Excel/CSV/JSON/NDJSON 数据源 FileSource
│   ├── core_env.py            # preflight 环境自检 + friendly_error
│   ├── core_batch.py          # generate_files 离线批量出图
│   ├── core_sync.py           # sync_all_tables / write_sync_report 回传
│   ├── gui.py                 # App 窗口装配 + main()（213 行，原 1015 行）
│   ├── gui_config.py          # 常量 / resource_path / write_log / load_config / save_config
│   ├── gui_settings.py        # TableSettingsMixin  区域选择 / 表设置 / 配置落盘
│   ├── gui_login.py           # LoginMixin          飞书登录 / 应用初始化 / 自动加载
│   ├── gui_table.py           # TablePreviewMixin   任务表渲染 / 勾选 / 版式预览
│   ├── gui_worker.py          # WorkerMixin         线程泵 / 加载任务 / 一键补齐
│   ├── label.py               # 版式常量与渲染（A4 标签、二维码、PDF）
│   └── cli.py                 # 命令行（argparse，原样保留）
├── assets/
│   ├── icon.ico / icon.png / icon32.png
│   ├── fonts/NotoSansSC-VF.ttf        # 版式字体（OFL），17 MB
│   └── 模板-任务清单.csv              # 离线导入模板
├── demo_out/                  # 3 个示例产物（2 PNG + 1 打印版 PDF）
├── docs/
│   ├── ARCHITECTURE.md        # 模块职责与数据流
│   ├── SPLIT.md               # 行段 → 新模块映射表
│   └── PACKAGING.md           # PyInstaller 打包 / 解包说明
├── legacy/                    # 原始 app/*.py 镜像（只读参照，不参与运行，见 legacy/NOTE.md）
├── packaging/                 # 脱敏后的 spec / version_info / build.py
└── tests/smoke_test.py        # can-import + CLI --help + 端到端出图冒烟
```

## 4. 安装与运行

```bash
python -m pip install -r requirements.txt
```

图形界面：

```bash
python main.py
```

命令行（`main.py --cli` 或直接 `python run_cli.py`）：

```bash
# 本地表格 → PNG + PDF（完全离线，不需要飞书登录）
python main.py --cli --source file --file "assets/模板-任务清单.csv" --out out --pdf

# 本机已登录的 lark-cli → 生成 + 回传飞书
python main.py --cli --source cli --exclude-done --upload

# 只看清单，不生成
python main.py --cli --source cli --list

# 飞书开发平台应用身份
python run_cli.py --source api --app-id cli_xxx --app-secret xxx --upload
```

冒烟自检：

```bash
python -X utf8 tests/smoke_test.py
```

> GUI 的飞书登录需要本机装有 `lark-cli`（`npm i -g @larksuite/cli`）；
> 纯离线出图（`--source file`）不依赖任何飞书环境。

## 5. 模块说明

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `app/core_config.py` | 26 | 默认 base_token / table_id（占位符）、字段名常量、`FeishuError` |
| `app/core_models.py` | 82 | `Task` 数据模型、`_text_of` / `_link_record_ids` / `_attachment_tokens` / `_find_tokens` 单元格解析 |
| `app/core_paths.py` | 126 | `_exe_dir`、`work_dir`（多级降级找可写目录）、`stage_upload_file`、`_debug_log`、锁状态与死锁清理、凭据目录镜像 |
| `app/core_api.py` | 220 | `FeishuAPI`：tenant_access_token、list_records / list_tasks / upload_png / set_code |
| `app/core_larkcli.py` | 362 | `LarkCLISource`：调用本机 lark-cli 读表/上传/登录，多调用方式×工作目录回退 |
| `app/core_files.py` | 96 | `FileSource`：xlsx / csv / json / ndjson 读取与列名兼容 |
| `app/core_env.py` | 66 | `preflight` 启动自检、`friendly_error` 错误人话化 |
| `app/core_batch.py` | 34 | `generate_files`：批量 PNG + 可选 PDF |
| `app/core_sync.py` | 119 | `_sync_one_table` / `sync_all_tables` / `write_sync_report` 幂等补码回传 |
| `app/core.py` | 88 | 兼容层：重导出上面全部符号，`from app.core import X` 行为不变 |
| `app/gui_config.py` | 118 | 界面常量、`resource_path`、`write_log`、`load_config` / `save_config`、预置区域 |
| `app/gui_settings.py` | 170 | `TableSettingsMixin`：区域下拉、表设置弹窗、配置落盘、数据源工厂 |
| `app/gui_login.py` | 265 | `LoginMixin`：设备码登录、应用初始化弹窗、自动加载探测 |
| `app/gui_table.py` | 123 | `TablePreviewMixin`：任务表渲染、勾选/筛选、右侧版式预览、双击出大图 |
| `app/gui_worker.py` | 214 | `WorkerMixin`：线程池泵、按钮状态、加载任务、一键补齐与停止 |
| `app/gui.py` | 213 | `App` 装配（mixin 组合）+ `_build_ui` 视觉层级 + `main()` |
| `app/label.py` | 354 | 版式常量、字体、二维码绘制、`render_label` / `render_pdf` / `render_sheet_pdf` |
| `app/cli.py` | 170 | argparse 参数、任务过滤、批量生成与上传的 CLI 流程 |

## 6. 配置项

运行时配置写在 `%APPDATA%\ScenarioQRCode\config.json`（GUI 自动维护，不进仓库）；
默认值来自 `app/core_config.py` 与 `app/gui_config.py`，仓库里全部是占位符：

```python
DEFAULT_BASE_TOKEN = os.environ.get("QRLABEL_BASE_TOKEN", "<FILL_ME_BASE_TOKEN>")
DEFAULT_TASK_TABLE = os.environ.get("QRLABEL_TASK_TABLE", "<FILL_ME_TASK_TABLE>")
DEFAULT_SITE_TABLE = os.environ.get("QRLABEL_SITE_TABLE", "<FILL_ME_SITE_TABLE>")
```

部署时可任选一种方式填真实值：

1. 环境变量：`QRLABEL_BASE_TOKEN` / `QRLABEL_TASK_TABLE` / `QRLABEL_SITE_TABLE`；
2. GUI「表设置…」填写后落盘到 `config.json`；
3. CLI 参数：`--base-token` / `--table-id` / `--site-table`。

需要应用身份（App ID / App Secret）时用 CLI 参数或 `config.json` 传入，**不要写进源码**：

```json
{
  "source": "飞书开放平台（App ID / Secret）",
  "app_id": "<FILL_ME_APP_ID>",
  "app_secret": "<FILL_ME_APP_SECRET>",
  "base_token": "<FILL_ME_BASE_TOKEN>",
  "task_table": "<FILL_ME_TASK_TABLE>",
  "site_table": "<FILL_ME_SITE_TABLE>",
  "out_dir": "<FILL_ME_OUT_DIR>"
}
```

## 7. 打包（PyInstaller spec 要点）

`packaging/` 内含四份脱敏 spec（GUI 单文件版、CLI 版、独立版 onedir、免解压版 onedir）、
`version_info.txt` 与一键脚本 `build.py`。要点：

- `datas`：`assets/fonts/NotoSansSC-VF.ttf → app/fonts`、`assets/icon.ico → assets`
  （打包目标目录仍是 `app/fonts`，与源码运行期字体搜索顺序一致）。
- `hiddenimports`：`PIL._tkinter_finder` + `collect_submodules('qrcode')`。
- `excludes`：`cv2 / numpy / pandas / matplotlib / scipy / docx / pyzbar`（独立版另加 `lxml`、`PIL.AvifImagePlugin`）。
- `uac_admin=True`、`console=False`（CLI 版为 `True`）、`icon=['assets/icon.ico']`、`version='version_info.txt'`。

```bash
python -m pip install -r requirements.txt pyinstaller
python packaging/build.py --clean          # 等价原 build.py
# 或指定 spec（必须在仓库根执行，spec 内相对路径以 cwd 为准）
python -m PyInstaller packaging/场景任务码生成器.spec --noconfirm
```

详见 [`docs/PACKAGING.md`](docs/PACKAGING.md)。

## 8. 拆分说明

`app/core.py`（1040 行）拆成 9 个 `core_*.py`，`app/gui.py`（1015 行）拆成 5 个 `gui_*.py` + 装配层，
原公共符号通过 `app/core.py` 与 `app/__init__.py` 完整重导出。
逐行段映射表、mixin 划分依据与保真度验证见 [`docs/SPLIT.md`](docs/SPLIT.md)，
模块职责与数据流见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

> 脱敏提示：原 `core.py` / `gui.py` 硬编码了 3 张生产多维表格的 base_token / table_id 与区域名，
> 仓库里已统一替换为 `<FILL_ME_*>` 占位符与「示例区域 1/2/3」；
> `legacy/` 镜像同样做了这一处替换（其余字节一致），说明见 `legacy/NOTE.md`。
