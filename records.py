"""생성 기록(outputs/results.csv·json). 측정하지 않은 유사도나 MOS는 쓰지 않는다."""

from __future__ import annotations

import csv
import json
import threading
from datetime import datetime
from typing import Any

import local_env

CSV_PATH = local_env.OUTPUTS / "results.csv"
JSON_PATH = local_env.OUTPUTS / "results.json"
_LOCK = threading.Lock()
FIELDS = [
    "created_at",
    "engine_id",
    "model_id",
    "device",
    "style",
    "reference_file",
    "ref_duration_sec",
    "output_duration_sec",
    "load_sec",
    "generate_sec",
    "rtf_generate_over_audio",
    "peak_memory_bytes",
    "sample_rate",
    "output_samples",
    "output_path",
    "generation_text",
]


def load_rows() -> list[dict[str, Any]]:
    if not JSON_PATH.is_file():
        return []
    try:
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def append(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row.setdefault("created_at", datetime.now().astimezone().isoformat(timespec="seconds"))
    out = float(row.get("output_duration_sec") or 0)
    row["rtf_generate_over_audio"] = (float(row.get("generate_sec") or 0) / out) if out > 0 else None
    with _LOCK:
        rows = load_rows()
        rows.append(row)
        local_env.OUTPUTS.mkdir(parents=True, exist_ok=True)
        JSON_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            for item in rows:
                writer.writerow({key: item.get(key) for key in FIELDS})
    return row
