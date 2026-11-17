"""엔진 작업 프로세스. 다른 가상환경의 파이썬으로 실행된다.

  <venv>/python -m backends.worker <engine_id>

표준 입력으로 JSON 한 줄씩 받고, 표준 출력으로 JSON 한 줄씩 답한다.
라이브러리가 찍는 글은 표준 오류로 돌려 통신 줄을 더럽히지 않는다.
  {"cmd": "check"} → {"ok": true, "available": true, "reason": "..."}
  {"cmd": "load"}  → {"ok": true, "load_sec": 1.2, "device": "cuda"}
  {"cmd": "generate", "text", "ref_wav", "ref_text", "seed", "language", "out_path"}
                   → {"ok": true, "sample_rate": 24000, "samples": 12345, "stats": {...}}
  {"cmd": "quit"}
"""

from __future__ import annotations

import importlib
import json
import sys
import time
import traceback
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> int:
    clipped = np.clip(np.nan_to_num(np.asarray(audio, dtype=np.float32).reshape(-1)), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())
    return int(pcm.size)


def main() -> int:
    engine_id = sys.argv[1]
    protocol = sys.stdout
    sys.stdout = sys.stderr  # 라이브러리 출력은 표준 오류로

    from backends import REGISTRY

    module_name, class_name = REGISTRY[engine_id].split(":")
    backend = getattr(importlib.import_module(module_name), class_name)()

    def reply(data: dict) -> None:
        protocol.write(json.dumps(data, ensure_ascii=False) + "\n")
        protocol.flush()

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            cmd = req.get("cmd")
            if cmd == "check":
                ok, reason = backend.check()
                reply({"ok": True, "available": ok, "reason": reason})
            elif cmd == "load":
                started = time.perf_counter()
                backend.load()
                reply({"ok": True, "load_sec": time.perf_counter() - started, "device": backend.device()})
            elif cmd == "generate":
                out = backend.generate(
                    text=req["text"],
                    ref_wav=Path(req["ref_wav"]),
                    ref_text=req.get("ref_text") or "",
                    seed=req.get("seed"),
                    language=req.get("language") or "ko",
                )
                samples = _write_wav(Path(req["out_path"]), out.audio, out.sample_rate)
                reply({"ok": True, "sample_rate": out.sample_rate, "samples": samples, "stats": out.stats})
            elif cmd == "quit":
                reply({"ok": True})
                return 0
            else:
                reply({"ok": False, "error": f"모르는 명령: {cmd}"})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            reply({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
