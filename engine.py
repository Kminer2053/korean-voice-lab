"""엔진 실행기. 메모리에는 엔진 하나만 두고, 생성은 한 번에 하나씩 한다.

엔진(모델 + 실행 방식)의 실제 구현은 backends/ 에 있다.
"""

from __future__ import annotations

import os
import re
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

import local_env
import backends
from audio_prep import ensure_tail_silence
from textnorm import spell_numbers
import system_probe
from backends import Backend, BackendUnavailable

_LOCK = threading.Lock()
_ACTIVE: Backend | None = None
_ACTIVE_ID: str | None = None



# 결과 끝에 남길 최소 무음(초). 문장 사이 쉼을 고르게 한다.
# VOICELAB_TAIL_SILENCE=0 이면 덧붙이지 않는다.
TAIL_SILENCE_SEC = float(os.environ.get("VOICELAB_TAIL_SILENCE", "0.3"))

class ModelDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class SynthesisReport:
    engine_id: str
    model_id: str
    device: str
    output_path: Path
    ref_duration_sec: float
    output_duration_sec: float
    load_sec: float
    generate_sec: float
    sample_rate: int
    output_samples: int
    peak_memory_bytes: int | None
    stats: dict = field(default_factory=dict)  # 엔진별 측정값(Qwen3 말끝 보정 ending 등)


def is_model_loaded() -> bool:
    return _ACTIVE is not None


def loaded_engine_id() -> str | None:
    return _ACTIVE_ID if _ACTIVE is not None else None


def loaded_model_id() -> str | None:
    return _ACTIVE.info.model_id if _ACTIVE is not None else None


def is_busy() -> bool:
    return _LOCK.locked()


def unload_model() -> None:
    global _ACTIVE, _ACTIVE_ID
    if _ACTIVE is not None:
        try:
            _ACTIVE.unload()
        finally:
            _ACTIVE = None
            _ACTIVE_ID = None


def resolve_engine(name: str | None) -> str:
    """'chatterbox'(모델 계열) 또는 'chatterbox-mlx'(정확한 id). 비우면 기본 엔진."""
    if not name or not name.strip() or name.strip().lower() == "auto":
        engine_id = backends.default_engine_id()
        if engine_id is None:
            raise ModelDisabled("이 컴퓨터에서 쓸 수 있는 엔진이 없습니다. README의 설치 안내를 보세요.")
        return engine_id
    key = name.strip().lower()
    if key in backends.REGISTRY:
        if key not in backends.available_ids():
            reason = next((e["reason"] for e in backends.all_status() if e["id"] == key), "")
            raise ModelDisabled(f"{backends.info(key).label} 엔진을 이 컴퓨터에서 쓸 수 없습니다: {reason}")
        return key
    family = backends.family_members(key)
    ready = backends.available_ids()
    for engine_id in family:
        if engine_id in ready:
            return engine_id
    if family:
        raise ModelDisabled(f"'{name}' 모델을 이 컴퓨터에서 돌릴 실행 방식이 없습니다. 후보: {', '.join(family)}")
    known = sorted(set(backends.families()) | set(backends.REGISTRY))
    raise ModelDisabled(f"엔진 '{name}'를 모릅니다. 쓸 수 있는 이름: {', '.join(known)}")


def _activate(engine_id: str) -> tuple[Backend, float]:
    global _ACTIVE, _ACTIVE_ID
    if _ACTIVE is not None and _ACTIVE_ID == engine_id:
        return _ACTIVE, 0.0
    # 쓸 수 없는 엔진이면 지금 올라가 있는 모델을 내리기 전에 실패한다.
    backend = backends.get(engine_id)
    system_probe.assert_disk_for_download(
        backend.info.model_id, backend.info.approx_download_gb, local_env.HF_HUB_CACHE
    )
    unload_model()  # 16GB 기기에서 두 모델을 함께 두지 않는다.
    print(f"엔진 준비: {backend.info.label} ({backend.info.model_id})", flush=True)
    print("캐시에 없으면 Hugging Face에서 받습니다. 진행 막대는 이 터미널에 표시됩니다.", flush=True)
    started = time.perf_counter()
    try:
        backend.load()
    except Exception:
        backend.unload()
        raise
    _ACTIVE, _ACTIVE_ID = backend, engine_id
    return backend, time.perf_counter() - started


