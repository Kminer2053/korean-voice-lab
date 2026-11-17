"""Qwen3-TTS 0.6B Base 8-bit, MLX(Apple Silicon 전용)."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np

from .base import Backend, BackendInfo, BackendUnavailable, GenerationOutput, current_platform, has_module

GIB = 1024**3
# 16GiB 통합 메모리에서 모델(약 2.8GiB)이 들어가고 OS 여유가 남도록 제한한다.
MEMORY_LIMIT_BYTES = 8 * GIB
CACHE_LIMIT_BYTES = 2 * GIB


class Qwen3MLX(Backend):
    info = BackendInfo(
        id="qwen3-mlx",
        family="qwen3",
        runtime="mlx",
        label="Qwen3-TTS 0.6B · MLX",
        model_id="mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
        developer="Alibaba Qwen 팀 (MLX 변환: mlx-community)",
        origin="중국",
        license="Apache-2.0",
        commercial_use=True,
        platforms=("mac-arm64",),
        needs_ref_text=True,
        approx_download_gb=3.0,
        homepage="https://github.com/QwenLM/Qwen3-TTS",
        notes="Apple Silicon에서 가장 빠름. 참조 녹음의 대본을 함께 넣어 복제한다.",
    )

    def __init__(self) -> None:
        self._model = None

    def check(self) -> tuple[bool, str]:
        if current_platform() != "mac-arm64":
            return False, "Apple Silicon Mac에서만 돕니다."
        if not (has_module("mlx") and has_module("mlx_audio")):
            return False, "mlx·mlx-audio 패키지가 없습니다(requirements/mac-mlx.txt)."
        return True, "사용 가능"

    def device(self) -> str:
        return "mlx-metal"

    def load(self) -> None:
        ok, reason = self.check()
        if not ok:
            raise BackendUnavailable(reason)
        import mlx.core as mx
        from mlx_audio.tts.utils import load

        mx.set_memory_limit(MEMORY_LIMIT_BYTES)
        mx.set_cache_limit(CACHE_LIMIT_BYTES)
        model = load(self.info.model_id)
        kind = getattr(model.config, "tts_model_type", None)
        if kind != "base":
            raise RuntimeError(f"Base 모델이 아닙니다. tts_model_type={kind}.")
        languages = [str(item).lower() for item in model.get_supported_languages()]
        if "korean" not in languages:
            raise RuntimeError(f"이 모델 언어 목록에 korean이 없습니다: {languages}")
        self._model = model

    def unload(self) -> None:
        self._model = None
        gc.collect()
        try:
            import mlx.core as mx

            mx.clear_cache()
        except ImportError:
            pass

    def generate(self, *, text, ref_wav: Path, ref_text, seed=None, language="ko") -> GenerationOutput:
        import mlx.core as mx

        if self._model is None:
            self.load()
        mx.reset_peak_memory()
        if seed is not None:
            mx.random.seed(int(seed))
        # Base 복제: ref_audio + ref_text 만 넘긴다. voice·instruct 는 넘기지 않는다.
        results = list(
            self._model.generate(
                text=text,
                ref_audio=str(ref_wav),
                ref_text=ref_text,
                lang_code="korean",
                stream=False,
                verbose=False,
            )
        )
        finals = [item for item in results if not item.is_streaming_chunk] or [
            item for item in results if item.is_final_chunk
        ]
        if not finals:
            raise RuntimeError("모델이 오디오를 반환하지 않았습니다.")
        pieces = [np.asarray(item.audio, dtype=np.float32).reshape(-1) for item in finals]
        if len(pieces) > 1:  # 줄마다 따로 만든 조각 사이에 쉼을 둔다(끝은 engine 이 맞춘다)
            from audio_prep import ensure_tail_silence

            rate = int(finals[-1].sample_rate)
            pieces = [ensure_tail_silence(p, rate, 0.3) for p in pieces[:-1]] + pieces[-1:]
        stats = {"peak_memory_bytes": int(mx.get_peak_memory())}
        mx.clear_cache()
        return GenerationOutput(np.concatenate(pieces), int(finals[-1].sample_rate), stats)
