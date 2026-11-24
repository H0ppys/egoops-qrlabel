"""本机 lark-cli 数据源（拆分自 core.py）"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

from .core_config import (
    DEFAULT_BASE_TOKEN,
    DEFAULT_SITE_TABLE,
    DEFAULT_TASK_TABLE,
    F_CODE,
    F_ID,
    F_NAME,
    F_SITE,
    F_STATUS,
    FeishuError,
)
from .core_models import (
    Task,
    _attachment_tokens,
    _find_tokens,
    _link_record_ids,
    _text_of,
)
from .core_paths import (
    _clear_stale_locks,
    _debug_log,
    _exe_dir,
    _lock_state,
    _profile_mirror,
    work_dir,
)

# ---------------------------------------------------------------- lark-cli
class LarkCLISource:
    """调用本机已登录的 lark-cli（用户身份，无需配置应用）。"""

    def __init__(
        self,
        base_token: str = DEFAULT_BASE_TOKEN,
        task_table: str = DEFAULT_TASK_TABLE,
        site_table: str = DEFAULT_SITE_TABLE,
        cli_path: str = "",
    ) -> None:
        self.base_token = base_token
        self.task_table = task_table
        self.site_table = site_table
        self.cli_path = cli_path or self.find_cli()

    @staticmethod
    def find_cli() -> str:
        # 1) 随程序打包的 lark-cli（独立版，目标机器无需安装任何东西）
        for base in (Path(_exe_dir()), Path(getattr(sys, "_MEIPASS", _exe_dir()))):
            for rel in ("bin/lark-cli.exe", "lark-cli.exe"):
                candidate = base / rel
                if candidate.exists():
                    return str(candidate)
        # 2) 系统 PATH（npm 全局安装）
        for name in ("lark-cli.cmd", "lark-cli.exe", "lark-cli"):
            path = shutil.which(name)
            if path:
                return path
        # 3) npm 默认目录
        candidate = Path(os.environ.get("APPDATA", "")) / "npm" / "lark-cli.cmd"
        return str(candidate) if candidate.exists() else ""

    @property
    def available(self) -> bool:
        return bool(self.cli_path) and Path(self.cli_path).exists()

    def _native_exe(self) -> str:
        """优先直接调用 lark-cli.exe，避免 cmd.exe 包装带来的编码/环境差异。"""
        if self.cli_path.lower().endswith(".exe"):
            return self.cli_path
        candidate = Path(self.cli_path).with_name("lark-cli.exe")
        if candidate.exists():
            return str(candidate)
        npm_bin = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli.exe"
        return str(npm_bin) if npm_bin.exists() else ""

    def _run(self, args: list[str], timeout: int = 180, retries: int = 3,
             cwd: str | None = None) -> str:
        if not self.available:
            raise FeishuError("没有找到 lark-cli，请先安装并登录（npm i -g @larksuite/cli）")
        direct = self._native_exe()
        _clear_stale_locks()  # 先清掉被强杀进程留下的死锁，活锁删不掉、不会被误伤

        # 不同启动上下文（桌面双击 / 服务 / 沙箱）对 lark-cli 的凭据访问表现不同，
        # 这里把「调用方式 × 工作目录」组合起来逐个尝试，任一成功即可。
        variants: list[tuple[str, list[str], str | None]] = []
        if direct:
            variants.append(("native", [direct, *args], cwd))
            variants.append(("native-home", [direct, *args], str(Path.home())))
        if self.cli_path:
            variants.append(("cmd", ["cmd.exe", "/c", self.cli_path, *args], cwd))
            variants.append(("cmd-home", ["cmd.exe", "/c", self.cli_path, *args], str(Path.home())))
        if direct:
            variants.append(("exe-home", [direct, *args], str(Path.home())))

        last = ""
        used_mirror = False
        for label, cmd, workdir in variants:
            delay = 0.5
            env = None
            if used_mirror:
                mirror = _profile_mirror()
                if mirror:
                    env = {**os.environ, "USERPROFILE": str(mirror), "HOME": str(mirror)}
            for attempt in range(retries):
                proc = subprocess.run(
                    cmd, capture_output=True, timeout=timeout, cwd=workdir, env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                out = (proc.stdout or b"").decode("utf-8", "ignore")
                err = (proc.stderr or b"").decode("utf-8", "ignore")
                if proc.returncode == 0 or '"ok": true' in out:
                    if label != "native" or used_mirror:
                        _debug_log(f"OK variant={label} mirror={used_mirror} cwd={workdir}")
                    return out
                last = err or out
                text = last.lower()
                if "lock" in text:
                    _clear_stale_locks()
                if attempt < retries - 1 and ("lock" in text or "temporarily" in text):
                    time.sleep(delay)
                    delay = min(delay * 2, 3.0)
                    continue
                break
            _debug_log(
                f"FAIL[{label}] mirror={used_mirror} cwd={workdir} rc={proc.returncode} "
                f"locks=[{_lock_state()}] user={os.environ.get('USERPROFILE')} "
                f"err={err[:200]!r}"
            )
            used_mirror = True  # 后续变体改用可写镜像凭据目录
        raise FeishuError(f"lark-cli 执行失败：{last[:400]}")

    def _records(self, table_id: str, field_ids: Iterable[str]) -> list[dict]:
        # 注意：lark-cli 只允许把 --output 写到「当前工作目录 / 临时目录 / ~/files」，
        # 因此这里既把文件放进工作目录，也把子进程的 cwd 指到同一个目录。
        tmpdir = work_dir()
        out_file = tmpdir / "records.ndjson"
        args = [
            "base", "+record-list",
            "--base-token", self.base_token,
            "--table-id", table_id,
            "--limit", "2000",
            "--format", "ndjson",
            "--output", out_file.name,
            "--as", "user",
        ]
        for fid in field_ids:
            args += ["--field-id", fid]
        self._run(args, cwd=str(tmpdir))
        rows: list[dict] = []
        if out_file.exists():
            with out_file.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        shutil.rmtree(tmpdir, ignore_errors=True)
        return rows

    def list_sites(self) -> dict[str, str]:
        try:
            rows = self._records(self.site_table, ["采集点ID", "采集点名称"])
        except FeishuError:
            return {}
        return {
            str(r.get("record_id")): _text_of(r.get("采集点名称"))
            for r in rows if r.get("采集点名称")
        }

    def list_tasks(self) -> list[Task]:
        sites = self.list_sites()
        rows = self._records(
            self.task_table, [F_NAME, F_ID, F_SITE, F_STATUS, F_CODE]
        )
        tasks: list[Task] = []
        for r in rows:
            task_id = _text_of(r.get(F_ID)).strip()
            if not task_id:
                continue
            site = ""
            for rid in _link_record_ids(r.get(F_SITE)):
                if rid in sites:
                    site = sites[rid]
                    break
            if not site:
                site = _text_of(r.get(F_SITE))
            tasks.append(
                Task(
                    record_id=str(r.get("record_id")),
                    task_id=task_id,
                    task_name=_text_of(r.get(F_NAME)),
                    site_name=site,
                    status=_text_of(r.get(F_STATUS)),
                    code_tokens=_attachment_tokens(r.get(F_CODE)),
                )
            )
        tasks.sort(key=lambda t: (t.site_name, t.task_id))
        return tasks

    def upload_png(self, path: str, record_id: str) -> str:
        # --file 也必须在 lark-cli 允许的目录内：切到文件所在目录并用相对文件名
        p = Path(path)
        out = self._run([
            "base", "+record-upload-attachment",
            "--base-token", self.base_token,
            "--table-id", self.task_table,
            "--record-id", record_id,
            "--field-id", F_CODE,
            "--file", p.name,
            "--as", "user",
        ], cwd=str(p.parent))
        payload = json.loads(out)
        data = payload.get("data") or {}
        tokens: list[str] = []
        for key in ("uploaded", "attachments", "files", "items"):
            for item in data.get(key) or []:
                if isinstance(item, dict) and item.get("file_token"):
                    tokens.append(item["file_token"])
        if not tokens:
            tokens = _find_tokens(data)
        if not tokens:
            raise FeishuError(f"上传成功但未解析到 file_token：{out[:300]}")
        return tokens[-1]

    def set_code(self, record_id: str, file_token: str) -> None:
        body = {"update_records": {record_id: {F_CODE: [{"file_token": file_token}]}}}
        self._run([
            "base", "+record-batch-update",
            "--base-token", self.base_token,
            "--table-id", self.task_table,
            "--json", json.dumps(body, ensure_ascii=False),
            "--as", "user",
        ])

    def check(self) -> str:
        tasks = self.list_tasks()
        return f"lark-cli 连接成功，读取到 {len(tasks)} 条任务"

    # -- 登录状态与扫码登录 -----------------------------------------
    def _raw(self, args: list[str], timeout: int = 60) -> tuple[int, str, str]:
        """直接跑一次 lark-cli，返回 (退出码, stdout, stderr)。"""
        direct = self._native_exe()
        cmd = [direct, *args] if direct else ["cmd.exe", "/c", self.cli_path, *args]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        return (proc.returncode,
                (proc.stdout or b"").decode("utf-8", "ignore"),
                (proc.stderr or b"").decode("utf-8", "ignore"))

    def config_state(self) -> str:
        """'unconfigured' / 'ok' / 'unknown'。先看本地配置文件，避免每次启动都等 CLI。"""
        if not (Path.home() / ".lark-cli" / "config.json").exists():
            return "unconfigured"
        rc, out, err = self._raw(["auth", "status", "--json"], timeout=20)
        text = out + err
        if "not_configured" in text or "not configured" in text:
            return "unconfigured"
        if '"appId"' in out or '"ok": true' in out:
            return "ok"
        return "unknown"

    def config_init_start(self, deadline: float = 40.0) -> tuple[subprocess.Popen, str]:
        """启动 `config init --new` 并读出授权链接（进程会一直等待授权）。"""
        direct = self._native_exe()
        cmd = [direct, "config", "init", "--new"] if direct else \
            ["cmd.exe", "/c", self.cli_path, "config", "init", "--new"]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        url = ""
        end = time.time() + deadline
        pattern = re.compile(r"https://[^\s\"']+")
        while time.time() < end:
            line = proc.stdout.readline() if proc.stdout else b""
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
                continue
            text = line.decode("utf-8", "ignore")
            found = pattern.search(text)
            if found:
                url = found.group(0)
                break
        if not url:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            raise FeishuError("初始化应用失败：没有拿到授权链接，请检查网络后重试。")
        return proc, url

    def config_init_finish(self, proc: subprocess.Popen, timeout: float = 8.0) -> bool:
        """确认应用初始化是否完成；没完成就立刻返回，避免界面像卡死。"""
        cfg = Path.home() / ".lark-cli" / "config.json"
        if cfg.exists():
            return True
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return cfg.exists()

    def auth_status(self) -> tuple[bool, str]:
        """返回 (是否已登录, 说明)。只跑一次 CLI，避免多处重试导致界面像卡住。"""
        rc, out, err = self._raw(["auth", "status", "--json"], timeout=20)
        text = out or err
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            if "not_configured" in text or "not configured" in text:
                return False, "尚未初始化飞书 CLI"
            return False, f"读取登录状态失败：{text[:120]}"
        user = (data.get("identities") or {}).get("user") or {}
        if user.get("available"):
            return True, user.get("userName") or user.get("openId") or "已登录"
        return False, user.get("message") or "未登录"

    def login_start(self) -> dict:
        """发起设备码登录，返回 {url, code, expires_in}。"""
        out = self._run(
            ["auth", "login", "--no-wait", "--json", "--domain", "base,drive"],
            retries=1,
        )
        data = json.loads(out)
        url = data.get("verification_url") or ""
        code = data.get("device_code") or ""
        if not url or not code:
            raise FeishuError(f"登录初始化失败：{out[:200]}")
        return {"url": url, "code": code, "expires_in": data.get("expires_in", 600)}

    def login_finish(self, device_code: str) -> bool:
        """用户完成授权后调用；最多等 25 秒，没确认就返回 False，界面可重试。"""
        try:
            self._run(
                ["auth", "login", "--device-code", device_code, "--json"],
                timeout=25, retries=1,
            )
        except FeishuError:
            pass
        except subprocess.TimeoutExpired:
            pass
        ok, _ = self.auth_status()
        return ok
