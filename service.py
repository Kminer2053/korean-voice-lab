"""화면·HTTP API·명령줄·MCP가 함께 쓰는 생성 서비스.

모델은 프로세스마다 하나만 메모리에 올리고, 생성은 한 번에 하나씩 순서대로 한다.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import local_env
import audio_prep
import engine
import records
import backends
from textnorm import spell_numbers
import voices
from audio_prep import UserInputError

API_VERSION = "1"
LEXICON_PATH = local_env.ROOT / "lexicon.json"
MAX_TEXT_CHARS = 2000

# 화면과 /api/health 가 함께 보는 상태.
STATUS: dict[str, Any] = {"phase": "idle", "detail": "", "last": None}


@dataclass
class Result:
    path: Path
    style: str
    style_label: str
    text: str
    spoken_text: str
    duration_sec: float
    sample_rate: int
    generate_sec: float
    load_sec: float
    model: str
    engine: str = ""
    device: str = ""
    seed: int | None = None
    cached: bool = False
    id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "id": self.id,
            "path": str(self.path),
            "file": self.path.name,
            "style": self.style,
            "style_label": self.style_label,
            "text": self.text,
            "spoken_text": self.spoken_text,
            "duration_sec": round(self.duration_sec, 3),
            "sample_rate": self.sample_rate,
            "generate_sec": round(self.generate_sec, 3),
            "load_sec": round(self.load_sec, 3),
            "model": self.model,
            "engine": self.engine,
            "device": self.device,
            "seed": self.seed,
            "cached": self.cached,
        }


# ---------------------------------------------------------------- 발음 사전
def load_lexicon() -> dict[str, str]:
    """lexicon.json: {"배지": "뺏지"} 처럼 원문 → 읽을 소리. 없으면 빈 사전."""
    if not LEXICON_PATH.is_file():
        return {}
    try:
        data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("replace"), dict):
        data = data["replace"]
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if str(k) and not str(k).startswith("_")}


def save_lexicon(mapping: dict[str, str]) -> None:
    cleaned = {str(k).strip(): str(v).strip() for k, v in mapping.items() if str(k).strip()}
    LEXICON_PATH.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_lexicon(text: str, extra: dict[str, str] | None = None, use_file: bool = True) -> str:
    """긴 단어부터 바꾼다. [뺏지]처럼 대괄호로 쓴 소리 표기는 대괄호를 벗긴다."""
    mapping = dict(load_lexicon()) if use_file else {}
    if extra:
        mapping.update({str(k): str(v) for k, v in extra.items() if str(k)})
    out = text
    for key in sorted(mapping, key=len, reverse=True):
        out = out.replace(key, mapping[key])
    out = re.sub(r"\[([^\[\]/]+)\]", r"\1", out)
    return out


# ---------------------------------------------------------------- 생성
def _set_phase(name: str, detail: str = "") -> None:
    STATUS["phase"] = name
    STATUS["detail"] = detail


def engines() -> list[dict[str, Any]]:
    return backends.all_status()


def health() -> dict[str, Any]:
    styles = voices.list_styles()
    default = backends.default_engine_id()
    return {
        "ok": True,
        "api_version": API_VERSION,
        "service": "qwen3-voice-lab",
        "platform": backends.current_platform(),
        "default_engine": default,
        "engines": [{"id": e["id"], "family": e["family"], "available": e["available"]} for e in engines()],
        "loaded_engine": engine.loaded_engine_id(),
        "model": engine.loaded_model_id() or (backends.info(default).model_id if default else None),
        "model_loaded": engine.is_model_loaded(),
        "busy": engine.is_busy(),
        "phase": STATUS["phase"],
        "styles": [{"id": s.id, "label": s.label, "ready": s.ready} for s in styles],
        "outputs_dir": str(local_env.OUTPUTS.resolve()),
    }


def synthesize(
    text: str,
    style: str | None = "default",
    *,
    output_path: str | Path | None = None,
    ref_text: str | None = None,
    seed: int | None = None,
    engine_name: str | None = None,
    replace: dict[str, str] | None = None,
    use_lexicon: bool = True,
    item_id: str | None = None,
    on_phase: Callable[[str], None] | None = None,
    wait_sec: float | None = None,
) -> Result:
    """한 문장(또는 한 덩어리)을 고른 말투로 읽어 WAV 하나를 만든다."""
    raw = (text or "").strip()
    if not raw:
        raise UserInputError("만들 문장이 비어 있습니다.")
    if len(raw) > MAX_TEXT_CHARS:
        raise UserInputError(
            f"문장이 너무 깁니다({len(raw)}자). {MAX_TEXT_CHARS}자 이하로 나누어 보내세요. "
            "여러 문장은 /api/batch 나 명령줄 batch 를 쓰면 하나씩 만듭니다."
        )
    chosen = voices.resolve(style)
    ref_path = chosen.path
    if ref_path is None or not voices.usable_reference(ref_path):
        raise UserInputError(
            f"'{chosen.label}({chosen.id})' 말투에 등록된 참조 녹음이 없습니다. 화면의 ① 목소리 등록에서 먼저 녹음하세요."
        )
    script = (ref_text or "").strip() or chosen.script.strip()
    try:
        engine_id = engine.resolve_engine(engine_name)
    except engine.ModelDisabled as exc:
        raise UserInputError(str(exc)) from exc
    if backends.info(engine_id).needs_ref_text and not script:
        raise UserInputError(
            f"{backends.info(engine_id).label} 엔진은 참조 녹음의 대본이 필요합니다. 목소리 등록 탭에서 읽은 문장을 적으세요."
        )
    # use_lexicon=False 이고 replace 도 없으면 문장을 손대지 않고 그대로 읽는다(예전 /synthesize 동작).
    spoken = apply_lexicon(raw, replace, use_file=use_lexicon) if (use_lexicon or replace) else raw
    if not backends.info(engine_id).reads_digits:
        spoken = spell_numbers(spoken)  # 숫자를 잘못 읽는 엔진은 한국어 소리로 바꿔 넘긴다(engine 에서도 같은 처리)
    target = Path(output_path).expanduser().resolve() if output_path else None

    def phase(name: str) -> None:
        _set_phase(name)
        if on_phase is not None:
            on_phase(name)

    try:
        report = engine.synthesize(
            engine=engine_id,
            ref_wav=ref_path,
            ref_text=script,
            text=spoken,
            clip_label=chosen.label,
            on_phase=phase,
            output_path=target,
            seed=seed,
            wait_sec=wait_sec,
        )
    except Exception as exc:
        _set_phase("error", str(exc))
        raise
    try:
        records.append(
            {
                "engine_id": report.engine_id,
                "model_id": report.model_id,
                "device": report.device,
                "style": chosen.id,
                "reference_file": ref_path.name,
                "ref_duration_sec": report.ref_duration_sec,
                "output_duration_sec": report.output_duration_sec,
                "load_sec": report.load_sec,
                "generate_sec": report.generate_sec,
                "peak_memory_bytes": report.peak_memory_bytes,
                "sample_rate": report.sample_rate,
                "output_samples": report.output_samples,
                "output_path": str(report.output_path),
                "generation_text": raw,
            }
        )
    except Exception as exc:  # 기록 실패가 생성 결과를 막지 않게 한다.
        print(f"생성 기록을 남기지 못했습니다: {exc}", flush=True)
    STATUS["last"] = {
        "generate_sec": float(report.generate_sec),
        "output_duration_sec": float(report.output_duration_sec),
        "peak_bytes": report.peak_memory_bytes,
    }
    _set_phase("ready")
    return Result(
        path=report.output_path,
        style=chosen.id,
        style_label=chosen.label,
        text=raw,
        spoken_text=spoken,
        duration_sec=report.output_duration_sec,
        sample_rate=report.sample_rate,
        generate_sec=report.generate_sec,
        load_sec=report.load_sec,
        model=report.model_id,
        engine=report.engine_id,
        device=report.device,
        seed=seed,
        id=item_id,
    )


# ---------------------------------------------------------------- 일괄 생성
@dataclass
class BatchItem:
    text: str
    id: str | None = None
    style: str | None = None
    seed: int | None = None
    engine: str | None = None
    replace: dict[str, str] = field(default_factory=dict)


def parse_items(data: Any, default_style: str | None = None) -> list[BatchItem]:
    """문장 목록을 받는다.

    - ["문장1", "문장2"]
    - [{"id": "s01", "text": "문장", "style": "talk"}, ...]
    - {"style": "guide", "items": [...]}  (공통 말투)
    """
    common_style = default_style
    common_engine: str | None = None
    common_replace: dict[str, str] = {}
    if isinstance(data, dict):
        common_style = data.get("style") or common_style
        common_engine = data.get("engine")
        common_replace = dict(data.get("replace") or {})
        data = data.get("items") or data.get("lines") or data.get("texts")
    if not isinstance(data, list) or not data:
        raise UserInputError("items 는 비어 있지 않은 목록이어야 합니다.")
    items: list[BatchItem] = []
    for index, entry in enumerate(data, start=1):
        if isinstance(entry, str):
            if not entry.strip():
                continue
            items.append(BatchItem(text=entry.strip(), style=common_style, engine=common_engine, replace=common_replace))
            continue
        if not isinstance(entry, dict):
            raise UserInputError(f"{index}번째 항목이 문자열도 객체도 아닙니다.")
        text = str(entry.get("text") or "").strip()
        if not text:
            raise UserInputError(f"{index}번째 항목의 text 가 비어 있습니다.")
        merged = dict(common_replace)
        merged.update(entry.get("replace") or {})
        items.append(
            BatchItem(
                text=text,
                id=str(entry["id"]) if entry.get("id") not in (None, "") else None,
                style=entry.get("style") or common_style,
                seed=entry.get("seed"),
                engine=entry.get("engine") or common_engine,
                replace=merged,
            )
        )
    if not items:
        raise UserInputError("만들 문장이 없습니다.")
    return items


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", value).strip("-.")
    return cleaned[:60] or "item"


def _item_digest(item: BatchItem, style: voices.Style, engine_id: str) -> str:
    fields = {
        "text": apply_lexicon(item.text, item.replace),
        "style": style.id,
        "file": style.file,
        "script": style.script,
        "seed": item.seed,
        "engine": engine_id,
    }
    if not backends.info(engine_id).reads_digits:
        fields["text"] = spell_numbers(fields["text"])  # 숫자 읽기 규칙이 바뀌면 다시 만든다
    key = json.dumps(
        fields,
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def run_batch(
    items: Iterable[BatchItem],
    out_dir: str | Path,
    *,
    default_style: str | None = None,
    default_engine: str | None = None,
    skip_existing: bool = True,
    on_item: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """문장마다 WAV 하나. out_dir/manifest.json 에 결과를 남기고, 같은 문장·말투는 다시 만들지 않는다."""
    items = list(items)
    folder = Path(out_dir).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = loaded.get("items", {}) if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            manifest = {}
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    used: set[str] = set()
    for index, item in enumerate(items, start=1):
        key = safe_name(item.id) if item.id else f"{index:03d}"
        while key in used:
            key = f"{key}-{index}"
        used.add(key)
        wav = folder / f"{key}.wav"
        try:
            style = voices.resolve(item.style or default_style)
            try:
                engine_id = engine.resolve_engine(item.engine or default_engine)
            except engine.ModelDisabled as exc:
                raise UserInputError(str(exc)) from exc
            digest = _item_digest(item, style, engine_id)
            prev = manifest.get(key) or {}
            if skip_existing and wav.is_file() and prev.get("sha") == digest:
                entry = dict(prev)
                entry.update({"ok": True, "id": key, "path": str(wav), "file": wav.name, "cached": True})
            else:
                result = synthesize(
                    item.text,
                    style.id,
                    output_path=wav,
                    seed=item.seed,
                    engine_name=engine_id,
                    replace=item.replace,
                    item_id=key,
                )
                entry = result.to_dict()
                entry["id"] = key
                entry["sha"] = digest
                manifest[key] = {k: v for k, v in entry.items() if k not in {"ok", "cached"}}
                manifest_path.write_text(
                    json.dumps({"api_version": API_VERSION, "items": manifest}, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8",
                )
        except Exception as exc:
            entry = {"ok": False, "id": key, "text": item.text, "error": str(exc)}
        results.append(entry)
        if on_item is not None:
            on_item(index, len(items), entry)
    ok = sum(1 for r in results if r.get("ok"))
    return {
        "ok": ok == len(results),
        "count": len(results),
        "succeeded": ok,
        "failed": len(results) - ok,
        "out_dir": str(folder),
        "manifest": str(manifest_path),
        "elapsed_sec": round(time.perf_counter() - started, 2),
        "items": results,
    }


def register_reference(
    style_id: str,
    audio_file: str | Path,
    script: str,
    *,
    label: str | None = None,
    description: str | None = None,
) -> voices.Style:
    """WAV/M4A 녹음을 16-bit 모노 WAV 로 바꿔 references/ 에 두고 말투에 연결한다."""
    prepared = audio_prep.prepare_upload(str(audio_file))
    if prepared.rms < audio_prep.NEAR_SILENCE_RMS:
        raise UserInputError("녹음이 무음에 가깝습니다. 다시 녹음하세요.")
    return voices.register(style_id, prepared.wav_path, script, label=label, description=description)
