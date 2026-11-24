"""可写目录、调试日志、lark-cli 锁清理与上传暂存（拆分自 core.py）"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _debug_log(text: str) -> None:
    """把 lark-cli 调用细节写到日志，便于排查环境问题。"""
    try:
        base = Path(os.environ.get("APPDATA", Path.home())) / "ScenarioQRCode" / "logs"
        base.mkdir(parents=True, exist_ok=True)
        with (base / "cli-debug.log").open("a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except Exception:  # noqa: BLE001
        pass


def _lock_state() -> str:
    locks = Path.home() / ".lark-cli" / "locks"
    if not locks.exists():
        return "locks-dir-missing"
    items = []
    for f in locks.glob("*"):
        try:
            items.append(f"{f.name}:{int(time.time() - f.stat().st_mtime)}s")
        except Exception:  # noqa: BLE001
            items.append(f.name)
    return ",".join(items) or "empty"


def _profile_mirror() -> Path | None:
    """把 ~/.lark-cli 镜像个可写副本，供低权限/沙箱进程使用。

    某些环境里交互式进程是低完整性令牌，写不进 ~/.lark-cli，lark-cli 会报
    「failed to acquire key storage lock」。指到一份可写的镜像即可正常工作。
    """
    src = Path.home() / ".lark-cli"
    if not src.exists():
        return None
    dst = _exe_dir() / ".lark-profile" / ".lark-cli"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return dst.parent
    except Exception as exc:  # noqa: BLE001
        _debug_log(f"profile mirror failed: {exc}")
        return None


def _clear_stale_locks(max_age: float = 0.0) -> None:
    """清理 lark-cli 遗留的锁文件。

    Windows 上「正在被进程持有」的文件删不掉，所以直接尝试删除是最可靠的存活检测：
    删成功的都是死锁，删不掉的自然保留。
    """
    locks = Path.home() / ".lark-cli" / "locks"
    if not locks.exists():
        return
    now = time.time()
    for item in locks.glob("*.lock"):
        try:
            if max_age > 0 and now - item.stat().st_mtime <= max_age:
                continue
            item.unlink()
        except Exception:  # noqa: BLE001
            continue


def work_dir(prefix: str = "qrlabel-") -> Path:
    """返回一个确实可写的临时目录。

    受限环境（企业策略、沙箱启动）里 %TEMP% 可能整个不可写，甚至 tempfile 直接报
    「No usable temporary directory」。这里逐个候选降级，最后兜底到 exe 所在目录。
    """
    candidates: list[Path] = []
    for getter in (
        lambda: Path(tempfile.gettempdir()),
        lambda: Path(os.environ.get("TEMP", "")),
        lambda: Path(os.environ.get("TMP", "")),
        lambda: Path.home() / "files",
        lambda: Path.cwd(),
        _exe_dir,
    ):
        try:
            path = getter()
        except Exception:  # noqa: BLE001
            continue
        if path and str(path) and path not in candidates:
            candidates.append(path)

    last_error: Exception | None = None
    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix=prefix, dir=base))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(
        "当前启动方式无法写入任何临时目录（找不到可写路径）。"
        "请把程序解压到本地磁盘，从资源管理器双击 exe 启动。"
        f"（底层错误：{last_error}）"
    )


def stage_upload_file(data: bytes, filename: str) -> Path:
    """把待上传的 PNG 落到 lark-cli 允许的目录。

    lark-cli 的 `--file` 只接受「当前工作目录 / 账号临时目录 / 家目录 files」下的路径，
    直接传桌面路径会被判定为 unsafe file path。
    """
    path = work_dir("qrlabel-upload-") / filename
    path.write_bytes(data)
    return path
