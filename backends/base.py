"""TTS 엔진(백엔드) 공통 인터페이스.

엔진 하나 = 모델 하나 + 실행 방식(MLX·PyTorch 등). 참조 녹음과 대본은 엔진과 상관없이 같다.
새 엔진을 붙이려면 Backend 를 상속해 info·check·load·generate 를 채우고 backends/__init__.py 에 등록한다.
"""

from __future__ import annotations

import importlib.util
import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class BackendInfo:
    id: str  # API·명령줄에서 쓰는 이름. 예: qwen3-mlx  (= 모델 계열 + 실행 방식)
    family: str  # 모델 계열. 예: qwen3, chatterbox
    runtime: str  # 실행 방식. mlx(맥) 또는 torch(CUDA·CPU·MPS)
    label: str  # 화면 이름
    model_id: str  # Hugging Face 저장소 등
    developer: str
    origin: str  # 개발 주체 국가(공공 도입 검토용)
    license: str  # 가중치 라이선스
    commercial_use: bool  # 상업·공공 이용 가능 여부(라이선스 기준)
    platforms: tuple[str, ...]  # mac-arm64, windows, linux
    needs_ref_text: bool  # 참조 녹음의 대본이 필요한지
    approx_download_gb: float
    homepage: str
    notes: str = ""
    languages: tuple[str, ...] = ("ko",)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GenerationOutput:
    audio: np.ndarray  # float32 모노, -1..1
    sample_rate: int
    stats: dict[str, Any] = field(default_factory=dict)  # 엔진별 측정값(피크 메모리 등)


class BackendUnavailable(RuntimeError):
    """이 컴퓨터에서 쓸 수 없는 엔진(패키지 없음·OS 미지원 등)."""


def current_platform() -> str:
    system = platform.system()
    if system == "Darwin":
        return "mac-arm64" if platform.machine() == "arm64" else "mac-intel"
    if system == "Windows":
        return "windows"
    return "linux"


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class Backend:
    info: BackendInfo

    def check(self) -> tuple[bool, str]:
        """(쓸 수 있는지, 이유). 무거운 import 없이 빠르게 답한다."""
        raise NotImplementedError

    def load(self) -> None:
        raise NotImplementedError

    def unload(self) -> None:
        pass

    def device(self) -> str:
        return "cpu"

    def generate(
        self,
        *,
        text: str,
        ref_wav: Path,
        ref_text: str,
        seed: int | None = None,
        language: str = "ko",
    ) -> GenerationOutput:
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        ok, reason = self.check()
        data = self.info.to_dict()
        data.update({"available": ok, "reason": reason})
        return data
