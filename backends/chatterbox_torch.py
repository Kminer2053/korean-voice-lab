"""Chatterbox Multilingual v3 (Resemble AI), PyTorch — Windows·Linux(CUDA 또는 CPU), 맥(MPS)."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np

from .base import Backend, BackendInfo, BackendUnavailable, GenerationOutput, has_module

EXAGGERATION = 0.5
CFG_WEIGHT = 0.5


def pick_torch_device() -> str:
    """CUDA → MPS(맥) → CPU. 문자열로 돌려준다(Windows CPU에서 torch.device 객체를 넘기면 실패하는 문제 회피)."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class ChatterboxTorch(Backend):
    info = BackendInfo(
        id="chatterbox-torch",
        family="chatterbox",
        runtime="torch",
        label="Chatterbox 다국어 v3 · PyTorch",
        model_id="ResembleAI/chatterbox (t3 v3)",
        developer="Resemble AI",
        origin="미국",
        license="MIT",
        commercial_use=True,
        platforms=("windows", "linux", "mac-arm64"),
        needs_ref_text=False,
        reads_digits=False,  # 숫자를 엉뚱하게 읽어(벤치마크 CER 0.4) 한국어 소리로 바꿔 넘긴다
        approx_download_gb=3.2,
        homepage="https://github.com/resemble-ai/chatterbox",
        notes="23개 언어 제로샷 복제. NVIDIA GPU(CUDA)에서 빠르고 CPU에서도 돈다. 출력에 Perth 워터마크가 들어간다.",
    )

    def __init__(self) -> None:
        self._model = None
        self._device = "cpu"

    def check(self) -> tuple[bool, str]:
        if not (has_module("torch") and has_module("chatterbox")):
            return False, "torch·chatterbox-tts 패키지가 없습니다(requirements-torch.txt)."
        return True, "사용 가능"

    def device(self) -> str:
        return self._device

    def load(self) -> None:
        ok, reason = self.check()
        if not ok:
            raise BackendUnavailable(reason)
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        self._device = pick_torch_device()
        self._model = ChatterboxMultilingualTTS.from_pretrained(device=self._device, t3_model="v3")

    def unload(self) -> None:
        self._model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def generate(self, *, text, ref_wav: Path, ref_text="", seed=None, language="ko") -> GenerationOutput:
        import torch

        if self._model is None:
            self.load()
        if seed is not None:
            torch.manual_seed(int(seed))
        with torch.inference_mode():
            wav = self._model.generate(
                text,
                language_id=language,
                audio_prompt_path=str(ref_wav),
                exaggeration=EXAGGERATION,
                cfg_weight=CFG_WEIGHT,
            )
        audio = wav.detach().float().cpu().numpy().reshape(-1)
        stats = {}
        if self._device == "cuda":
            stats["peak_memory_bytes"] = int(torch.cuda.max_memory_allocated())
        return GenerationOutput(np.asarray(audio, dtype=np.float32), int(self._model.sr), stats)
