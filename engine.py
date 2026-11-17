"""Qwen3-TTS Base 8-bit 로컬 복제. voice 프리셋과 CustomVoice/VoiceDesign은 쓰지 않는다."""

from __future__ import annotations

import gc
import re
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, assert_never

import numpy as np

import local_env
import system_probe
from system_probe import MODEL_06, MODEL_17

# 환경 변수를 적용한 뒤에만 불러온다.
import mlx.core as mx
from mlx_audio.tts.utils import load

ModelChoice = Literal["0.6B", "1.7B"]
_LOCK = threading.Lock()
_MODEL = None
_MODEL_ID: str | None = None
# 측정된 기본 한도(16320875724)는 기기 메모리 거의 전부다.
# 16GiB 통합 메모리에서 0.6B(약 2.76GiB)가 들어가고 OS 여유가 남도록 8GiB로 제한한다.
MEMORY_LIMIT_BYTES = 8 * system_probe.GIB
CACHE_LIMIT_BYTES = 2 * system_probe.GIB


class ModelDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class SynthesisReport:
    model_id: str
    model_choice: ModelChoice
    sentence_id: str
    output_path: Path
    ref_duration_sec: float
    output_duration_sec: float
    load_sec: float
    generate_sec: float
    sample_rate: int
    output_samples: int
    library_processing_time_sec: float
    library_real_time_factor: float | None
    library_peak_memory_gb: float | None
    mlx_peak_bytes: int
    mlx_active_bytes: int


def assert_model_allowed(choice: ModelChoice) -> str:
    match choice:
        case "0.6B":
            system_probe.assert_disk_for_06()
            return MODEL_06
        case "1.7B":
            decision = system_probe.decide_model_17()
            if not decision.allowed:
                raise ModelDisabled(decision.reason)
            return MODEL_17
        case unreachable:
            assert_never(unreachable)


def is_model_loaded() -> bool:
    return _MODEL is not None


def is_busy() -> bool:
    """지금 다른 생성이 진행 중인지."""
    return _LOCK.locked()


def loaded_model_id() -> str | None:
    return _MODEL_ID if _MODEL is not None else None


def unload_model() -> None:
    global _MODEL, _MODEL_ID
    _MODEL = None
    _MODEL_ID = None
    gc.collect()
    mx.clear_cache()


def _configure_memory() -> None:
    mx.set_memory_limit(MEMORY_LIMIT_BYTES)
    mx.set_cache_limit(CACHE_LIMIT_BYTES)


def _get_model(model_id: str):
    global _MODEL, _MODEL_ID
    if _MODEL is not None and _MODEL_ID == model_id:
        return _MODEL, 0.0
    if _MODEL is not None:
        unload_model()
    _configure_memory()
    print(f"모델 준비: {model_id}", flush=True)
    print(
        "캐시에 없으면 Hugging Face에서 받습니다. 용량과 진행 막대는 이 터미널에 표시됩니다.",
        flush=True,
    )
    print(f"캐시 디렉터리: {local_env.HF_HUB_CACHE}", flush=True)
    started = time.perf_counter()
    model = load(model_id)
    load_sec = time.perf_counter() - started
    kind = getattr(model.config, "tts_model_type", None)
    if kind != "base":
        unload_model()
        raise RuntimeError(f"Base 모델이 아닙니다. tts_model_type={kind}. 합성을 중단했습니다.")
    languages = [str(item).lower() for item in model.get_supported_languages()]
    if "korean" not in languages:
        unload_model()
        raise RuntimeError(
            "이 모델 언어 목록에 korean이 없습니다. "
            f"실제 목록: {model.get_supported_languages()}"
        )
    _MODEL = model
    _MODEL_ID = model_id
    return model, load_sec


def _wav_duration(path: Path) -> tuple[float, int, int]:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
    if rate <= 0:
        raise RuntimeError(f"샘플레이트가 0입니다: {path}")
    return frames / float(rate), rate, frames


def _write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(np.nan_to_num(audio.astype(np.float32)), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())


