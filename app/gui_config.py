"""界面常量、配置文件读写与日志（拆分自 gui.py）"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .core import DEFAULT_BASE_TOKEN, DEFAULT_SITE_TABLE, DEFAULT_TASK_TABLE

APP_TITLE = "场景任务码生成器"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ScenarioQRCode"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"


def resource_path(relative: str) -> Path:
    """兼容源码运行与 PyInstaller 打包后的资源定位。"""
    import sys

    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parent.parent / relative


def write_log(text: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = __import__("datetime").datetime.now().strftime("%Y%m%d")
        with (LOG_DIR / f"run-{stamp}.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
    except Exception:
        pass

SOURCE_API = "飞书开放平台（App ID / Secret）"
SOURCE_CLI = "本机 lark-cli（已登录）"
SOURCE_FILE = "本地文件（Excel / CSV / JSON）"


# ---------------------------------------------------------------- 配置
DEFAULT_PROFILES = [
    {"name": "示例区域 1",
     "base_token": "<FILL_ME_BASE_TOKEN>",
     "task_table": "<FILL_ME_TASK_TABLE>",
     "site_table": "<FILL_ME_SITE_TABLE>"},
    {"name": "示例区域 2",
     "base_token": "<FILL_ME_BASE_TOKEN_2>",
     "task_table": "<FILL_ME_TASK_TABLE_2>",
     "site_table": "<FILL_ME_SITE_TABLE_2>"},
    {"name": "示例区域 3",
     "base_token": "<FILL_ME_BASE_TOKEN_3>",
     "task_table": "<FILL_ME_TASK_TABLE_3>",
     "site_table": "<FILL_ME_SITE_TABLE_3>"},
]


def load_config() -> dict:
    defaults = {
        "source": SOURCE_CLI,
        "app_id": "",
        "app_secret": "",
        "user_token": "",
        "base_token": DEFAULT_BASE_TOKEN,
        "task_table": DEFAULT_TASK_TABLE,
        "site_table": DEFAULT_SITE_TABLE,
        "out_dir": str(Path.home() / "Desktop" / "场景任务码"),
        "last_file": "",
        "auto_load": True,
        "profiles": [
            {"name": "示例区域 1",
             "base_token": "<FILL_ME_BASE_TOKEN>",
             "task_table": "<FILL_ME_TASK_TABLE>",
             "site_table": "<FILL_ME_SITE_TABLE>"},
            {"name": "示例区域 2",
             "base_token": "<FILL_ME_BASE_TOKEN_2>",
             "task_table": "<FILL_ME_TASK_TABLE_2>",
             "site_table": "<FILL_ME_SITE_TABLE_2>"},
            {"name": "示例区域 3",
             "base_token": "<FILL_ME_BASE_TOKEN_3>",
             "task_table": "<FILL_ME_TASK_TABLE_3>",
             "site_table": "<FILL_ME_SITE_TABLE_3>"},
        ],
        "active_profile": "示例区域 1",
        "only_missing": False,
    }
    try:
        if CONFIG_FILE.exists():
            defaults.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    # 以预置表格为准去重合并（升级后旧配置里的重复项会被自动清理）
    def _key(p: dict) -> tuple[str, str]:
        return (p.get("base_token", ""), p.get("task_table", ""))

    merged: list[dict] = []
    known: set[tuple[str, str]] = set()
    for preset in DEFAULT_PROFILES:
        if _key(preset) not in known:
            merged.append(dict(preset))
            known.add(_key(preset))
    for prof in defaults.get("profiles") or []:
        if not prof.get("base_token") or not prof.get("task_table"):
            continue
        if _key(prof) in known:
            continue
        merged.append(dict(prof))
        known.add(_key(prof))
    defaults["profiles"] = merged
    return defaults


def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
