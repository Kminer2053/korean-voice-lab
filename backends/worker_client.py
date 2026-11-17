"""다른 가상환경의 엔진을 작업 프로세스로 띄워 쓰는 쪽."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

from .base import Backend, BackendInfo, BackendUnavailable, GenerationOutput

ROOT = Path(__file__).resolve().parent.parent


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))
    env.setdefault("HF_HUB_CACHE", str(ROOT / ".cache" / "huggingface" / "hub"))
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    env.setdefault("DO_NOT_TRACK", "1")
    return env


def probe(engine_id: str, python: Path, timeout: float = 120) -> tuple[bool, str]:
    """작업 프로세스 쪽 파이썬에서 엔진이 쓸 수 있는지 한 번 묻는다."""
    code = (
        "import sys, json; sys.path.insert(0, sys.argv[1]);"
        "from backends import REGISTRY; import importlib;"
        "m, c = REGISTRY[sys.argv[2]].split(':');"
        "ok, why = getattr(importlib.import_module(m), c)().check();"
        "print(json.dumps({'ok': ok, 'why': why}, ensure_ascii=False))"
    )
    try:
        done = subprocess.run(
            [str(python), "-c", code, str(ROOT), engine_id],
            capture_output=True, text=True, timeout=timeout, env=_env(), encoding="utf-8",
        )
        data = json.loads(done.stdout.strip().splitlines()[-1])
        return bool(data["ok"]), f"{data['why']} (작업 프로세스: {python})"
    except Exception as exc:
        return False, f"작업 프로세스 점검 실패({python}): {exc}"


class WorkerBackend(Backend):
    def __init__(self, info: BackendInfo, python: Path) -> None:
        self.info = info
        self.python = python
        self._proc: subprocess.Popen | None = None
        self._device = "?"
        self._lock = threading.Lock()

    def check(self) -> tuple[bool, str]:
        return probe(self.info.id, self.python)

    def device(self) -> str:
        return self._device

    def _ask(self, req: dict, timeout_note: str = "") -> dict:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                [str(self.python), "-m", "backends.worker", self.info.id],
                cwd=str(ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,  # 진행 막대·경고는 서버 터미널에 그대로 보인다
                text=True,
                encoding="utf-8",
                env=_env(),
            )
        assert self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            code = self._proc.poll()
            self._proc = None
            raise RuntimeError(f"{self.info.label} 작업 프로세스가 끝났습니다(코드 {code}). 서버 터미널의 오류를 보세요.")
        data = json.loads(line)
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "작업 프로세스 오류")
        return data

    def load(self) -> None:
        with self._lock:
            data = self._ask({"cmd": "load"})
            self._device = str(data.get("device") or "?")

    def unload(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    def generate(self, *, text, ref_wav: Path, ref_text, seed=None, language="ko") -> GenerationOutput:
        with tempfile.TemporaryDirectory(prefix="voicelab-worker-") as tmp:
            out_path = Path(tmp) / "out.wav"
            with self._lock:
                data = self._ask(
                    {
                        "cmd": "generate",
                        "text": text,
                        "ref_wav": str(ref_wav),
                        "ref_text": ref_text,
                        "seed": seed,
                        "language": language,
                        "out_path": str(out_path),
                    }
                )
            with wave.open(str(out_path), "rb") as handle:
                raw = handle.readframes(handle.getnframes())
                rate = handle.getframerate()
        audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        return GenerationOutput(audio, rate, dict(data.get("stats") or {}))


__all__ = ["WorkerBackend", "probe", "BackendUnavailable", "sys"]
