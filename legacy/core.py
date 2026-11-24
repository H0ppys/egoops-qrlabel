"""核心逻辑：任务数据源、批量生成、回传飞书。

三种数据源：
1. FeishuAPI   —— 飞书开放平台（App ID / App Secret，tenant_access_token）
2. LarkCLISource —— 本机已登录的 lark-cli（无需配置应用）
3. FileSource  —— 本地 Excel / CSV / JSON 导出文件
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .label import TaskLabel, png_bytes, render_label, render_pdf

# ---------------------------------------------------------------- 默认配置
DEFAULT_BASE_TOKEN = "<FILL_ME_BASE_TOKEN>"
DEFAULT_TASK_TABLE = "<FILL_ME_TASK_TABLE>"
DEFAULT_SITE_TABLE = "<FILL_ME_SITE_TABLE>"

F_NAME = "任务名称"
F_ID = "任务ID"
F_SITE = "所属采集点"
F_STATUS = "任务状态"
F_CODE = "场景任务码"

FEISHU_HOST = "https://open.feishu.cn"


class FeishuError(RuntimeError):
    pass


# ---------------------------------------------------------------- 数据模型
@dataclass
class Task:
    record_id: str
    task_id: str
    task_name: str
    site_name: str = ""
    status: str = ""
    code_tokens: list[str] = field(default_factory=list)

    @property
    def has_code(self) -> bool:
        return bool(self.code_tokens)

    def to_label(self) -> TaskLabel:
        return TaskLabel(self.task_id, self.task_name, self.site_name)


def _text_of(value) -> str:
    """把多维表格单元格值转成纯文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "name", "value", "full_text"):
            if key in value:
                return _text_of(value[key])
        return ""
    if isinstance(value, list):
        parts = [_text_of(v) for v in value]
        return "、".join(p for p in parts if p)
    return str(value)


def _link_record_ids(value) -> list[str]:
    ids: list[str] = []
    if isinstance(value, list):
        for v in value:
            if isinstance(v, dict):
                if v.get("record_ids"):
                    ids.extend(str(x) for x in v["record_ids"])
                elif v.get("id"):
                    ids.append(str(v["id"]))
            elif isinstance(v, str):
                ids.append(v)
    return ids


def _attachment_tokens(value) -> list[str]:
    tokens: list[str] = []
    if isinstance(value, list):
        for v in value:
            if isinstance(v, dict) and v.get("file_token"):
                tokens.append(str(v["file_token"]))
            elif isinstance(v, str):
                tokens.append(v)
    return tokens


