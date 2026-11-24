"""命令行模式：批量生成 / 回传，可挂到 Windows 计划任务实现全自动。

示例：
  # 用本机 lark-cli 全量生成 PNG + PDF
  ScenarioQRCode.exe --cli --source cli --out "D:\\labels" --pdf

  # 只生成某个采集点的任务，并回传飞书
  ScenarioQRCode.exe --cli --source cli --site 大利家生活超市 --upload

  # 飞书开放平台（App ID / Secret）
  ScenarioQRCode.exe --cli --source api --app-id cli_xxx --app-secret xxx --upload
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # 直接以脚本方式运行（含 PyInstaller 打包）
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import (  # noqa: E402
    DEFAULT_BASE_TOKEN,
    DEFAULT_SITE_TABLE,
    DEFAULT_TASK_TABLE,
    FeishuAPI,
    FileSource,
    LarkCLISource,
    Task,
    generate_files,
    stage_upload_file,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ScenarioQRCode", description="场景任务码批量生成")
    p.add_argument("--cli", action="store_true", help="命令行模式（默认启动图形界面）")
    p.add_argument("--source", choices=["cli", "api", "file"], default="cli",
                   help="数据源：cli=本机 lark-cli，api=飞书开放平台，file=本地表格")
    p.add_argument("--file", default="", help="本地表格路径（--source file 时使用）")
    p.add_argument("--app-id", default="", help="飞书应用 App ID")
    p.add_argument("--app-secret", default="", help="飞书应用 App Secret")
    p.add_argument("--user-token", default="", help="可选的 user_access_token")
    p.add_argument("--base-token", default=DEFAULT_BASE_TOKEN)
    p.add_argument("--table-id", default=DEFAULT_TASK_TABLE)
    p.add_argument("--site-table", default=DEFAULT_SITE_TABLE)
    p.add_argument("--out", default=str(Path.home() / "Desktop" / "场景任务码"))
    p.add_argument("--site", default="", help="只处理指定采集点")
    p.add_argument("--task-id", action="append", default=[], help="只处理指定任务ID，可重复")
    p.add_argument("--limit", type=int, default=0, help="最多处理多少条")
    p.add_argument("--upload", action="store_true", help="生成后上传并覆盖「场景任务码」")
    p.add_argument("--pdf", action="store_true", help="额外导出 A4 打印版 PDF")
    p.add_argument("--exclude-done", action="store_true", help="跳过已经有二维码的任务")
    p.add_argument("--list", action="store_true", help="只列出符合条件的任务，不生成图片")
    return p


def make_source(args):
    if args.source == "file":
        if not args.file:
            raise SystemExit("--source file 需要同时指定 --file")
        return FileSource(args.file)
    if args.source == "api":
        return FeishuAPI(args.app_id, args.app_secret, base_token=args.base_token,
                         task_table=args.table_id, site_table=args.site_table,
                         user_token=args.user_token)
    return LarkCLISource(base_token=args.base_token, task_table=args.table_id,
                         site_table=args.site_table)


def filter_tasks(tasks: list[Task], args) -> list[Task]:
    out = tasks
    if args.site:
        out = [t for t in out if t.site_name == args.site]
    if args.task_id:
        wanted = set(args.task_id)
        out = [t for t in out if t.task_id in wanted]
    if args.exclude_done:
        out = [t for t in out if not t.has_code]
    if args.limit > 0:
        out = out[: args.limit]
    return out


def _dump_debug() -> None:
    """临时诊断：把环境变量与 lark-cli 探测结果写到临时目录。"""
    import os
    import subprocess
    import tempfile

    lines = [f"frozen={getattr(sys, 'frozen', False)}", f"exe={sys.executable}"]
    for key in sorted(os.environ):
        lines.append(f"ENV {key}={os.environ[key][:300]}")
    cli = LarkCLISource.find_cli()
    lines.append(f"cli_path={cli}")
    if cli:
        for probe in (["auth", "status"], ["base", "+table-list",
                                           "--base-token", DEFAULT_BASE_TOKEN, "--as", "user"]):
            proc = subprocess.run(["cmd.exe", "/c", cli, *probe], capture_output=True)
            lines.append(f"$ {' '.join(probe)} -> rc={proc.returncode}")
            lines.append((proc.stdout or b"").decode("utf-8", "ignore")[:800])
            lines.append((proc.stderr or b"").decode("utf-8", "ignore")[:800])
    path = Path(tempfile.gettempdir()) / "qrlabel-debug.txt"
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if os.environ.get("QR_LABEL_DEBUG"):
        _dump_debug()
    source = make_source(args)
    print(f"[1/3] 读取任务（数据源：{args.source}）…", flush=True)
    try:
        tasks = filter_tasks(source.list_tasks(), args)
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "not_configured" in text or "not configured" in text:
            print("这台电脑还没初始化飞书 CLI。\n"
                  "请先双击打开图形界面，点【飞书登录】按提示完成初始化与扫码；"
                  "或手动执行：lark-cli config init --new")
        elif "key storage lock" in text:
            print("读不到飞书登录凭据。请确认把程序放在桌面/D 盘，并以当前登录的 Windows 用户运行；"
                  "或在图形界面重新点【飞书登录】。")
        else:
            print(f"读取任务失败：{text[:500]}")
        return 3
    if not tasks:
        print("没有符合条件的任务。")
        return 1
    if args.list:
        print(f"{'任务ID':<12}{'采集点':<24}{'已有码':<6}任务名称")
        for t in tasks:
            print(f"{t.task_id:<12}{(t.site_name or '-'):<24}{'有' if t.has_code else '无':<6}{t.task_name}")
        print(f"共 {len(tasks)} 条")
        return 0
    out_dir = Path(args.out)
    print(f"[2/3] 生成 {len(tasks)} 张标签 → {out_dir}", flush=True)
    result = generate_files(tasks, out_dir, make_pdf=args.pdf)
    print(f"      PNG {len(result['png'])} 个" + (f"，PDF {result['pdf'].name}" if result["pdf"] else ""))

    if args.upload:
        if args.source == "file":
            print("离线数据源不支持回传，已跳过上传。")
            return 0
        print(f"[3/3] 回传 {len(tasks)} 张到飞书…", flush=True)
        ok, failed = 0, []
        for i, task in enumerate(tasks, 1):
            try:
                path = out_dir / f"{task.task_id}.png"
                data = path.read_bytes()
                if isinstance(source, LarkCLISource):
                    staged = stage_upload_file(data, f"{task.task_id}.png")
                    token = source.upload_png(str(staged), task.record_id)
                else:
                    token = source.upload_png(data, f"{task.task_id}.png")
                source.set_code(task.record_id, token)
                ok += 1
                print(f"  [{i}/{len(tasks)}] {task.task_id} 成功", flush=True)
            except Exception as exc:  # noqa: BLE001
                failed.append((task.task_id, str(exc)))
                print(f"  [{i}/{len(tasks)}] {task.task_id} 失败：{exc}", flush=True)
        print(f"完成：成功 {ok}，失败 {len(failed)}")
        return 0 if not failed else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
