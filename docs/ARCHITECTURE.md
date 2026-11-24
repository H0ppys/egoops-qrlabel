# 架构说明（ARCHITECTURE）

## 一、总体分层

```
                        ┌──────────────────────────┐
   用户                  │  main.py / run_cli.py    │
                        └───────────┬──────────────┘
                    ┌───────────────┴────────────────┐
                    │                                │
             ┌──────▼──────┐                  ┌──────▼──────┐
             │  app/gui.py │ (tkinter)        │  app/cli.py │ (argparse)
             │  App 装配层  │                  │  批处理入口  │
             └──────┬──────┘                  └──────┬──────┘
        mixin 组合   │                                │
   gui_settings ─────┤                                │
   gui_login    ─────┤                                │
   gui_table    ─────┤                                │
   gui_worker   ─────┤                                │
                     └──────────────┬─────────────────┘
                                    │ 只依赖 app.core 的公共符号
                        ┌───────────▼──────────────┐
                        │      app/core.py         │ 兼容层（重导出）
                        └───────────┬──────────────┘
        ┌───────────┬───────────────┼───────────────┬──────────────┐
   core_config  core_models     core_paths      core_env      core_batch
        │           │               │
        │           ├── core_api ───┘                （HTTP / urllib）
        │           ├── core_larkcli （子进程 lark-cli）
        │           ├── core_files   （xlsx/csv/json）
        │           └── core_sync    （编排：生成→上传→写回→报表）
        │
        └────────── app/label.py   （版式常量 + Pillow 渲染 + qrcode）
```

依赖规则：**箭头单向**。`label` 不知道 `core` 的存在；`core_*` 之间只允许
`config → models/paths → api/larkcli/files/env/batch → sync`；GUI 只经由 `app.core` 的公共符号访问底层。

## 二、core 各模块职责

| 模块 | 职责 | 关键入口 | 外部依赖 |
| --- | --- | --- | --- |
| `core_config` | 常量、字段名、`FeishuError` | `DEFAULT_*`、`F_*`、`FEISHU_HOST` | 无（仅 `os.environ` 覆盖） |
| `core_models` | 数据模型与单元格解析 | `Task`、`_text_of`、`_link_record_ids`、`_attachment_tokens`、`_find_tokens` | `label.TaskLabel` |
| `core_paths` | 可写目录、日志、锁清理、凭据镜像、上传暂存 | `work_dir`、`stage_upload_file`、`_exe_dir`、`_debug_log`、`_clear_stale_locks`、`_profile_mirror`、`_lock_state` | 标准库 |
| `core_api` | 飞书开放平台（tenant_access_token） | `FeishuAPI.list_tasks/upload_png/set_code` | `urllib` |
| `core_larkcli` | 本机 lark-cli 数据源 | `LarkCLISource`（含 `auth_status` / `login_start` / `config_init_*`） | `subprocess` |
| `core_files` | 本地表格数据源 | `FileSource.list_tasks` | `openpyxl`（可选）、`csv`、`json` |
| `core_env` | 启动自检与错误翻译 | `preflight`、`friendly_error` | `subprocess` |
| `core_batch` | 离线批量出图 | `generate_files` | `label` |
| `core_sync` | 幂等补码编排 + CSV 报表 | `sync_all_tables`、`write_sync_report` | `core_larkcli`、`core_paths`、`label` |
| `core` | **兼容层**：重导出以上全部 32 个顶层符号 | — | 以上全部 |

## 三、GUI 各模块职责

`App` 是 `LoginMixin + TableSettingsMixin + TablePreviewMixin + WorkerMixin + tk.Tk` 的组合，
每个 mixin 的方法体都是原 `App` 的实现，逐字未改，因此 `self.xxx` 互相调用的语义完全不变。

