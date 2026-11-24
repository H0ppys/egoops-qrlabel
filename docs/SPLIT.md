# 拆分映射表（SPLIT）

源文件（只读）：`qr-label/app/core.py`（42,223 B / 1040 行）、`qr-label/app/gui.py`（44,519 B / 1015 行）。
合计 **86,742 B ≈ 84.7 KiB / 2055 行**，本仓库拆成 **9 个 core 子模块 + 5 个 gui mixin + 2 个装配层**。

拆分原则：

1. **纯搬运**：函数/类体逐字保留，只换所在文件；新增内容仅限模块 docstring、`from __future__`、import 语句、类头。
2. **无循环导入**：按 `config → models/paths → api/larkcli/files/env/batch → sync` 单向分层，`core.py` 只做重导出。
3. **GUI 用 mixin 而不是重写方法**：tkinter 的方法都能通过 `self` 访问彼此，改成 mixin 后方法体一个字符都不用改，
   `class App(LoginMixin, TableSettingsMixin, TablePreviewMixin, WorkerMixin, tk.Tk)` 只是换个组合方式。
4. **公共符号零丢失**：`app/core.py` 重导出原 core 的全部 32 个顶层符号；`app/__init__.py` 重导出主要公共符号，
   `import app` 后 `app.Task / app.render_label / app.generate_files ...` 仍可用。

---

## 一、core.py → core_*.py（1040 行 → 9 模块 + 兼容层）

| 原文件 | 行段 / 符号 | 新模块 | 说明 |
| --- | --- | --- | --- |
| core.py | 1-7 模块 docstring（三种数据源说明） | app/core.py | 说明搬到兼容层 docstring |
| core.py | 9-29 import 区 | 各子模块自行 import | 按需裁剪，无副作用 |
| core.py | 31-43 `DEFAULT_BASE_TOKEN` / `DEFAULT_TASK_TABLE` / `DEFAULT_SITE_TABLE` / `F_NAME`~`F_CODE` / `FEISHU_HOST` | app/core_config.py | 常量集中，供 api/larkcli/files 共用（脱敏为 `<FILL_ME_*>` + 环境变量覆盖） |
| core.py | 45-47 `FeishuError` | app/core_config.py | 异常基类放常量旁边，避免 api/larkcli 互相 import |
| core.py | 49-66 `Task`（含 `has_code` / `to_label`） | app/core_models.py | 数据模型，只依赖 label.TaskLabel |
| core.py | 67-83 `_text_of` | app/core_models.py | 多维表格单元格 → 文本 |
| core.py | 86-97 `_link_record_ids` | app/core_models.py | 关联字段解析 |
| core.py | 100-108 `_attachment_tokens` | app/core_models.py | 附件字段解析 |
| core.py | 111-306 `FeishuAPI`（`_request` / `_token` / `list_records` / `list_sites` / `list_tasks` / `upload_png` / `set_code` / `check`） | app/core_api.py | 唯一依赖 urllib 的 HTTP 层 |
| core.py | 309-629 `LarkCLISource`（`find_cli` / `_native_exe` / `_run` / `_records` / `list_sites` / `list_tasks` / `upload_png` / `set_code` / `check` / `_raw` / `config_state` / `config_init_start` / `config_init_finish` / `auth_status` / `login_start` / `login_finish`） | app/core_larkcli.py | 体量最大（321 行），保留完整 |
| core.py | 632-635 `_exe_dir` | app/core_paths.py | 路径解析 |
| core.py | 638-646 `_debug_log` | app/core_paths.py | `%APPDATA%\ScenarioQRCode\logs\cli-debug.log` |
| core.py | 649-659 `_lock_state` | app/core_paths.py | lark-cli 锁诊断 |
| core.py | 662-680 `_profile_mirror` | app/core_paths.py | 低权限/沙箱下镜像 `~/.lark-cli` |
| core.py | 683-699 `_clear_stale_locks` | app/core_paths.py | 删死锁（删不掉即活锁） |
| core.py | 811-844 `work_dir` | app/core_paths.py | 多级降级找可写临时目录 |
| core.py | 847-855 `stage_upload_file` | app/core_paths.py | lark-cli `--file` 允许目录内暂存 |
| core.py | 702-759 `_sync_one_table` | app/core_sync.py | 单表幂等补码：生成→上传→写回→复核 |
| core.py | 762-787 `sync_all_tables` | app/core_sync.py | 多表串行 + 可中断 |
| core.py | 790-808 `write_sync_report` | app/core_sync.py | 同步结果 CSV（utf-8-sig） |
| core.py | 858-883 `preflight` | app/core_env.py | 临时目录/令牌自检 |
| core.py | 886-913 `friendly_error` | app/core_env.py | 英文报错 → 人话 |
| core.py | 916-927 `_find_tokens` | app/core_models.py | 递归捞 file_token（larkcli 上传结果解析用） |
| core.py | 930-1002 `FileSource`（`list_tasks` / `_read_xlsx` / `_read_csv` / `_read_json`） | app/core_files.py | 离线数据源 |
| core.py | 1005-1014 `_pick` | app/core_files.py | 列名兼容取值 |
| core.py | 1017-1040 `generate_files` | app/core_batch.py | 批量 PNG + 可选 PDF |

