"""数据模型与多维表格单元格解析（拆分自 core.py）"""

from __future__ import annotations

from dataclasses import dataclass, field

from .label import TaskLabel

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
