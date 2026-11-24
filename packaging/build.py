# 脱敏：本文件不含账号 / App Secret / user_token / 真实表 ID，
# 运行期凭据由 app/core_config.py 的 <FILL_ME_*> 占位符或环境变量提供。
# 仓库布局说明：字体在 assets/fonts/，打包目标仍是 app/fonts（与源码运行期的
# 字体搜索顺序一致，见 app/label.py:_font_dirs）。
"""一键打包：生成「独立版」——内置 lark-cli，目标机器无需安装任何依赖。

用法：python build.py [--clean]
产物：dist/场景任务码生成器-独立版/  （exe + _internal + bin/lark-cli.exe）
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not (ROOT / "app").exists() and (ROOT.parent / "app").exists():
    ROOT = ROOT.parent  # 本文件放在 packaging/ 下，构建根目录仍是仓库根
APP_NAME = "场景任务码生成器-独立版"
BUNDLED_CLI = Path(os.environ.get(
    "LARK_CLI_EXE",
    str(Path.home() / "AppData" / "Roaming" / "npm" / "node_modules"
        / "@larksuite" / "cli" / "bin" / "lark-cli.exe"),
))

COMMON = [
    "--noconfirm",
    "--onedir",
    "--windowed",
    "--uac-admin",
    "--add-data", "assets/fonts/NotoSansSC-VF.ttf;app/fonts",
    "--add-data", "assets/icon.ico;assets",
    "--hidden-import", "PIL._tkinter_finder",
    "--collect-submodules", "qrcode",
    "--exclude-module", "cv2",
    "--exclude-module", "numpy",
    "--exclude-module", "pandas",
    "--exclude-module", "matplotlib",
    "--exclude-module", "scipy",
    "--exclude-module", "docx",
    "--exclude-module", "pyzbar",
    "--exclude-module", "lxml",
    "--exclude-module", "PIL.AvifImagePlugin",
    "--icon", "assets/icon.ico",
    "--version-file", "version_info.txt",
    "--distpath", "dist",
    "--workpath", "build",
]


def build() -> int:
    if "--clean" in sys.argv:
        for path in ("build", "dist"):
            shutil.rmtree(ROOT / path, ignore_errors=True)

    print("===== 构建独立版 =====", flush=True)
    code = subprocess.call(
        [sys.executable, "-m", "PyInstaller", *COMMON, "--name", APP_NAME, "run.py"],
        cwd=ROOT,
    )
    if code != 0:
        return code

    target = ROOT / "dist" / APP_NAME
    # PyInstaller 会把 exe 名字设成 APP_NAME，改成更短的显示名
    built_exe = target / f"{APP_NAME}.exe"
    if built_exe.exists():
        built_exe.rename(target / "场景任务码生成器.exe")

    # 内置 lark-cli：目标机器无需安装 Node / lark-cli
    if BUNDLED_CLI.exists():
        bin_dir = target / "bin"
        bin_dir.mkdir(exist_ok=True)
        shutil.copy2(BUNDLED_CLI, bin_dir / "lark-cli.exe")
        print(f"已内置 lark-cli：{BUNDLED_CLI.stat().st_size / 1024 / 1024:.1f} MB")
    else:
        print("警告：未找到 lark-cli.exe，独立版将依赖目标机器已安装的 CLI")

    total = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"\n构建完成：{target}  共 {total / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