依赖方向（无环）：

```
core_config ─┬─> core_models ─> core_api
             ├─> core_paths  ─> core_larkcli ─> core_sync
             └────────────────> core_env / core_files / core_batch
app/core.py = 以上全部符号的重导出（32 个顶层符号，含下划线私有名）
```

## 二、gui.py → gui_*.py（1015 行 → 5 mixin/config + 装配层）

| 原文件 | 行段 / 符号 | 新模块 | 说明 |
| --- | --- | --- | --- |
| gui.py | 1-33 import 区 | 各 gui 子模块自行 import | 按需裁剪 |
| gui.py | 35-38 `APP_TITLE` / `CONFIG_DIR` / `CONFIG_FILE` / `LOG_DIR` | app/gui_config.py | 配置路径 |
| gui.py | 41-48 `resource_path` | app/gui_config.py | 源码/PyInstaller 双态资源定位 |
| gui.py | 51-58 `write_log` | app/gui_config.py | 按日日志 |
| gui.py | 60-62 `SOURCE_API` / `SOURCE_CLI` / `SOURCE_FILE` | app/gui_config.py | 数据源中文标签 |
| gui.py | 66-79 `DEFAULT_PROFILES` | app/gui_config.py | 预置区域（脱敏为「示例区域 1/2/3」） |
| gui.py | 82-134 `load_config` | app/gui_config.py | 合并 config.json + 预置去重 |
| gui.py | 137-142 `save_config` | app/gui_config.py | 落盘 |
| gui.py | 146-171 `App.__init__` | app/gui.py | 窗口初始化 + `after` 调度 |
| gui.py | 173-309 `App._build_ui` | app/gui.py | 视觉层级（状态栏/区域/工具栏/树/预览/操作区/日志） |
| gui.py | 311-352 `FILE_CHOICE` / `_init_table_ui` / `_on_pick_change` | app/gui_settings.py | 区域下拉与「本地文件」切换 |
| gui.py | 353-364 `_refresh_login_hint` | app/gui_login.py | 登录态提示（登录与设置两处都会调） |
| gui.py | 366-420 `_open_table_settings` | app/gui_settings.py | 表设置弹窗（保存 / 另存为新表） |
| gui.py | 422-424 `_profiles` | app/gui_settings.py | 区域列表访问器 |
| gui.py | 426-433 `on_pick_file` | app/gui_settings.py | 选择本地表格 |
| gui.py | 435-446 `_save_cfg` | app/gui_settings.py | 写回 config.json |
| gui.py | 448-464 `_make_source` | app/gui_settings.py | 数据源工厂（api / cli / file） |
| gui.py | 467-481 `run_bg` | app/gui_worker.py | 后台线程 + 事件队列 |
| gui.py | 483-503 `_pump_events` | app/gui_worker.py | 120ms 泵，UI 线程安全 |
| gui.py | 505-509 `_set_buttons` | app/gui_worker.py | 忙闲态按钮 |
| gui.py | 512-525 `_preflight` | app/gui_worker.py | 启动自检提示 |
| gui.py | 527-548 `on_login` | app/gui_login.py | 扫码登录入口 |
| gui.py | 550-552 `_notify` | app/gui_login.py | 后台线程写日志 |
| gui.py | 554-567 `_login_probe` | app/gui_login.py | 判断 ok / config / login 三阶段 |
| gui.py | 569-580 `_handle_login_state` | app/gui_login.py | 阶段分发 |
| gui.py | 582-637 `_show_config_dialog` | app/gui_login.py | 首次使用：应用初始化 |
| gui.py | 639-711 `_show_login_dialog` | app/gui_login.py | 设备码登录二维码弹窗 |
| gui.py | 713-739 `_auto_load` | app/gui_login.py | 启动自动探测 |
| gui.py | 741-752 `_after_auto_probe` | app/gui_login.py | 探测结果提示 |
| gui.py | 754-762 `on_test` | app/gui_login.py | 连接测试 |
| gui.py | 764-791 `on_load` | app/gui_worker.py | 拉任务 → 填树 → 选中首行 |
| gui.py | 793-810 `refresh_tree` | app/gui_table.py | 搜索 / 采集点 / 只看缺码 过滤 |
| gui.py | 812-814 `_row_key` | app/gui_table.py | iid 生成 |
| gui.py | 816-819 `_on_only_missing` | app/gui_table.py | 「只看缺二维码」持久化 |
| gui.py | 821-827 `_update_sel_label` | app/gui_table.py | 选中计数 + 状态栏统计 |
| gui.py | 829-835 `select_all` | app/gui_table.py | 全选 / 全不选 |
| gui.py | 837-850 `_on_tree_click` | app/gui_table.py | 勾选列点击 |
| gui.py | 852-861 `_on_space` | app/gui_table.py | 空格勾选 |
| gui.py | 863-875 `update_preview` | app/gui_table.py | 右侧版式预览（缩略 296×430） |
| gui.py | 877-878 `selected_tasks` | app/gui_table.py | 勾选结果 |
| gui.py | 880-896 `_on_tree_double_click` | app/gui_table.py | 双击出大图并调系统看图 |
| gui.py | 898-904 `_current_profile` | app/gui_settings.py | 当前区域配置 |
| gui.py | 906-911 `on_stop_sync` | app/gui_worker.py | 请求停止 |
| gui.py | 913-918 `on_sync_current` | app/gui_worker.py | 只补当前区域 |
| gui.py | 920-925 `on_sync_all` | app/gui_worker.py | 一键补齐全部区域 |
| gui.py | 927-992 `_start_sync` | app/gui_worker.py | 确认 → 后台跑 → 汇总弹窗 |
| gui.py | 994-997 `open_out_dir` | app/gui_worker.py | 打开输出目录 |
| gui.py | 1000-1005 `log_line` | app/gui_worker.py | 日志区追加 + 落盘 |
| gui.py | 1008-1015 `main` | app/gui.py | DPI 感知 + 进主循环 |