# ---------------------------------------------------------------- 飞书 API
class FeishuAPI:
    """飞书开放平台客户端（tenant_access_token）。"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        base_token: str = DEFAULT_BASE_TOKEN,
        task_table: str = DEFAULT_TASK_TABLE,
        site_table: str = DEFAULT_SITE_TABLE,
        user_token: str = "",
    ) -> None:
        self.app_id = app_id.strip()
        self.app_secret = app_secret.strip()
        self.base_token = base_token.strip()
        self.task_table = task_table.strip()
        self.site_table = site_table.strip()
        self.user_token = user_token.strip()
        self._access_token = ""
        self._token_kind = ""

    # -- HTTP ------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None,
                 timeout: int = 30) -> dict:
        token = self.user_token or self._token()
        data = None
        headers = {"Authorization": f"Bearer {token}"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(FEISHU_HOST + path, data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")
            raise FeishuError(f"{exc.code} {detail[:400]}") from exc
        except urllib.error.URLError as exc:
            raise FeishuError(f"网络无法连接飞书开放平台：{exc.reason}") from exc
        if payload.get("code") not in (0, None):
            raise FeishuError(f"{payload.get('code')} {payload.get('msg')}")
        return payload.get("data", payload)

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        if not self.app_id or not self.app_secret:
            raise FeishuError("未配置 App ID / App Secret")
        req = urllib.request.Request(
            FEISHU_HOST + "/open-apis/auth/v3/tenant_access_token/internal",
            data=json.dumps({"app_id": self.app_id,
                             "app_secret": self.app_secret}).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise FeishuError(f"获取 tenant_access_token 失败：{exc}") from exc
        if payload.get("code") != 0:
            raise FeishuError(
                f"获取 tenant_access_token 失败：{payload.get('code')} {payload.get('msg')}"
            )
        self._access_token = payload["tenant_access_token"]
        return self._access_token

    # -- 读取 ------------------------------------------------------
    def list_records(self, table_id: str, page_size: int = 500) -> list[dict]:
        items: list[dict] = []
        page_token = ""
        while True:
            query = {"page_size": str(page_size)}
            if page_token:
                query["page_token"] = page_token
            data = self._request(
                "GET",
                f"/open-apis/bitable/v1/apps/{self.base_token}/tables/"
                f"{table_id}/records?{urllib.parse.urlencode(query)}",
            )
            items.extend(data.get("items") or [])
            if not data.get("has_more"):
                break
            page_token = data.get("page_token") or ""
            if not page_token:
                break
        return items

    def list_sites(self) -> dict[str, str]:
        if not self.site_table:
            return {}
        try:
            items = self.list_records(self.site_table)
        except FeishuError:
            return {}
        result = {}
        for item in items:
            fields = item.get("fields") or {}
            name = _text_of(fields.get("采集点名称")) or _text_of(fields.get("名称"))
            if name:
                result[str(item.get("record_id"))] = name
        return result

    def list_tasks(self) -> list[Task]:
        sites = self.list_sites()
        tasks: list[Task] = []
        for item in self.list_records(self.task_table):
            fields = item.get("fields") or {}
            task_id = _text_of(fields.get(F_ID)).strip()
            if not task_id:
                continue
            site = ""
            ids = _link_record_ids(fields.get(F_SITE))
            for rid in ids:
                if rid in sites:
                    site = sites[rid]
                    break
            if not site:
                site = _text_of(fields.get(F_SITE))
            tasks.append(
                Task(
                    record_id=str(item.get("record_id")),
                    task_id=task_id,
                    task_name=_text_of(fields.get(F_NAME)),
                    site_name=site,
                    status=_text_of(fields.get(F_STATUS)),
                    code_tokens=_attachment_tokens(fields.get(F_CODE)),
                )
            )
        tasks.sort(key=lambda t: (t.site_name, t.task_id))
        return tasks

    # -- 写入 ------------------------------------------------------
    def upload_png(self, data: bytes, filename: str) -> str:
        boundary = "----qrlabel" + uuid.uuid4().hex
        parts: list[bytes] = []

        def add_field(name: str, value: str) -> None:
            parts.append(
                (
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\""
                    f"\r\n\r\n{value}\r\n"
                ).encode("utf-8")
            )

        add_field("file_name", filename)
        add_field("parent_type", "bitable_file")
        add_field("parent_node", self.base_token)
        add_field("size", str(len(data)))
        parts.append(
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                f"filename=\"{filename}\"\r\nContent-Type: image/png\r\n\r\n"
            ).encode("utf-8")
            + data
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)

        token = self.user_token or self._token()
        req = urllib.request.Request(
            FEISHU_HOST + "/open-apis/drive/v1/medias/upload_all",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise FeishuError(
                f"上传素材失败：{exc.code} {exc.read().decode('utf-8', 'ignore')[:300]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise FeishuError(f"上传素材失败：{exc.reason}") from exc
        if payload.get("code") != 0:
            raise FeishuError(f"上传素材失败：{payload.get('code')} {payload.get('msg')}")
        return payload["data"]["file_token"]

    def set_code(self, record_id: str, file_token: str) -> None:
        self._request(
            "PUT",
            f"/open-apis/bitable/v1/apps/{self.base_token}/tables/"
            f"{self.task_table}/records/{record_id}",
            {"fields": {F_CODE: [{"file_token": file_token}]}},
        )

    def check(self) -> str:
        tasks = self.list_tasks()
        return f"连接成功，读取到 {len(tasks)} 条任务"


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


def _find_tokens(obj) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "file_token" and isinstance(v, str):
                found.append(v)
            else:
                found.extend(_find_tokens(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_find_tokens(v))
    return found


# ---------------------------------------------------------------- 本地文件
class FileSource:
    """从 Excel / CSV / JSON 读取任务。"""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def list_tasks(self) -> list[Task]:
        suffix = self.path.suffix.lower()
        if suffix in (".xlsx", ".xlsm"):
            rows = self._read_xlsx()
        elif suffix == ".json":
            rows = self._read_json()
        elif suffix == ".ndjson":
            rows = [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        else:
            rows = self._read_csv()

        tasks: list[Task] = []
        for i, row in enumerate(rows):
            task_id = _text_of(_pick(row, "任务ID", "任务 ID", "task_id", "taskId", "ID")).strip()
            name = _text_of(_pick(row, "任务名称", "任务名", "task_name", "name", "标题")).strip()
            site = _text_of(_pick(row, "采集点", "采集点名称", "所属采集点", "site", "site_name")).strip()
            status = _text_of(_pick(row, "任务状态", "状态", "status")).strip()
            if not task_id and not name:
                continue
            tasks.append(
                Task(
                    record_id=_text_of(_pick(row, "record_id", "recordId")) or f"row-{i}",
                    task_id=task_id,
                    task_name=name,
                    site_name=site,
                    status=status,
                )
            )
        return tasks

    def _read_xlsx(self) -> list[dict]:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("读取 Excel 需要 openpyxl") from exc
        wb = load_workbook(self.path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        rows = ws.iter_rows(values_only=True)
        header = [str(c) if c is not None else "" for c in next(rows)]
        out = []
        for values in rows:
            if not any(v is not None and str(v).strip() for v in values):
                continue
            out.append({h: v for h, v in zip(header, values)})
        return out

    def _read_csv(self) -> list[dict]:
        raw = self.path.read_bytes()
        for enc in ("utf-8-sig", "gb18030", "utf-16"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", "ignore")
        dialect = "\t" if text.count("\t") > text.count(",") else ","
        return list(csv.DictReader(io.StringIO(text), delimiter=dialect))

    def _read_json(self) -> list[dict]:
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            for key in ("records", "items", "data", "tasks"):
                if isinstance(data.get(key), list):
                    return data[key]
        return data


def _pick(row: dict, *names: str):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for n in names:
        v = lowered.get(n.strip().lower())
        if v not in (None, ""):
            return v
    return None


# ---------------------------------------------------------------- 批量流程
def generate_files(
    tasks: list[Task],
    out_dir: Path,
    make_pdf: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    png_paths: list[Path] = []
    total = len(tasks)
    for i, task in enumerate(tasks, 1):
        img = render_label(task.to_label())
        path = out_dir / f"{task.task_id}.png"
        path.write_bytes(png_bytes(img))
        png_paths.append(path)
        if progress:
            progress(i, total, f"生成 {task.task_id}.png")
    pdf_path = None
    if make_pdf and tasks:
        pdf_path = out_dir / f"场景任务码_{len(tasks)}张.pdf"
        pdf_path.write_bytes(render_pdf([t.to_label() for t in tasks]))
        if progress:
            progress(total, total, f"生成 {pdf_path.name}")
    return {"png": png_paths, "pdf": pdf_path}