| 模块 | 职责 | 主要方法 |
| --- | --- | --- |
| `gui_config` | 界面常量、资源路径、日志、配置读写、预置区域 | `resource_path`、`write_log`、`load_config`、`save_config` |
| `gui_settings` | 区域选择、表设置、配置落盘、数据源工厂 | `_init_table_ui`、`_on_pick_change`、`_open_table_settings`、`_make_source`、`_save_cfg` |
| `gui_login` | 登录与初始化（设备码 + 应用初始化）、自动加载探测 | `on_login`、`_login_probe`、`_show_login_dialog`、`_show_config_dialog`、`_auto_load` |
| `gui_table` | 任务表渲染、勾选、筛选、版式预览 | `refresh_tree`、`_on_tree_click`、`update_preview`、`_on_tree_double_click` |
| `gui_worker` | 线程泵、忙闲态、加载任务、一键同步 | `run_bg`、`_pump_events`、`on_load`、`on_sync_all`、`_start_sync`、`log_line` |
| `gui` | 窗口装配（`__init__`）+ 视觉层级（`_build_ui`）+ `main()` | `App`、`main` |

## 四、数据流

### 1) 离线出图（CLI 最常用）

```
文件(xlsx/csv/json/ndjson)
   │ core_files.FileSource.list_tasks
   ▼
Task[] ──► core_batch.generate_files ──► label.render_label ──► PNG(1190×1684 @144dpi)
                                     └─► label.render_pdf  ──► A4 打印版 PDF
```

### 2) 飞书补码（GUI「一键补齐」/ `--upload`）

```
Task[] ──► label.render_label ──► PNG bytes
   │                                │
   │                                ▼
   │                       core_paths.stage_upload_file   （放到 lark-cli 允许的目录）
   │                                ▼
   │                       core_larkcli.upload_png  ──► file_token
   │                                ▼
   └───────────────────────  set_code(record_id, token)  写回「场景任务码」附件字段
                                    ▼
                          重新 list_tasks 复核 has_code
                                    ▼
                          core_sync.write_sync_report → 同步结果_*.csv
```

幂等性：`only_missing=True` 时只处理 `has_code == False` 的任务，重复点不会重复上传；
中途「停止」只会打断当前循环，已上传的不回滚，下次继续补剩下的。

### 3) 登录（首次使用）

```
GUI on_login
  └─ LarkCLISource.config_state()
       ├─ "unconfigured" → config_init_start() 拿授权链接（浏览器确认）→ config_init_finish()
       ├─ "login"        → login_start() 拿设备码/URL → 画二维码 → login_finish(device_code)
       └─ "ok"           → 直接 on_load()
```

三种数据源通过 `_make_source()` 多态切换：`FeishuAPI`（应用身份）/ `LarkCLISource`（本机登录）/ `FileSource`（离线）。

## 五、运行环境要点

- **临时目录降级**：`core_paths.work_dir()` 依次尝试 `%TEMP%` → `TEMP` → `TMP` → `~/files` → cwd → exe 目录，
  受限环境（企业策略 / 沙箱 / 压缩包内直接运行）下仍能拿到可写目录。
- **lark-cli 调用回退**：`LarkCLISource._run()` 按 `native / native-home / cmd / cmd-home / exe-home` 组合尝试，
  遇到 `lock` / `temporarily` 退避重试，并把 `USERPROFILE` 指向可写镜像（`_profile_mirror`）。
- **日志**：`%APPDATA%\ScenarioQRCode\logs\run-YYYYMMDD.log`（GUI 行为）与 `cli-debug.log`（底层调用细节）。
- **配置**：`%APPDATA%\ScenarioQRCode\config.json`，包含 `source`、表标识、`out_dir`、`profiles`、`only_missing` 等；
  `app_id` / `app_secret` 只存在本地，仓库里始终保持 `<FILL_ME_*>`。

## 六、保真度与已知缺陷

拆分保真度验证（符号集合、`self` 属性连通性、真实建窗、渲染逐字节一致）见
[`SPLIT.md` 第四节](SPLIT.md#四保真度验证本地实测)。
已知缺陷（CSV 报表因原文件漏 import 而未生成）按原样保留，说明见
[`SPLIT.md` 第六节](SPLIT.md#六已知缺陷保持原样未修)。
