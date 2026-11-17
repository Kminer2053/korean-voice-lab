"""생성 기록과 주관 점수. 측정하지 않은 유사도나 MOS는 쓰지 않는다."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import local_env
import system_probe

CSV_PATH = local_env.OUTPUTS / "results.csv"
JSON_PATH = local_env.OUTPUTS / "results.json"
COMPARISON_PATH = local_env.OUTPUTS / "comparison.md"
SCORE_KEYS = ("timbre", "pronunciation", "prosody", "emotion", "quality")
CSV_FIELDS = [
    "created_at",
    "model_id",
    "model_choice",
    "sentence_id",
    "reference_kind",
    "reference_note",
    "ref_duration_sec",
    "output_duration_sec",
    "load_sec",
    "generate_sec",
    "rtf_generate_over_audio",
    "library_processing_time_sec",
    "library_real_time_factor_audio_over_generate",
    "library_peak_memory_div_1e9",
    "mlx_peak_bytes",
    "mlx_active_bytes",
    "sample_rate",
    "output_samples",
    "output_path",
    "generation_text",
    "score_timbre",
    "score_pronunciation",
    "score_prosody",
    "score_emotion",
    "score_quality",
]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_rows() -> list[dict[str, Any]]:
    if not JSON_PATH.is_file():
        return []
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("results.json 형식이 목록이 아닙니다.")
    return data


def _rtf(generate_sec: float, output_duration: float) -> float | None:
    if output_duration <= 0:
        return None
    return generate_sec / output_duration


def append_generation(
    *,
    created_at: str | None = None,
    model_id: str,
    model_choice: str,
    sentence_id: str,
    reference_kind: str,
    reference_note: str,
    ref_duration_sec: float,
    output_duration_sec: float,
    load_sec: float,
    generate_sec: float,
    library_processing_time_sec: float,
    library_real_time_factor: float | None,
    library_peak_memory_gb: float | None,
    mlx_peak_bytes: int,
    mlx_active_bytes: int,
    sample_rate: int,
    output_samples: int,
    output_path: str,
    generation_text: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "created_at": created_at or _now(),
        "model_id": model_id,
        "model_choice": model_choice,
        "sentence_id": sentence_id,
        "reference_kind": reference_kind,
        "reference_note": reference_note,
        "ref_duration_sec": ref_duration_sec,
        "output_duration_sec": output_duration_sec,
        "load_sec": load_sec,
        "generate_sec": generate_sec,
        "rtf_generate_over_audio": _rtf(generate_sec, output_duration_sec),
        "library_processing_time_sec": library_processing_time_sec,
        "library_real_time_factor_audio_over_generate": library_real_time_factor,
        "library_peak_memory_div_1e9": library_peak_memory_gb,
        "mlx_peak_bytes": mlx_peak_bytes,
        "mlx_active_bytes": mlx_active_bytes,
        "sample_rate": sample_rate,
        "output_samples": output_samples,
        "output_path": output_path,
        "generation_text": generation_text,
        "score_timbre": None,
        "score_pronunciation": None,
        "score_prosody": None,
        "score_emotion": None,
        "score_quality": None,
    }
    rows = load_rows()
    rows.append(row)
    _write(rows)
    return row


def save_scores(output_path: str, scores: dict[str, int]) -> dict[str, Any]:
    rows = load_rows()
    target = None
    for row in rows:
        if row.get("output_path") == output_path:
            target = row
    if target is None:
        raise RuntimeError("점수를 붙일 생성 기록을 찾지 못했습니다. 먼저 음성을 생성하세요.")
    for key in SCORE_KEYS:
        value = scores[key]
        if value < 1 or value > 5:
            raise RuntimeError("점수는 1에서 5 사이여야 합니다.")
        target[f"score_{key}"] = value
    _write(rows)
    return target


def _write(rows: list[dict[str, Any]]) -> None:
    local_env.OUTPUTS.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})
    write_comparison(rows)


def _fmt(value: object) -> str:
    if value is None:
        return "없음"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def write_comparison(rows: list[dict[str, Any]] | None = None) -> None:
    if rows is None:
        rows = load_rows()
    decision = system_probe.decide_model_17()
    lines = [
        "# 0.6B와 1.7B 비교",
        "",
        "주관 청취 평가입니다. 측정하지 않은 유사도, MOS, 속도는 적지 않습니다.",
        "RTF는 생성 시간(초)을 출력 길이(초)로 나눈 값이며, 생성이 성공한 뒤에만 계산합니다.",
        "라이브러리 real_time_factor는 mlx-audio 0.6.1 기준 출력 길이 / 처리 시간입니다.",
        "",
        "## 1.7B",
        "",
    ]
    ran_17 = [row for row in rows if row.get("model_choice") == "1.7B"]
    if ran_17:
        lines.append("실행함. 아래는 기록된 실측입니다.")
        lines.append("")
        for row in ran_17:
            lines.extend(_row_lines(row))
    else:
        lines.append("미실행.")
        lines.append("")
        lines.append(decision.reason)
        lines.append("")
    lines.extend(["## 0.6B", ""])
    ran_06 = [row for row in rows if row.get("model_choice") == "0.6B"]
    if not ran_06:
        lines.append("미실행. 아직 0.6B 생성 기록이 없습니다.")
        lines.append("")
    else:
        for row in ran_06:
            lines.extend(_row_lines(row))
    lines.extend(
        [
            "## 직접 들어볼 항목",
            "",
            "같은 참조 음성과 대본, 같은 문장으로 두 모델을 만들었을 때만 나란히 비교하세요. 차이는 숨기지 않습니다.",
            "1.7B를 실행하지 않았다면 블라인드 A/B도 미실행입니다.",
            "",
            "- 음색 유사도 (1–5, 주관)",
            "- 한국어 발음 (1–5, 주관)",
            "- 억양·리듬 (1–5, 주관)",
            "- 감정 (1–5, 주관)",
            "- 잡음·음질·깨짐 (1–5, 주관)",
            "",
            "macOS say 시스템 음성으로 만든 시험 파일은 사람 녹음이 아니며 품질 평가 대상이 아닙니다.",
            "",
        ]
    )
    COMPARISON_PATH.write_text("\n".join(lines), encoding="utf-8")


def _row_lines(row: dict[str, Any]) -> list[str]:
    note = row.get("reference_note") or ""
    return [
        f"- 시각: {row.get('created_at')}",
        f"- 모델 ID: {row.get('model_id')}",
        f"- 문장 ID: {row.get('sentence_id')}",
        f"- 참조 종류: {row.get('reference_kind')}. {note}",
        f"- 원본 길이(초): {_fmt(row.get('ref_duration_sec'))}",
        f"- 출력 길이(초): {_fmt(row.get('output_duration_sec'))}",
        f"- 모델 준비 시간(초, 캐시에 있으면 0에 가깝습니다): {_fmt(row.get('load_sec'))}",
        f"- 생성 시간(초): {_fmt(row.get('generate_sec'))}",
        f"- RTF(생성/출력): {_fmt(row.get('rtf_generate_over_audio'))}",
        f"- 라이브러리 처리 시간(초): {_fmt(row.get('library_processing_time_sec'))}",
        f"- 라이브러리 real_time_factor(출력/처리): {_fmt(row.get('library_real_time_factor_audio_over_generate'))}",
        f"- 라이브러리 peak_memory_usage(바이트/1e9): {_fmt(row.get('library_peak_memory_div_1e9'))}",
        f"- mlx.get_peak_memory() 바이트: {_fmt(row.get('mlx_peak_bytes'))}",
        f"- mlx.get_active_memory() 바이트: {_fmt(row.get('mlx_active_bytes'))}",
        f"- 파일: {row.get('output_path')}",
        "",
    ]


def blind_assignment(rows: list[dict[str, Any]], sentence_id: str, seed: int) -> dict[str, Any] | None:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("sentence_id") != sentence_id:
            continue
        choice = str(row.get("model_choice"))
        if choice in {"0.6B", "1.7B"} and Path(str(row.get("output_path"))).is_file():
            grouped[choice] = row
    if "0.6B" not in grouped or "1.7B" not in grouped:
        return None
    order = ["0.6B", "1.7B"]
    if seed % 2 == 1:
        order = ["1.7B", "0.6B"]
    return {
        "A": grouped[order[0]]["output_path"],
        "B": grouped[order[1]]["output_path"],
        "reveal": f"A={order[0]}, B={order[1]}",
    }
