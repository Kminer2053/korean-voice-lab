"""Chatterbox Multilingual v3 (Resemble AI), PyTorch — Windows·Linux(CUDA 또는 CPU), 맥(MPS)."""

from __future__ import annotations

import gc
import inspect
import sys
from pathlib import Path

import numpy as np

from .base import Backend, BackendInfo, BackendUnavailable, GenerationOutput, has_module

EXAGGERATION = 0.5
CFG_WEIGHT = 0.5


def pick_torch_device() -> str:
    """CUDA → MPS(맥) → CPU. 문자열로 돌려준다(Windows CPU에서 torch.device 객체를 넘기면 실패하는 문제 회피).

    VOICELAB_TORCH_DEVICE=cpu|cuda|mps 로 강제할 수 있다(시험·문제 해결용).
    """
    import os

    import torch

    forced = os.environ.get("VOICELAB_TORCH_DEVICE", "").strip().lower()
    if forced in ("cpu", "cuda", "mps"):
        return forced

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
        self._variant = ""

    def check(self) -> tuple[bool, str]:
        if not (has_module("torch") and has_module("chatterbox")):
            return False, "torch·chatterbox-tts 패키지가 없습니다(requirements/engine-chatterbox.txt, engine-chatterbox-src.txt)."
        return True, "사용 가능"

    def device(self) -> str:
        return self._device + self._variant

    def load(self) -> None:
        ok, reason = self.check()
        if not ok:
            raise BackendUnavailable(reason)
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        self._device = pick_torch_device()
        # v3 가중치는 GitHub 판 chatterbox-tts(engine-chatterbox-src.txt)에서만 고를 수 있다.
        # PyPI 0.1.7 이 깔려 있으면 v2 로 돌리고 그 사실을 장치 이름에 남긴다.
        if "t3_model" in inspect.signature(ChatterboxMultilingualTTS.from_pretrained).parameters:
            self._model = ChatterboxMultilingualTTS.from_pretrained(device=self._device, t3_model="v3")
            self._variant = ""
        else:
            print("chatterbox-tts 가 다국어 v3 를 지원하지 않는 판이라 v2 로 돌립니다. "
                  "requirements/engine-chatterbox-src.txt 를 설치하면 v3 를 씁니다.", file=sys.stderr)
            self._model = ChatterboxMultilingualTTS.from_pretrained(device=self._device)
            self._variant = " (v2)"

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