def _safe_token(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned[:48] or "item"


def _clip_token(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", value).strip("-.")
    return cleaned[:24] or "목소리"


def _unused_output(filename: str) -> Path:
    path = local_env.OUTPUTS / filename
    if not path.exists():
        return path
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for number in range(2, 1000):
        candidate = local_env.OUTPUTS / f"{stem}-{number}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("같은 이름의 결과 파일을 피하지 못했습니다.")


def synthesize(
    *,
    model_choice: ModelChoice,
    ref_wav: Path,
    ref_text: str,
    text: str,
    sentence_id: str,
    on_phase: Callable[[str], None] | None = None,
    clip_label: str | None = None,
    output_path: Path | None = None,
    seed: int | None = None,
    wait_sec: float | None = None,
) -> SynthesisReport:
    """참조 녹음 하나와 그 대본으로 text 를 읽은 WAV 를 만든다.

    다른 생성이 진행 중이면 wait_sec 동안 기다린다(None 이면 끝날 때까지).
    output_path 를 주면 그 위치에 쓰고, 없으면 outputs/ 에 새 이름으로 쓴다.
    """
    def phase(name: str) -> None:
        if on_phase is not None:
            on_phase(name)
    acquired = _LOCK.acquire(timeout=-1 if wait_sec is None else max(0.0, wait_sec))
    if not acquired:
        raise RuntimeError("이미 다른 생성이 진행 중입니다. 끝난 뒤에 다시 누르세요.")
    try:
        model_id = assert_model_allowed(model_choice)
        if not ref_wav.is_file():
            raise RuntimeError(f"참조 WAV가 없습니다: {ref_wav}")
        cleaned_ref = ref_text.strip()
        cleaned_text = text.strip()
        if not cleaned_ref:
            raise RuntimeError("원본 대본이 비어 있습니다.")
        if not cleaned_text:
            raise RuntimeError("생성할 문장이 비어 있습니다.")
        phase("loading")
        try:
            model, load_sec = _get_model(model_id)
            phase("generating")
            ref_duration, _ref_rate, _ref_frames = _wav_duration(ref_wav)
            mx.reset_peak_memory()
            if seed is not None:
                mx.random.seed(int(seed))
            started = time.perf_counter()
            # Base 복제: ref_audio + ref_text만 전달한다. voice, instruct는 넘기지 않는다.
            # 설치된 mlx-audio 0.6.1 Model.generate 시그니처에 맞춘 호출이다.
            results = list(
                model.generate(
                    text=cleaned_text,
                    ref_audio=str(ref_wav),
                    ref_text=cleaned_ref,
                    lang_code="korean",
                    stream=False,
                    verbose=True,
                )
            )
            generate_sec = time.perf_counter() - started
            peak_bytes = int(mx.get_peak_memory())
            active_bytes = int(mx.get_active_memory())
        except Exception:
            unload_model()
            raise
        finals = [item for item in results if not item.is_streaming_chunk]
        if not finals:
            finals = [item for item in results if item.is_final_chunk]
        if not finals:
            raise RuntimeError("모델이 오디오를 반환하지 않았습니다.")
        pieces: list[np.ndarray] = []
        sample_rate: int | None = None
        library_proc = 0.0
        library_rtf: float | None = None
        library_peak: float | None = None
        for item in finals:
            piece = np.asarray(item.audio, dtype=np.float32).reshape(-1)
            pieces.append(piece)
            sample_rate = int(item.sample_rate)
            library_proc += float(item.processing_time_seconds)
            library_rtf = float(item.real_time_factor)
            library_peak = float(item.peak_memory_usage)
        if sample_rate is None or not pieces:
            raise RuntimeError("모델 출력 샘플레이트를 읽지 못했습니다.")
        audio = np.concatenate(pieces)
        if audio.size == 0:
            raise RuntimeError("모델 출력 샘플이 0개입니다.")
        if output_path is None:
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
            if clip_label:
                filename = f"{_clip_token(clip_label)}_{stamp}.wav"
            else:
                tag = "0.6B-Base-8bit" if model_choice == "0.6B" else "1.7B-Base-8bit"
                filename = f"{tag}_{_safe_token(sentence_id)}_{stamp}.wav"
            output_path = _unused_output(filename)
        output_path = Path(output_path)
        _write_wav(output_path, audio, sample_rate)
        output_duration, written_rate, output_samples = _wav_duration(output_path)
        if written_rate != sample_rate:
            raise RuntimeError("저장한 WAV의 샘플레이트가 모델 출력과 다릅니다.")
        mx.clear_cache()
        return SynthesisReport(
            model_id=model_id,
            model_choice=model_choice,
            sentence_id=sentence_id,
            output_path=output_path.resolve(),
            ref_duration_sec=ref_duration,
            output_duration_sec=output_duration,
            load_sec=load_sec,
            generate_sec=generate_sec,
            sample_rate=sample_rate,
            output_samples=output_samples,
            library_processing_time_sec=library_proc,
            library_real_time_factor=library_rtf,
            library_peak_memory_gb=library_peak,
            mlx_peak_bytes=peak_bytes,
            mlx_active_bytes=active_bytes,
        )
    finally:
        _LOCK.release()
