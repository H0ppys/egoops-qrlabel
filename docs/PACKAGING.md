# 打包说明（PACKAGING）

对应源目录 `qr-label/` 根下的四份 PyInstaller 配置与 `build.py`，已脱敏后放入本仓库 `packaging/`。
**四份 spec 与 `build.py` 均不含账号、App Secret、user_token 或真实表 ID**；运行时表标识由
`app/core_config.py` 的 `<FILL_ME_*>` 占位符 / 环境变量提供。

## 一、四套产物对照

| spec | 入口 | 形态 | console | 产物 | 适用 |
| --- | --- | --- | --- | --- | --- |
| `场景任务码生成器.spec` | `run.py` | onefile | `False` | `场景任务码生成器.exe` | 单文件分发（解包到 `%TEMP%` 才能跑） |
| `场景任务码生成器-CLI.spec` | `run_cli.py` | onefile | `True` | `场景任务码生成器-CLI.exe` | 计划任务 / 服务器 |
| `场景任务码生成器-独立版.spec` | `run.py` | onedir（`COLLECT`） | `False` | `dist/场景任务码生成器-独立版/` | **主推**：onedir + 内置 `bin/lark-cli.exe` |
| `场景任务码生成器-免解压版.spec` | `run.py` | onedir（`COLLECT`） | `False` | `dist/场景任务码生成器-免解压版/` | 不允许写 `%TEMP%` 的环境 |

共同参数：

- `datas=[('assets/fonts/NotoSansSC-VF.ttf', 'app/fonts'), ('assets/icon.ico', 'assets')]`
  （仓库字体在 `assets/fonts/`，打包目标仍是 `app/fonts`，与 `app/label.py::_font_dirs` 的首选目录一致）
- `hiddenimports = ['PIL._tkinter_finder'] + collect_submodules('qrcode')`
- `excludes = ['cv2','numpy','pandas','matplotlib','scipy','docx','pyzbar']`
  （独立版另加 `lxml`、`PIL.AvifImagePlugin`，减小体积）
- `uac_admin=True`、`version='version_info.txt'`、`icon=['assets/icon.ico']`、`upx=True`

## 二、GUI spec 要点（脱敏后原文，`packaging/场景任务码生成器.spec`）

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['PIL._tkinter_finder']
hiddenimports += collect_submodules('qrcode')

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/fonts/NotoSansSC-VF.ttf', 'app/fonts'), ('assets/icon.ico', 'assets')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['cv2', 'numpy', 'pandas', 'matplotlib', 'scipy', 'docx', 'pyzbar'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='场景任务码生成器',
    debug=False, strip=False, upx=True, upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None,
    codesign_identity=None, entitlements_file=None,
    version='version_info.txt',
    uac_admin=True,
    icon=['assets/icon.ico'],
)
```

独立版 / 免解压版额外用 `exclude_binaries=True` + `COLLECT(...)` 生成目录形态（onedir），
`EXE` 里 `a.binaries, a.datas` 传空、交给 `COLLECT` 收集。

## 三、`version_info.txt`（Windows 文件属性，已脱敏）

```python
VSVersionInfo(
  ffi=FixedFileInfo(filevers=(1,1,0,0), prodvers=(1,1,0,0), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[
    StringFileInfo([StringTable('080404b0', [
        StringStruct('CompanyName', '<FILL_ME_COMPANY>'),
        StringStruct('FileDescription', '场景任务码批量生成工具'),
        StringStruct('FileVersion', '1.1.0.0'),
        StringStruct('InternalName', 'ScenarioQRCode'),
        StringStruct('OriginalFilename', '场景任务码生成器.exe'),
        StringStruct('ProductName', '场景任务码生成器'),
        StringStruct('ProductVersion', '1.1.0.0')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
```

> 仓库内该文件保留了原有字段值（无敏感信息），需要改公司名时改 `CompanyName`；语气语言代码 `080404b0` = 简体中文 / Unicode。

## 四、一键构建（`packaging/build.py`）

原 `build.py` 只做三件事：调 PyInstaller 出 onedir → 把 exe 改名为 `场景任务码生成器.exe` →
把本机 npm 全局安装的 `lark-cli.exe` 复制进 `bin/`，使目标机器无需 Node。

本仓库版本做了两处适配（其余逻辑未改）：

```python
ROOT = Path(__file__).resolve().parent
if not (ROOT / "app").exists() and (ROOT.parent / "app").exists():
    ROOT = ROOT.parent          # 文件在 packaging/ 下，构建根目录仍是仓库根

BUNDLED_CLI = Path(os.environ.get(
    "LARK_CLI_EXE",
    str(Path.home() / "AppData" / "Roaming" / "npm" / "node_modules"
        / "@larksuite" / "cli" / "bin" / "lark-cli.exe"),
))
```

用法（**必须在仓库根执行**，spec 内相对路径以 cwd 为准）：

```bash
python -m pip install -r requirements.txt pyinstaller

# 方式 A：一键脚本
python packaging/build.py --clean

# 方式 B：直接指定 spec
python -m PyInstaller packaging/场景任务码生成器-独立版.spec --noconfirm
python -m PyInstaller packaging/场景任务码生成器-CLI.spec --noconfirm

# 指定内置 lark-cli 路径
set LARK_CLI_EXE=D:\tools\lark-cli.exe   && python packaging/build.py --clean
```

产物：`dist/场景任务码生成器-独立版/{场景任务码生成器.exe, _internal/, bin/lark-cli.exe}`。

## 五、运行时目录约定

| 路径 | 内容 |
| --- | --- |
| `%APPDATA%\ScenarioQRCode\config.json` | 界面配置（数据源、表标识、输出目录、区域列表） |
| `%APPDATA%\ScenarioQRCode\logs\run-YYYYMMDD.log` | GUI 行为日志 |
| `%APPDATA%\ScenarioQRCode\logs\cli-debug.log` | lark-cli 调用细节（排查环境问题用） |
| `~/.lark-cli\` | lark-cli 自己的登录凭据（**不要拷进仓库、不要随 exe 分发**） |
| `工作目录/.lark-profile/` | 受限环境下的凭据镜像（`core_paths._profile_mirror` 生成，可删） |

## 六、解包与排错（拿到别人的 exe 时）

```bash
# onefile 解包（pyinstxtractor）
python pyinstxtractor-ng.py 场景任务码生成器.exe
# 目录版直接就是 pyc/资源树，decompyle3 / uncompyle6 或 pycdc 还原
```

常见问题：

- **`Could not create temporary directory!`**：onefile 版需要 `%TEMP%`；改用 onedir（独立版/免解压版）。
- **`failed to acquire key storage lock`**：进程被降权（从聊天窗口/预览器直接点开、或放在同步盘），
  把目录挪到本地磁盘后从资源管理器双击；`core_env.friendly_error` 已把该错误翻成人话提示。
- **字体不一致**：确认 `_internal/app/fonts/NotoSansSC-VF.ttf` 存在；缺失时回退到 `C:\Windows\Fonts` 的微软雅黑，版式会有差异。
- **杀软误报**：`--uac-admin` + UPX 压缩容易触发启发式，可 `upx=False` 重新打包。
