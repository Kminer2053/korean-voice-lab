"""Qwen3-TTS 0.6B Base, PyTorch(공식 qwen-tts 패키지) — Windows·Linux(CUDA 또는 CPU)."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np

from .base import Backend, BackendInfo, BackendUnavailable, GenerationOutput, has_module
from .chatterbox_torch import pick_torch_device


class Qwen3Torch(Backend):
    info = BackendInfo(
        id="qwen3-torch",
        family="qwen3",
        runtime="torch",
        label="Qwen3-TTS 0.6B · PyTorch",
        model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        developer="Alibaba Qwen 팀",
        origin="중국",
        license="Apache-2.0",
        commercial_use=True,
        platforms=("windows", "linux"),
        needs_ref_text=True,
        approx_download_gb=2.5,
        homepage="https://github.com/QwenLM/Qwen3-TTS",
        notes="공식 PyTorch 구현. NVIDIA GPU에서 bfloat16, CPU에서는 float32로 돈다. 맥에서는 qwen3-mlx가 더 빠르다.",
    )

    def __init__(self) -> None:
        self._model = None
        self._device = "cpu"

    def check(self) -> tuple[bool, str]:
        if not (has_module("torch") and has_module("qwen_tts")):
            return False, "torch·qwen-tts 패키지가 없습니다(requirements/engine-qwen3.txt)."
        return True, "사용 가능"

    def device(self) -> str:
        return self._device

    def load(self) -> None:
        ok, reason = self.check()
        if not ok:
            raise BackendUnavailable(reason)
        import torch
        from qwen_tts import Qwen3TTSModel

        self._device = pick_torch_device()
        kwargs = {"device_map": "cuda:0" if self._device == "cuda" else self._device}
        kwargs["dtype"] = torch.bfloat16 if self._device == "cuda" else torch.float32
        if self._device == "cuda" and has_module("flash_attn"):
            kwargs["attn_implementation"] = "flash_attention_2"
        self._model = Qwen3TTSModel.from_pretrained(self.info.model_id, **kwargs)

    def unload(self) -> None:
        self._model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def generate(self, *, text, ref_wav: Path, ref_text, seed=None, language="ko") -> GenerationOutput:
        import torch

        if self._model is None:
            self.load()
        if seed is not None:
            torch.manual_seed(int(seed))
        wavs, sample_rate = self._model.generate_voice_clone(
            text=text,
            language="Korean",
            ref_audio=str(ref_wav),
            ref_text=ref_text,
        )
        audio = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
        stats = {}
        if self._device == "cuda":
            stats["peak_memory_bytes"] = int(torch.cuda.max_memory_allocated())
        return GenerationOutput(audio, int(sample_rate), stats)
