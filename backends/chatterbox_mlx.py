"""Chatterbox Multilingual v3 (Resemble AI), MLX(Apple Silicon 전용)."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np

from .base import Backend, BackendInfo, BackendUnavailable, GenerationOutput, current_platform, has_module
from .qwen3_mlx import CACHE_LIMIT_BYTES, MEMORY_LIMIT_BYTES

# 감정 과장 정도와 CFG. 원본 기본값(0.5/0.5)이 한국어 낭독에서 무난하다.
EXAGGERATION = 0.5
CFG_WEIGHT = 0.5


class ChatterboxMLX(Backend):
    info = BackendInfo(
        id="chatterbox-mlx",
        family="chatterbox",
        runtime="mlx",
        label="Chatterbox 다국어 v3 · MLX",
        model_id="mlx-community/chatterbox-multilingual-v3",
        developer="Resemble AI (MLX 변환: mlx-community)",
        origin="미국",
        license="MIT",
        commercial_use=True,
        platforms=("mac-arm64",),
        needs_ref_text=False,
        approx_download_gb=2.7,
        homepage="https://github.com/resemble-ai/chatterbox",
        notes="23개 언어 제로샷 복제. 참조 녹음만 쓰고 대본은 쓰지 않는다. 출력에 Perth 워터마크가 없는 MLX 변환본.",
    )

    def __init__(self) -> None:
        self._model = None

    def check(self) -> tuple[bool, str]:
        if current_platform() != "mac-arm64":
            return False, "Apple Silicon Mac에서만 돕니다."
        if not (has_module("mlx") and has_module("mlx_audio")):
            return False, "mlx·mlx-audio 패키지가 없습니다(requirements-mac.txt)."
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
        self._model = load(self.info.model_id)

    def unload(self) -> None:
        self._model = None
        gc.collect()
        try:
            import mlx.core as mx

            mx.clear_cache()
        except ImportError:
            pass

    def generate(self, *, text, ref_wav: Path, ref_text="", seed=None, language="ko") -> GenerationOutput:
        import mlx.core as mx

        if self._model is None:
            self.load()
        mx.reset_peak_memory()
        if seed is not None:
            mx.random.seed(int(seed))
        results = list(
            self._model.generate(
                text=text,
                ref_audio=str(ref_wav),
                lang_code=language,
                exaggeration=EXAGGERATION,
                cfg_weight=CFG_WEIGHT,
                verbose=False,
            )
        )
        finals = [item for item in results if not getattr(item, "is_streaming_chunk", False)] or results
        if not finals:
            raise RuntimeError("모델이 오디오를 반환하지 않았습니다.")
        pieces = [np.asarray(item.audio, dtype=np.float32).reshape(-1) for item in finals]
        stats = {"peak_memory_bytes": int(mx.get_peak_memory())}
        mx.clear_cache()
        return GenerationOutput(np.concatenate(pieces), int(finals[-1].sample_rate), stats)