def _wav_duration(path: Path) -> tuple[float, int, int]:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
    if rate <= 0:
        raise RuntimeError(f"샘플레이트가 0입니다: {path}")
    return frames / float(rate), rate, frames


def _write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(np.nan_to_num(np.asarray(audio, dtype=np.float32).reshape(-1)), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())


def _clip_token(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", value).strip("-.")
    return cleaned[:24] or "목소리"


def _unused_output(filename: str) -> Path:
    path = local_env.OUTPUTS / filename
    if not path.exists():
        return path
    stem, suffix = Path(filename).stem, Path(filename).suffix
    for number in range(2, 1000):
        candidate = local_env.OUTPUTS / f"{stem}-{number}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("같은 이름의 결과 파일을 피하지 못했습니다.")


def synthesize(
    *,
    ref_wav: Path,
    ref_text: str,
    text: str,
    engine: str | None = None,
    clip_label: str | None = None,
    on_phase: Callable[[str], None] | None = None,
    output_path: Path | None = None,
    seed: int | None = None,
    wait_sec: float | None = None,
    language: str = "ko",
) -> SynthesisReport:
    """참조 녹음 하나(+ 대본)로 text 를 읽은 WAV 를 만든다.

    다른 생성이 진행 중이면 wait_sec 동안 기다린다(None 이면 끝날 때까지).
    output_path 가 없으면 outputs/ 에 새 이름으로 쓴다.
    """

    def phase(name: str) -> None:
        if on_phase is not None:
            on_phase(name)

    engine_id = resolve_engine(engine)
    acquired = _LOCK.acquire(timeout=-1 if wait_sec is None else max(0.0, wait_sec))
    if not acquired:
        raise RuntimeError("이미 다른 생성이 진행 중입니다. 끝난 뒤에 다시 누르세요.")
    try:
        if not ref_wav.is_file():
            raise RuntimeError(f"참조 WAV가 없습니다: {ref_wav}")
        cleaned_text = text.strip()
        if not cleaned_text:
            raise RuntimeError("생성할 문장이 비어 있습니다.")
        info = backends.info(engine_id)
        if not info.reads_digits:
            cleaned_text = spell_numbers(cleaned_text)
        cleaned_ref = ref_text.strip()
        if info.needs_ref_text and not cleaned_ref:
            raise RuntimeError("이 엔진은 참조 녹음의 대본이 필요합니다. 대본이 비어 있습니다.")
        phase("loading")
        try:
            backend, load_sec = _activate(engine_id)
            phase("generating")
            ref_duration, _rate, _frames = _wav_duration(ref_wav)
            started = time.perf_counter()
            out = backend.generate(
                text=cleaned_text, ref_wav=ref_wav, ref_text=cleaned_ref, seed=seed, language=language
            )
            generate_sec = time.perf_counter() - started
        except BackendUnavailable:
            raise
        except Exception:
            unload_model()  # 메모리 부족 등에서 다음 시도가 깨끗하게 시작하도록
            raise
        audio = np.asarray(out.audio, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            raise RuntimeError("모델 출력 샘플이 0개입니다.")
        audio = ensure_tail_silence(audio, out.sample_rate, TAIL_SILENCE_SEC)
        if output_path is None:
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
            output_path = _unused_output(f"{_clip_token(clip_label or 'voice')}_{stamp}.wav")
        output_path = Path(output_path)
        _write_wav(output_path, audio, out.sample_rate)
        output_duration, written_rate, output_samples = _wav_duration(output_path)
        if written_rate != out.sample_rate:
            raise RuntimeError("저장한 WAV의 샘플레이트가 모델 출력과 다릅니다.")
        peak = out.stats.get("peak_memory_bytes")
        return SynthesisReport(
            engine_id=engine_id,
            model_id=info.model_id,
            device=backend.device(),
            output_path=output_path.resolve(),
            ref_duration_sec=ref_duration,
            output_duration_sec=output_duration,
            load_sec=load_sec,
            generate_sec=generate_sec,
            sample_rate=out.sample_rate,
            output_samples=output_samples,
            peak_memory_bytes=int(peak) if peak is not None else None,
            stats={k: v for k, v in out.stats.items() if k != "peak_memory_bytes"},
        )
    finally:
        _LOCK.release()
