"""环境自检与错误人话化（拆分自 core.py）"""

from __future__ import annotations

import os
import shutil
import subprocess

from .core_paths import _debug_log, work_dir

def preflight() -> list[str]:
    """启动自检：返回当前环境导致功能受限的问题列表（空列表=正常）。"""
    problems: list[str] = []
    try:
        probe = work_dir("qrlabel-check-")
        shutil.rmtree(probe, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"无法写入任何临时目录（{exc}）")

    try:
        proc = subprocess.run(["whoami", "/groups"], capture_output=True, timeout=10,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = (proc.stdout or b"").decode("mbcs", "ignore")
        level = [line.strip() for line in text.splitlines() if "Mandatory" in line]
        me = subprocess.run(["whoami"], capture_output=True, timeout=10,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        user = (me.stdout or b"").decode("mbcs", "ignore").strip()
        _debug_log(f"PREFLIGHT user={user} level={level[:1]} pid={os.getpid()}")
        keys = ("TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE",
                "HOMEPATH", "SystemRoot", "COMSPEC", "SESSIONNAME", "USERNAME")
        snapshot = {k: os.environ.get(k, "") for k in keys}
        extra = sorted(k for k in os.environ if k.startswith(("DSH", "SANDBOX", "_PYI")))
        _debug_log(f"ENV {snapshot} extra={extra}")
    except Exception:  # noqa: BLE001
        pass
    return problems


def friendly_error(exc: Exception) -> str:
    """把底层报错翻译成同事能看懂的话。"""
    text = str(exc)
    low = text.lower()
    if "key storage lock" in low or "token storage lock" in low:
        return (
            "无法访问本机 lark-cli 的登录凭据（key storage lock）。\n\n"
            "这种情况几乎都是「启动方式受限」导致的：程序是从聊天窗口、文件预览器或"
            "受管控的宿主里打开的，进程被限制了文件访问。\n\n"
            "解决办法：\n"
            "1) 把整个文件夹解压到本地磁盘（如 D:\\工具\\场景任务码生成器）；\n"
            "2) 从「资源管理器」双击 场景任务码生成器.exe（不是从聊天窗口点开）；\n"
            "3) 若仍失败，打开命令行执行 lark-cli auth login 重新登录后再试。"
        )
    if "no usable temporary directory" in low or "无法写入任何临时目录" in text:
        return (
            "找不到任何可写的临时目录，程序无法准备运行环境。\n\n"
            "请把程序解压到本地磁盘（不要放在只读目录、网络盘或压缩包内直接运行），"
            "再从资源管理器双击 exe。也可以改用「免解压版」文件夹里的 exe。"
        )
    if "unsafe file path" in low:
        return (
            "lark-cli 拒绝读取该路径下的文件（不在它的允许目录内）。\n\n"
            "请把程序放在本地磁盘的用户目录下运行，或把输出目录改到用户目录里再重试。"
        )
    if "access denied" in low or "permission" in low or "权限" in text:
        return f"权限不足，无法完成操作。\n\n原始信息：{text[:500]}"
    return text
