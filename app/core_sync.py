"""飞书回传同步与 CSV 报表（拆分自 core.py）"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .core_larkcli import LarkCLISource
from .core_paths import stage_upload_file
from .label import png_bytes, render_label

def _sync_one_table(
    profile: dict,
    out_dir: Path,
    only_missing: bool = True,
    limit: int | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict:
    """把一张表的二维码补齐：生成 → 上传 → 写回「场景任务码」→ 复核。"""
    source = LarkCLISource(
        base_token=profile.get("base_token", ""),
        task_table=profile.get("task_table", ""),
        site_table=profile.get("site_table", ""),
    )
    tasks = source.list_tasks()
    have = sum(1 for t in tasks if t.has_code)
    pending = [t for t in tasks if not t.has_code] if only_missing else list(tasks)
    if limit:
        pending = pending[:limit]
    out_dir.mkdir(parents=True, exist_ok=True)

    ok, failed, skipped = 0, [], False
    total = len(pending)
    for i, task in enumerate(pending, 1):
        if cancel and cancel():
            skipped = True
            break
        if progress:
            progress(i, total, f"{profile.get('name', '')}：第 {i}/{total} 张 · {task.task_id}")
        try:
            data = png_bytes(render_label(task.to_label()))
            (out_dir / f"{task.task_id}.png").write_bytes(data)
            staged = stage_upload_file(data, f"{task.task_id}.png")
            token = source.upload_png(str(staged), task.record_id)
            source.set_code(task.record_id, token)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            failed.append((task.task_id, str(exc)[:200]))

    verified = have + ok
    if pending and not skipped:
        try:
            verified = sum(1 for t in source.list_tasks() if t.has_code)
        except Exception:  # noqa: BLE001
            pass

    return {
        "name": profile.get("name", ""),
        "base_token": profile.get("base_token", ""),
        "total": len(tasks),
        "before": have,
        "pending": total,
        "ok": ok,
        "failed": failed,
        "skipped": skipped,
        "verified": verified,
        "out_dir": str(out_dir),
    }


def sync_all_tables(
    profiles: list[dict],
    out_dir: Path,
    only_missing: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> list[dict]:
    """一键同步：逐张表补齐缺失的二维码，支持中途停止。"""
    results: list[dict] = []
    for index, profile in enumerate(profiles, 1):
        if cancel and cancel():
            break
        name = profile.get("name", f"表格{index}")
        if progress:
            progress(0, 1, f"开始第 {index}/{len(profiles)} 张表：{name}")
        result = _sync_one_table(profile, out_dir, only_missing=only_missing,
                                 progress=progress, cancel=cancel)
        results.append(result)
        if progress:
            tail = "（已停止）" if result["skipped"] else ""
            progress(result["ok"], max(result["pending"], 1),
                     f"{name}：成功 {result['ok']}/{result['pending']}"
                     f"，该表现有二维码 {result['verified']}/{result['total']}{tail}")
        if result["skipped"]:
            break
    return results


def write_sync_report(results: list[dict], out_dir: Path) -> Path:
    """把同步结果写成 CSV。"""
    import csv as _csv

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"同步结果_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = _csv.writer(fh)
        writer.writerow(["区域", "任务总数", "同步前已有", "本次待补", "本次成功",
                         "本次失败", "同步后已有", "是否中断"])
        for r in results:
            writer.writerow([r["name"], r["total"], r["before"], r["pending"], r["ok"],
                             len(r["failed"]), r["verified"], "是" if r["skipped"] else "否"])
        failed_rows = [(r["name"], tid, err) for r in results for tid, err in r["failed"]]
        if failed_rows:
            writer.writerow([])
            writer.writerow(["区域", "任务ID", "失败原因"])
            writer.writerows(failed_rows)
    return path
