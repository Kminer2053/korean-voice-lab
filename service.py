"""화면·HTTP API·명령줄·MCP가 함께 쓰는 생성 서비스.

모델은 프로세스마다 하나만 메모리에 올리고, 생성은 한 번에 하나씩 순서대로 한다.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import local_env
import audio_prep
import engine
import ending
import records
import backends
from textnorm import spell_numbers
import voices
from audio_prep import UserInputError

API_VERSION = "1"
LEXICON_PATH = local_env.ROOT / "lexicon.json"
MAX_TEXT_CHARS = 2000

# 화면과 /api/health 가 함께 보는 상태.
STATUS: dict[str, Any] = {"phase": "idle", "detail": "", "last": None, "batch": None}


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
    quality: dict[str, Any] = field(default_factory=dict)  # 말끝 보정(ending)·음량(audio) 기록

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
            "quality": self.quality,
            "warning": quality_warning(self.quality),
        }


def quality_warning(quality: dict[str, Any] | None) -> str:
    """사람이 확인해 볼 만한 결과면 짧은 이유(아니면 빈 문자열)."""
    ending_info = (quality or {}).get("ending") or {}
    if ending_info and not ending_info.get("coda", True) and ending.ENABLED:
        return "말끝이 짧게 끝났을 수 있음(꼬리말 보정 실패) — 들어 보고 어색하면 다른 버전으로 다시 만드세요"
    return ""


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
    """긴 단어부터 바꾼다. [뺏지]처럼 대괄호로 쓴 소리 표기는 대괄호를 벗긴다.

    로마자로 시작·끝나는 원문은 단어 단위로만 바꾼다(AI → 에이아이 를 넣어도 OpenAI·AIR 는 그대로).
    """
    mapping = dict(load_lexicon()) if use_file else {}
    if extra:
        mapping.update({str(k): str(v) for k, v in extra.items() if str(k)})
    out = text
    for key in sorted(mapping, key=len, reverse=True):
        if re.match(r"[A-Za-z0-9]", key[0]) or re.match(r"[A-Za-z0-9]", key[-1]):
            left = r"(?<![A-Za-z0-9])" if re.match(r"[A-Za-z0-9]", key[0]) else ""
            right = r"(?![A-Za-z0-9])" if re.match(r"[A-Za-z0-9]", key[-1]) else ""
            out = re.sub(left + re.escape(key) + right, lambda _m, v=mapping[key]: v, out)
        else:
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
        "batch": STATUS.get("batch"),  # 일괄 생성 중이면 {"done", "total", "id"}
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
    loudness: float | None = None,
    sample_rate: int | None = None,
    speed: float | None = None,
) -> Result:
    """한 문장(또는 한 덩어리)을 고른 말투로 읽어 WAV 하나를 만든다.

    seed 를 주지 않으면 무작위로 정하고 결과에 남긴다(같은 seed 로 다시 만들면 같은 결과).
    loudness(LUFS, 예: -16)·sample_rate(예: 48000)를 주면 그에 맞춰 저장한다.
    """
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
    if seed is None:
        seed = secrets.randbelow(2**31 - 1)  # 무작위지만 기록해 두어 같은 결과를 다시 얻을 수 있게
    if sample_rate is not None and int(sample_rate) not in (16000, 22050, 24000, 44100, 48000):
        raise UserInputError("sample_rate 는 16000, 22050, 24000, 44100, 48000 중 하나여야 합니다.")
    if speed is not None and not 0.8 <= float(speed) <= 1.25:
        raise UserInputError("speed(말 빠르기)는 0.8 ~ 1.25 사이여야 합니다(1 = 그대로, 1.1 = 10% 빠르게).")
    if speed is not None and abs(float(speed) - 1.0) < 1e-3:
        speed = None
    if loudness is not None and not -40 <= float(loudness) <= -5:
        raise UserInputError("loudness 는 -40 ~ -5 LUFS 사이여야 합니다(영상은 보통 -16, 유튜브 -14).")

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
            loudness_lufs=loudness,
            export_rate=sample_rate,
            speed=speed,
        )
    except Exception as exc:
        _set_phase("error", str(exc))
        raise
    quality = {k: v for k, v in (report.stats or {}).items() if k in ("ending", "audio")}
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
                "seed": seed,
                "quality": quality,
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
        quality=quality,
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
    paragraph: int | None = None  # 같은 번호끼리 한 문단(timeline 에서 문단 사이는 더 길게 쉰다)


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
                paragraph=int(entry["paragraph"]) if str(entry.get("paragraph", "")).strip().lstrip("-").isdigit() else None,
            )
        )
    if not items:
        raise UserInputError("만들 문장이 없습니다.")
    return items


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", value).strip("-.")
    return cleaned[:60] or "item"


def _item_digest(item: BatchItem, style: voices.Style, engine_id: str, options: dict | None = None) -> str:
    fields = {
        "text": apply_lexicon(item.text, item.replace),
        "style": style.id,
        "file": style.file,
        "script": style.script,
        "seed": item.seed,
        "engine": engine_id,
    }
    if engine.TAIL_SILENCE_SEC:
        fields["tail"] = engine.TAIL_SILENCE_SEC  # 끝 쉼 보정 전에 만든 파일은 다시 만든다
    if not backends.info(engine_id).reads_digits:
        fields["text"] = spell_numbers(fields["text"])  # 숫자 읽기 규칙이 바뀌면 다시 만든다
    if backends.info(engine_id).family == "qwen3" and ending.ENABLED:
        fields["ending"] = ending.VERSION  # 말끝 보정 규칙이 바뀌면 다시 만든다
    for name, value in (options or {}).items():
        if value is not None:
            fields[name] = value  # 음량·표본율을 지정했을 때만(기본 결과의 캐시 키는 그대로)
    key = json.dumps(
        fields,
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


CACHE_DIR = ".voicelab-cache"  # 일괄 결과 폴더 안: 내용(문장·말투·설정)별로 만든 WAV 를 모아 둔다


def run_batch(
    items: Iterable[BatchItem],
    out_dir: str | Path,
    *,
    default_style: str | None = None,
    default_engine: str | None = None,
    skip_existing: bool = True,
    on_item: Callable[[int, int, dict[str, Any]], None] | None = None,
    loudness: float | None = None,
    sample_rate: int | None = None,
    prune: bool = False,
    timeline: bool = False,
    gap_sec: float = 0.4,
    paragraph_gap_sec: float = 1.0,
    speed: float | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """문장마다 WAV 하나. out_dir/manifest.json 에 결과를 남긴다.

    - 같은 문장·말투·설정은 다시 만들지 않는다. 문장 순서가 바뀌어 파일 이름(번호)이 달라져도
      out_dir/.voicelab-cache 에서 찾아 쓴다. 다른 버전(seed)으로 다시 만들어도 이전 것은 그 폴더에 남는다.
    - 한 문장이 실패해도 나머지는 계속 만든다.
    - prune: 이번 목록에 없는 예전 파일은 _stale/ 로 옮기고 manifest 에서 뺀다(지우지 않음).
    - timeline: 순서대로 이어 붙인 narration.wav, 자막 narration.srt, 편집 프로그램 마커 narration_markers.csv 를 만들고
      항목마다 start_sec·end_sec 를 넣는다. 문장 사이 gap_sec, 문단(paragraph 번호가 바뀜) 사이 paragraph_gap_sec 만큼 쉰다.
    - should_stop() 이 True 가 되면 다음 문장부터 멈춘다.
    """
    items = list(items)
    folder = Path(out_dir).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder / CACHE_DIR
    manifest_path = folder / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = loaded.get("items", {}) if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            manifest = {}
    options = {"loudness": loudness, "sample_rate": sample_rate,
               "speed": None if speed is None or abs(float(speed) - 1.0) < 1e-3 else float(speed)}
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    used: set[str] = set()
    order: list[str] = []
    stopped = False

    def save_manifest() -> None:
        manifest_path.write_text(
            json.dumps({"api_version": API_VERSION, "order": order, "items": manifest}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )

    for index, item in enumerate(items, start=1):
        key = safe_name(item.id) if item.id else f"{index:03d}"
        while key in used:
            key = f"{key}-{index}"
        used.add(key)
        order.append(key)
        wav = folder / f"{key}.wav"
        STATUS["batch"] = {"done": index - 1, "total": len(items), "id": key}
        if should_stop is not None and should_stop():
            stopped = True
            entry = {"ok": False, "id": key, "text": item.text, "error": "멈춤 요청으로 만들지 않음", "skipped": True}
            results.append(entry)
            if on_item is not None:
                on_item(index, len(items), entry)
            continue
        try:
            style = voices.resolve(item.style or default_style)
            try:
                engine_id = engine.resolve_engine(item.engine or default_engine)
            except engine.ModelDisabled as exc:
                raise UserInputError(str(exc)) from exc
            digest = _item_digest(item, style, engine_id, options)
            prev = manifest.get(key) or {}
            cached_wav = cache / f"{digest}.wav"
            if skip_existing and wav.is_file() and prev.get("sha") == digest:
                entry = dict(prev)
                entry.update({"ok": True, "id": key, "path": str(wav), "file": wav.name, "cached": True})
            elif skip_existing and cached_wav.is_file() and _cache_record(cache, digest):
                shutil.copyfile(cached_wav, wav)  # 번호가 바뀌었거나 예전 버전으로 돌아감 — 다시 만들지 않음
                entry = dict(_cache_record(cache, digest))
                entry.update({"ok": True, "id": key, "path": str(wav), "file": wav.name, "cached": True, "sha": digest})
                manifest[key] = {k: v for k, v in entry.items() if k not in {"ok", "cached"}}
            else:
                result = synthesize(
                    item.text,
                    style.id,
                    output_path=wav,
                    seed=item.seed,
                    engine_name=engine_id,
                    replace=item.replace,
                    item_id=key,
                    loudness=loudness,
                    sample_rate=sample_rate,
                    speed=speed,
                )
                entry = result.to_dict()
                entry["id"] = key
                entry["sha"] = digest
                manifest[key] = {k: v for k, v in entry.items() if k not in {"ok", "cached"}}
                cache.mkdir(exist_ok=True)
                shutil.copyfile(wav, cached_wav)
                (cache / f"{digest}.json").write_text(
                    json.dumps({k: v for k, v in entry.items() if k not in {"ok", "cached", "path", "file", "id"}},
                               ensure_ascii=False), encoding="utf-8")
            save_manifest()
        except Exception as exc:
            entry = {"ok": False, "id": key, "text": item.text, "error": str(exc)}
        if item.paragraph is not None:
            entry["paragraph"] = item.paragraph
            if key in manifest and entry.get("ok"):
                manifest[key]["paragraph"] = item.paragraph
        results.append(entry)
        if on_item is not None:
            on_item(index, len(items), entry)
    STATUS["batch"] = None
    if prune:
        stale = [k for k in list(manifest) if k not in used]
        for k in stale:
            old = folder / f"{k}.wav"
            if old.is_file():
                (folder / "_stale").mkdir(exist_ok=True)
                old.replace(folder / "_stale" / old.name)
            manifest.pop(k, None)
    extras: dict[str, Any] = {}
    mixed = {str(r.get("engine")) for r in results if r.get("ok") and r.get("engine")}  # 재사용한 항목 포함
    if len(mixed) > 1:
        extras["warning"] = (f"이번 결과에 여러 엔진이 섞여 있습니다({', '.join(sorted(mixed))}). "
                             "한 영상 안에서는 목소리 느낌이 달라지니 한 엔진으로 다시 만드세요.")
    if timeline:
        extras.update(_write_timeline(folder, results, gap_sec, paragraph_gap_sec))
        for entry in results:
            if entry.get("ok") and entry["id"] in manifest:
                manifest[entry["id"]].update({k: entry[k] for k in ("start_sec", "end_sec") if k in entry})
    save_manifest()
    ok = sum(1 for r in results if r.get("ok"))
    return {
        "ok": ok == len(results),
        "count": len(results),
        "succeeded": ok,
        "failed": len(results) - ok,
        "stopped": stopped,
        "out_dir": str(folder),
        "manifest": str(manifest_path),
        "elapsed_sec": round(time.perf_counter() - started, 2),
        "items": results,
        **extras,
    }


def _cache_record(cache: Path, digest: str) -> dict | None:
    try:
        return json.loads((cache / f"{digest}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_timeline(folder: Path, results: list[dict[str, Any]], gap_sec: float, paragraph_gap_sec: float = 1.0) -> dict[str, str]:
    """성공한 항목을 순서대로 이어 붙인 narration.wav, 자막 narration.srt, 마커 narration_markers.csv.

    항목에 start_sec·end_sec 를 넣는다. paragraph 번호가 바뀌는 곳은 paragraph_gap_sec 만큼 쉰다.
    """
    import wave

    import numpy as np

    import audio_fx

    pieces: list[np.ndarray] = []
    lines: list[str] = []
    rate = None
    cursor = 0.0
    number = 0
    markers = ["Name,Start,End,Duration,Text"]
    last_paragraph = None
    for entry in results:
        if not entry.get("ok"):
            continue
        with wave.open(entry["path"], "rb") as handle:
            this_rate = handle.getframerate()
            audio = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        if rate is None:
            rate = this_rate
        elif this_rate != rate:
            audio = audio_fx.resample(audio, this_rate, rate)
        if pieces:
            pause = paragraph_gap_sec if entry.get("paragraph") != last_paragraph else gap_sec
            pieces.append(np.zeros(int(pause * rate), dtype=np.float32))
            cursor += pause
        last_paragraph = entry.get("paragraph")
        duration = audio.size / rate
        levels = audio_fx.frame_db(audio, rate)
        mask, _floor, _speech = audio_fx.speech_mask(levels)
        voiced = np.flatnonzero(mask)
        speech_end = (voiced[-1] * audio_fx.HOP_SEC + audio_fx.FRAME_SEC) if voiced.size else duration
        entry["start_sec"] = round(cursor, 3)
        entry["end_sec"] = round(cursor + duration, 3)
        number += 1
        lines += [str(number), f"{_srt_time(cursor)} --> {_srt_time(cursor + min(duration, speech_end + 0.2))}", entry.get("text", ""), ""]
        text_cell = '"' + entry.get("text", "").replace('"', '""') + '"'
        markers.append(f"{entry.get('id', number)},{_srt_time(cursor).replace(',', '.')},{_srt_time(cursor + duration).replace(',', '.')},"
                       f"{duration:.3f},{text_cell}")
        pieces.append(audio)
        cursor += duration
    if rate is None:
        return {}
    wav_path = folder / "narration.wav"
    srt_path = folder / "narration.srt"
    audio_prep.write_pcm16(wav_path, np.concatenate(pieces), rate)
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    markers_path = folder / "narration_markers.csv"
    markers_path.write_text("\ufeff" + "\n".join(markers) + "\n", encoding="utf-8")  # BOM: 엑셀·편집기에서 한글이 깨지지 않게
    return {"narration_wav": str(wav_path), "narration_srt": str(srt_path), "narration_markers": str(markers_path)}


def register_reference(
    style_id: str,
    audio_file: str | Path,
    script: str,
    *,
    label: str | None = None,
    description: str | None = None,
) -> voices.Style:
    """녹음을 검사해(대본 맞춤·길이·잡음·찢어짐 등) 다듬은 16-bit 모노 WAV 로 references/ 에 두고 말투에 연결한다.

    검사에서 실패 항목이 있으면 등록하지 않고 이유를 모두 담아 UserInputError 를 낸다.
    """
    import audio_fx

    script = (script or "").strip()
    prepared = audio_prep.prepare_upload(str(audio_file), script)
    qc = prepared.qc or {}
    if audio_fx.has_failure(qc):
        prepared.wav_path.unlink(missing_ok=True)  # 거절한 녹음은 references/ 에 남기지 않는다
        raise UserInputError("이 녹음은 등록하지 않았습니다.\n" + audio_fx.qc_text(qc))
    return voices.register(style_id, prepared.wav_path, script, label=label, description=description, qc=qc)


def check_reference(audio_file: str | Path, script: str | None = None) -> dict:
    """등록하지 않고 검사만 한다(화면 미리 보기·API)."""
    return audio_prep.prepare_upload(str(audio_file), script, save=False).qc or {}