## 三、为什么这样切（依据）

- **core.py**：文件里天然有 4 条 `# ----` 分节（默认配置 / 数据模型 / 飞书 API / lark-cli / 本地文件 / 批量流程），
  加上散落在中间的一组环境辅助函数。按「网络层 / 进程调用层 / 文件层 / 路径与环境层 / 编排层」切开后，
  每个模块都能单独 import 和单测，`core_sync` 成为唯一的跨层编排点。
- **gui.py**：单文件里混了 41 个方法与 8 块 `# ----` 注释（构建 UI / 表格选择 / 表格配置 / 数据源 / 后台任务 /
  动作 / 同步 / 日志）。tkinter 的窗口类不适合拆成独立组件（父容器创建顺序会影响 pack 布局），
  因此按**行为域**拆成 4 个 mixin：设置、登录、表格与预览、后台与同步；`App` 只保留窗口装配与视觉层级。
  这样既满足「独立职责块抽成 gui_*.py」，又不动任何 pack/grid 调用顺序 —— 风险最低。
- **没有把 `App` 拆成 `PreviewWidget` 之类独立控件类**：那需要改 `_build_ui` 里的创建与挂载代码（属于改写实现），
  一旦 pack 顺序或父容器变化，1250 行界面布局就有回归风险。mixin 方案零布局改动。

## 四、保真度验证（本地实测）

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 符号完整性 | AST 对比 `legacy/core.py` 顶层符号 vs `core_*.py` 并集 | 32 → 32，缺失 0，新增 0 |
| GUI 方法完整性 | AST 对比 `legacy/gui.py::App` 方法与 mixin+`App` 并集 | 41 → 41（+`FILE_CHOICE` 类属性单独统计），缺失 0 |
| GUI 顶层符号 | AST 对比 `legacy/gui.py` 顶层名 vs `gui*.py` 并集 | 14 → 14，缺失 0 |
| self 属性连通性 | 静态扫描 mixin 里 `self.<attr>` 的读写集合 | 37 个赋值属性全覆盖，仅 `FILE_CHOICE` 为类属性 |
| 真实建窗 | `App()` 实例化 + `withdraw()` + `destroy()` | 通过，树列/下拉/状态栏均正常 |
| 渲染保真 | 同一 `TaskLabel` 分别用原 `qr-label/app` 与本仓库渲染 | PNG 67187 B，`sha256[:16]=4b47122699f4884b`，**逐字节相同** |
| 端到端 | `python main.py --cli --source file --file assets/模板-任务清单.csv --out ... --pdf` | 3 PNG + 1 PDF，退出码 0 |

## 五、对原文件的唯一改动（除脱敏外）

1. `app/label.py::_font_dirs()` 增加一个候选目录 `assets/fonts/`（仓库把字体统一放 assets/，
   排序在原 `app/fonts` 之后、`<repo>/fonts` 之前），不改任何排版常量；未改动前后渲染逐字节一致（见上表）。
2. `app/core_config.py` 三个默认表标识改为 `os.environ.get(..., "<FILL_ME_*>")`，`app/gui_config.py`
   预置区域改为「示例区域 1/2/3」+ 占位符；`legacy/core.py`、`legacy/gui.py` 同步替换字符串（其余字节一致，见 `legacy/NOTE.md`）。
3. `packaging/*.spec` 的 `datas` 源路径由 `app/fonts/...` 改为 `assets/fonts/...`（打包目标目录不变），
   `packaging/build.py` 增加 `LARK_CLI_EXE` 环境变量与仓库根自动判定。

## 六、已知缺陷（保持原样，未修）

- `legacy/gui.py`（原 `App._start_sync.done`）调用 `write_sync_report(results, out_dir)`，
  但文件顶部 import 未包含该符号 → 同步完成后生成 CSV 报表的那一步实际抛 `NameError`，
  被外层 `except Exception: pass` 吞掉（表现为「不生成同步结果 CSV」，不影响补码本身）。
  拆分时**按原样保留**（`gui_worker.py` 同样不 import 该符号），以遵守「不改业务逻辑」；
  如需修复：在 `app/gui_worker.py` 的 `from .core import (...)` 里补 `write_sync_report` 即可（一行）。
