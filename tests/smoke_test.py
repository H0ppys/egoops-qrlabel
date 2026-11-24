"""冒烟测试：全部模块可 import + CLI --help + 端到端出图（拆分自 qr-label/app）。

运行（仓库根目录）：
    python -X utf8 tests/smoke_test.py

不依赖网络与飞书环境：只用 --source file 走离线数据源。
"""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

failures: list[str] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{name}: {type(exc).__name__}: {exc}")
        print(f"[FAIL] {name} -> {type(exc).__name__}: {exc}")
        return
    print(f"[ OK ] {name}" + (f" -> {detail}" if detail else ""))


# ------------------------------------------------------------------ 1) can-import
CORE_MODULES = [
    "app", "app.core", "app.core_config", "app.core_models", "app.core_paths",
    "app.core_api", "app.core_larkcli", "app.core_files", "app.core_env",
    "app.core_batch", "app.core_sync", "app.label", "app.cli",
]
GUI_MODULES = [
    "app.gui", "app.gui_config", "app.gui_settings", "app.gui_login",
    "app.gui_table", "app.gui_worker",
]


def import_all() -> str:
    import importlib

    for name in CORE_MODULES + GUI_MODULES:
        importlib.import_module(name)
    return f"{len(CORE_MODULES + GUI_MODULES)} 个模块"


check("import 全部模块", import_all)


# ------------------------------------------------------------------ 2) 兼容层符号
def core_symbols() -> str:
    import app
    import app.core as core

    assert len(core.__all__) == 32, f"core.__all__ 应为 32 个，实际 {len(core.__all__)}"
    for name in core.__all__:
        assert hasattr(core, name), f"app.core 缺少符号 {name}"
        assert hasattr(app, name) or name.startswith("_"), f"app 未重导出 {name}"
    assert app.core.Task is app.Task, "app.Task 应指向 app.core 的 Task"
    return f"core.__all__={len(core.__all__)}，app 重导出可用"


check("app.core / app 符号重导出", core_symbols)


# ------------------------------------------------------------------ 3) 渲染
def render_ok() -> str:
    from app.label import TaskLabel, png_bytes, render_label, render_pdf

    label = TaskLabel("1043099046", "二楼茶室储物整理与茶桌清洁", "君馨阁一楼")
    img = render_label(label)
    assert img.size == (1190, 1684), f"画布尺寸异常：{img.size}"
    data = png_bytes(img)
    pdf = render_pdf([label])
    assert pdf.startswith(b"%PDF"), "PDF 头异常"
    return f"PNG {len(data)} B sha256[:8]={hashlib.sha256(data).hexdigest()[:8]}，PDF {len(pdf)} B"


check("A4 标签渲染（PNG + PDF）", render_ok)


# ------------------------------------------------------------------ 4) CLI --help
def cli_help() -> str:
    from app.cli import build_parser

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            build_parser().parse_args(["--help"])
    except SystemExit as exc:
        assert exc.code == 0, f"--help 退出码 {exc.code}"
    text = buf.getvalue()
    assert "场景任务码批量生成" in text, "--help 没有输出描述"
    assert "--source" in text and "--upload" in text
    return f"--help {len(text.splitlines())} 行，退出码 0"


check("CLI 入口 --help", cli_help)


# ------------------------------------------------------------------ 5) 子进程入口
def main_py_help() -> str:
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "main.py"), "--cli", "--help"],
        capture_output=True, cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"rc={proc.returncode} err={proc.stderr.decode('utf-8', 'ignore')[:300]}"
    out = proc.stdout.decode("utf-8", "ignore")
    assert "usage: ScenarioQRCode" in out
    return "python main.py --cli --help rc=0"


check("main.py --cli --help（子进程）", main_py_help)


# ------------------------------------------------------------------ 6) 端到端出图
def end_to_end() -> str:
    import shutil

    from app.cli import main as cli_main

    sample = ROOT / "assets" / "模板-任务清单.csv"
    assert sample.exists(), f"缺示例表格 {sample}"
    # 故意不预先建目录：由 CLI 自己 mkdir（某些受限环境下 mkdtemp 的 0700 ACL 反而不可写）
    tmp = Path(tempfile.gettempdir()) / f"qrlabel-smoke-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        rc = cli_main(["--source", "file", "--file", str(sample), "--out", str(tmp), "--pdf"])
        assert rc == 0, f"CLI 退出码 {rc}"
        pngs = sorted(tmp.glob("*.png"))
        pdfs = sorted(tmp.glob("*.pdf"))
        assert len(pngs) == 3, f"PNG 数量 {len(pngs)} != 3"
        assert len(pdfs) == 1, f"PDF 数量 {len(pdfs)} != 1"
        return f"{[p.name for p in pngs]} + {pdfs[0].name}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # Windows 上偶发句柄未释放，忽略清理失败


check("离线端到端：CSV → 3 PNG + 1 PDF", end_to_end)


# ------------------------------------------------------------------ 7) GUI 装配（不建窗）
def gui_wiring() -> str:
    from app.gui import App
    from app.gui_login import LoginMixin
    from app.gui_settings import TableSettingsMixin
    from app.gui_table import TablePreviewMixin
    from app.gui_worker import WorkerMixin

    for mixin in (LoginMixin, TableSettingsMixin, TablePreviewMixin, WorkerMixin):
        assert mixin in App.__mro__, f"App 未继承 {mixin.__name__}"
    names = {n for n in dir(App) if not n.startswith("__")}
    for required in ("on_login", "on_load", "on_sync_all", "refresh_tree",
                     "update_preview", "_build_ui", "log_line", "_make_source"):
        assert required in names, f"App 缺少方法 {required}"
    return "4 个 mixin + 关键方法齐全"


check("GUI mixin 装配", gui_wiring)


# ------------------------------------------------------------------ 8) 源码树卫生
FORBIDDEN_SUFFIX = (".exe", ".apk", ".pyc", ".spec.bak")
FORBIDDEN_NAME = ("token_cache.json", "config.ini", ".env")


def tree_hygiene() -> str:
    bad = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts:
            continue  # __pycache__ 由 .gitignore 忽略，不算仓库内容
        rel = str(p.relative_to(ROOT))
        if p.suffix in FORBIDDEN_SUFFIX:
            bad.append(rel)  # __pycache__/*.pyc 也计入：.gitignore 已忽略，此处仅提示
        if p.name in FORBIDDEN_NAME:
            bad.append(rel)
    assert not bad, f"仓库含构建产物/凭据/缓存：{bad[:5]}"
    for need in ("README.md", "LICENSE", "requirements.txt", "docs/ARCHITECTURE.md",
                 "docs/SPLIT.md", "docs/PACKAGING.md", "legacy/core.py",
                 "packaging/场景任务码生成器.spec", "assets/icon.ico",
                 "assets/fonts/NotoSansSC-VF.ttf"):
        assert (ROOT / need).exists(), f"缺少 {need}"
    return "无 exe/apk/凭据文件，必备文件齐全"


check("源码树卫生", tree_hygiene)


# ------------------------------------------------------------------ 汇总
print()
if failures:
    print(f"FAILED {len(failures)} 项：")
    for item in failures:
        print(" -", item)
    raise SystemExit(1)
print("全部冒烟通过 ✅")
raise SystemExit(0)
