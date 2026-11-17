#!/usr/bin/env python3
"""켜져 있는 서버를 점검한다. 표준 라이브러리만 쓴다.

  python3 selftest.py                 # 생성 없이 상태·말투·오류 응답·루프백 바인딩만
  python3 selftest.py --generate      # 문장 하나와 일괄 2개를 실제로 만들어 본다
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave
from pathlib import Path

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
FAILED: list[str] = []


def call(method: str, url: str, body: dict | None = None, timeout: float = 600):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read()


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}{' · ' + detail if detail else ''}", flush=True)
    if not ok:
        FAILED.append(label)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:7860")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    port = int(base.rsplit(":", 1)[-1])

    try:
        status, _ct, raw = call("GET", base + "/api/health", timeout=5)
    except (urllib.error.URLError, OSError) as exc:
        print(f"FAIL 서버 연결 · {base} 에 연결하지 못했습니다({exc}). start.command 또는 'python app.py'로 먼저 켜세요.")
        return 2
    health = json.loads(raw) if status == 200 else {}
    check("상태 /api/health", status == 200 and health.get("ok") is True, f"api_version={health.get('api_version')}")
    ready = [s["id"] for s in health.get("styles", []) if s.get("ready")]
    check("등록된 말투", bool(ready), ", ".join(ready) or "없음 — 화면의 목소리 등록 탭에서 녹음하세요")

    status, _ct, raw = call("GET", base + "/config", timeout=5)
    check("Gradio /config (gradio_client 호환)", status == 200)

    status, _ct, raw = call("POST", base + "/api/tts", {"text": "", "style": "default"})
    check("빈 문장은 400", status == 400, json.loads(raw).get("error", "") if raw else "")
    status, _ct, raw = call("POST", base + "/api/tts", {"text": "가", "style": "no-such-style"})
    check("없는 말투는 400", status == 400)

    try:
        out = subprocess.run(["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        lines = [line for line in out.splitlines() if "LISTEN" in line]
        check("127.0.0.1 에만 열림", bool(lines) and all("127.0.0.1:" in line for line in lines))
    except FileNotFoundError:
        print("SKIP lsof 없음", flush=True)

    if args.generate and ready:
        style = "talk" if "talk" in ready else ready[0]
        status, ctype, raw = call("POST", base + "/api/tts", {"text": "점검용 문장입니다.", "style": style})
        check("문장 하나 → WAV", status == 200 and ctype.startswith("audio/wav") and raw[:4] == b"RIFF", f"{len(raw)} bytes")
        with tempfile.TemporaryDirectory() as tmp:
            status, _ct, raw = call(
                "POST", base + "/api/batch",
                {"style": style, "out_dir": tmp, "items": ["첫 번째 점검 문장입니다.", {"id": "two", "text": "두 번째 점검 문장입니다."}]},
            )
            summary = json.loads(raw) if status == 200 else {}
            files = sorted(p.name for p in Path(tmp).glob("*.wav"))
            check("일괄 2개 → WAV 2개 + manifest", summary.get("succeeded") == 2 and len(files) == 2 and (Path(tmp) / "manifest.json").is_file(), ", ".join(files))
            for path in Path(tmp).glob("*.wav"):
                with wave.open(str(path)) as handle:
                    seconds = handle.getnframes() / handle.getframerate()
                check(f"{path.name} 길이", seconds > 0.3, f"{seconds:.2f}초")

    print("\n결과:", "모두 통과" if not FAILED else f"실패 {len(FAILED)}개 — {', '.join(FAILED)}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
