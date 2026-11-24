"""飞书开放平台客户端（tenant_access_token）（拆分自 core.py）"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .core_config import (
    DEFAULT_BASE_TOKEN,
    DEFAULT_SITE_TABLE,
    DEFAULT_TASK_TABLE,
    F_CODE,
    F_ID,
    F_NAME,
    F_SITE,
    F_STATUS,
    FEISHU_HOST,
    FeishuError,
)
from .core_models import Task, _attachment_tokens, _link_record_ids, _text_of

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
