"""엔진 목록과 선택.

엔진은 두 가지 방식으로 돈다.
- 같은 프로세스: 서버를 띄운 파이썬에 그 엔진 패키지가 있을 때.
- 작업 프로세스: 엔진 패키지가 다른 가상환경에 있을 때(예: 맥에서 MLX 환경과 PyTorch 환경을 나눔).
  settings.json 의 engine_python, .venv-<모델 계열>(예: .venv-chatterbox), .venv-torch 순서로 찾아
  그 파이썬으로 backends.worker 를 띄운다. 엔진마다 의존성 버전이 달라(transformers 등) 가상환경을 나눈다.

기본 엔진 순서: 환경변수 VOICELAB_ENGINE → settings.json 의 default_engine → 쓸 수 있는 첫 엔진(PREFERENCE).
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .base import Backend, BackendInfo, BackendUnavailable, GenerationOutput, current_platform

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "settings.json"

# id → "모듈:클래스". 모듈은 import 할 때 무거운 패키지를 불러오지 않아야 한다.
# id 는 "모델 계열-실행 방식". 같은 계열 안에서는 위에 있는 실행 방식이 더 빠르다(맥: MLX, 그 밖: PyTorch CUDA·CPU).
REGISTRY: dict[str, str] = {
    "qwen3-mlx": "backends.qwen3_mlx:Qwen3MLX",
    "qwen3-torch": "backends.qwen3_torch:Qwen3Torch",
    "chatterbox-mlx": "backends.chatterbox_mlx:ChatterboxMLX",
    "chatterbox-torch": "backends.chatterbox_torch:ChatterboxTorch",
}
# 기본 엔진을 고를 때의 순서. 맥은 MLX 를 먼저, 그 밖에서는 출처·라이선스 부담이 적은 Chatterbox 를 먼저 쓴다.
PREFERENCE = ("qwen3-mlx", "chatterbox-mlx", "chatterbox-torch", "qwen3-torch")
_INSTANCES: dict[str, Backend] = {}


def load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    data = load_settings()
    data.update(updates)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def _class_for(engine_id: str):
    target = REGISTRY.get(engine_id)
    if target is None:
        known = ", ".join(REGISTRY)
        raise BackendUnavailable(f"엔진 '{engine_id}'를 모릅니다. 쓸 수 있는 엔진: {known}")
    module_name, class_name = target.split(":")
    return getattr(importlib.import_module(module_name), class_name)


def info(engine_id: str) -> BackendInfo:
    return _class_for(engine_id).info


def families() -> list[str]:
    seen: list[str] = []
    for engine_id in REGISTRY:
        family = info(engine_id).family
        if family not in seen:
            seen.append(family)
    return seen


def family_members(family: str) -> list[str]:
    """그 모델 계열의 엔진 id. 빠른 실행 방식(REGISTRY 순서)부터."""
    return [engine_id for engine_id in REGISTRY if info(engine_id).family == family]


def _venv_python(folder: Path) -> Path:
    if os.name == "nt":
        return folder / "Scripts" / "python.exe"
    return folder / "bin" / "python"


def engine_python(engine_id: str) -> Path | None:
    """이 엔진을 작업 프로세스로 돌릴 파이썬. 없으면 None.

    찾는 순서: settings.json 의 engine_python[id] → .venv-<모델 계열>(예: .venv-chatterbox) → .venv-torch
    """
    configured = (load_settings().get("engine_python") or {}).get(engine_id)
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = ROOT / path
        return path if path.exists() else None
    meta = info(engine_id)
    if meta.runtime != "torch":
        return None
    here = Path(sys.executable).resolve()
    for folder in (ROOT / f".venv-{meta.family}", ROOT / ".venv-torch"):
        candidate = _venv_python(folder)
        if candidate.exists() and candidate.resolve() != here:
            return candidate
    return None


def get(engine_id: str) -> Backend:
    """쓸 수 있는 엔진 객체. 같은 프로세스에서 안 되면 작업 프로세스로 감싼다."""
    if engine_id in _INSTANCES:
        return _INSTANCES[engine_id]
    cls = _class_for(engine_id)
    local = cls()
    ok, reason = local.check()
    if ok:
        backend: Backend = local
    else:
        python = engine_python(engine_id)
        if python is None:
            raise BackendUnavailable(f"{cls.info.label}: {reason}")
        from .worker_client import WorkerBackend

        backend = WorkerBackend(cls.info, python)
    _INSTANCES[engine_id] = backend
    return backend


def status(engine_id: str) -> dict[str, Any]:
    cls = _class_for(engine_id)
    data = cls.info.to_dict()
    local_ok, local_reason = cls().check()
    if local_ok:
        data.update({"available": True, "reason": "사용 가능", "runs_in": "server"})
        return data
    python = engine_python(engine_id)
    if python is not None:
        from .worker_client import probe

        ok, reason = probe(engine_id, python)
        data.update({"available": ok, "reason": reason, "runs_in": f"worker:{python}"})
        return data
    data.update({"available": False, "reason": local_reason, "runs_in": None})
    return data


_STATUS_CACHE: dict[str, dict[str, Any]] = {}


def all_status(refresh: bool = False) -> list[dict[str, Any]]:
    if refresh:
        _STATUS_CACHE.clear()
    result = []
    for engine_id in REGISTRY:
        if engine_id not in _STATUS_CACHE:
            try:
                _STATUS_CACHE[engine_id] = status(engine_id)
            except Exception as exc:  # 상태 조회가 서버를 멈추게 하지 않는다.
                data = info(engine_id).to_dict()
                data.update({"available": False, "reason": f"{type(exc).__name__}: {exc}", "runs_in": None})
                _STATUS_CACHE[engine_id] = data
        result.append(_STATUS_CACHE[engine_id])
    return result


def available_ids() -> list[str]:
    return [item["id"] for item in all_status() if item["available"]]


def default_engine_id() -> str | None:
    wanted = os.environ.get("VOICELAB_ENGINE") or load_settings().get("default_engine")
    ready = available_ids()
    if wanted and wanted in ready:
        return wanted
    for engine_id in PREFERENCE:
        if engine_id in ready:
            return engine_id
    return None


__all__ = [
    "Backend",
    "BackendInfo",
    "BackendUnavailable",
    "GenerationOutput",
    "REGISTRY",
    "all_status",
    "available_ids",
    "current_platform",
    "default_engine_id",
    "families",
    "family_members",
    "get",
    "info",
    "load_settings",
    "save_settings",
]
