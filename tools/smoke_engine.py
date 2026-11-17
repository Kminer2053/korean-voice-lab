#!/usr/bin/env python3
"""엔진 하나로 짧은 한국어 문장을 실제로 만들어 본다(서버 없이). CI·설치 직후 점검용.

  .venv/bin/python tools/smoke_engine.py --engine chatterbox --style talk
  .venv/bin/python tools/smoke_engine.py --engine chatterbox-torch --ref ref.wav

--ref 를 주면 그 녹음을 참조로 쓴다(대본이 필요한 엔진이면 --ref-text 도). 결과는 JSON 한 줄.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import local_env  # noqa: E402,F401  (캐시 위치 환경변수)
import backends  # noqa: E402
import engine  # noqa: E402
import voices  # noqa: E402

TEXT = "안녕하세요. 설치가 잘 되었는지 확인하는 문장입니다."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--engine", default=None, help="모델(qwen3, chatterbox) 또는 엔진 id. 없으면 기본 엔진")
    parser.add_argument("--style", default="default")
    parser.add_argument("--ref", help="참조 녹음 WAV(등록된 말투 대신)")
    parser.add_argument("--ref-text", default="", help="--ref 의 대본(Qwen3 계열은 필수)")
    parser.add_argument("--text", default=TEXT)
    parser.add_argument("--out", default=str(ROOT / "outputs" / "smoke.wav"))
    args = parser.parse_args()

    print(json.dumps({"platform": backends.current_platform(),
                      "engines": [(e["id"], e["available"], e["runs_in"]) for e in backends.all_status()]},
                     ensure_ascii=False), file=sys.stderr)
    if args.ref:
        ref, ref_text = Path(args.ref).resolve(), args.ref_text
    else:
        style = voices.resolve(args.style)
        if style.path is None:
            print(json.dumps({"ok": False, "error": f"'{style.id}' 말투에 녹음이 없습니다. --ref 를 주세요."}, ensure_ascii=False))
            return 2
        ref, ref_text = style.path, style.script
    started = time.perf_counter()
    try:
        report = engine.synthesize(ref_wav=ref, ref_text=ref_text, text=args.text, engine=args.engine,
                                   output_path=Path(args.out))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    finally:
        engine.unload_model()
    with wave.open(str(report.output_path), "rb") as handle:
        audio = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0
    ok = report.output_duration_sec > 0.8 and rms > 0.005
    print(json.dumps({
        "ok": ok,
        "engine": report.engine_id,
        "device": report.device,
        "path": str(report.output_path),
        "duration_sec": round(report.output_duration_sec, 2),
        "rms": round(rms, 4),
        "load_sec": round(report.load_sec, 1),
        "generate_sec": round(report.generate_sec, 2),
        "total_sec": round(time.perf_counter() - started, 1),
    }, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
