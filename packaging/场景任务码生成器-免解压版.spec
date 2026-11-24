# 脱敏：本文件不含账号 / App Secret / user_token / 真实表 ID，
# 运行期凭据由 app/core_config.py 的 <FILL_ME_*> 占位符或环境变量提供。
# 仓库布局说明：字体在 assets/fonts/，打包目标仍是 app/fonts（与源码运行期的
# 字体搜索顺序一致，见 app/label.py:_font_dirs）。
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
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='场景任务码生成器-免解压版',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    uac_admin=True,
    icon=['assets/icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='场景任务码生成器-免解压版',
)
