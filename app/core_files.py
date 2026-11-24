"""本地 Excel / CSV / JSON / NDJSON 数据源（拆分自 core.py）"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .core_models import Task, _text_of

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
