#!/usr/bin/env python3
"""명령줄 도구. 문장 하나 또는 목록(JSON·TXT)을 WAV 로 만든다.

서버(기본 http://127.0.0.1:7860)가 켜져 있으면 서버에 보낸다. 모델을 두 번 올리지 않기 위해서다.
서버가 꺼져 있으면 이 프로세스에서 모델을 올려 직접 만든다(.venv 의 파이썬 필요).

예:
  .venv/bin/python voicelab_cli.py say "안녕하세요" -s talk -o hello.wav
  .venv/bin/python voicelab_cli.py batch lines.json -o out/ -s guide
  .venv/bin/python voicelab_cli.py batch script.txt -o out/      # 줄마다 한 문장
  .venv/bin/python voicelab_cli.py styles
결과는 표준 출력에 JSON 으로 나온다(--quiet 이면 JSON 만).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_SERVER = os.environ.get("VOICELAB_URL", "http://127.0.0.1:7860")
HERE = Path(__file__).resolve().parent


class CliError(Exception):
    pass


# ---------------------------------------------------------------- 서버 호출
def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 로컬 주소라 프록시를 거치지 않는다


def _http(method: str, url: str, body: dict | None = None, timeout: float = 3600) -> Any:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with _opener().open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error")
        except Exception:
            detail = str(exc)
        raise CliError(detail) from exc


def server_alive(base: str) -> bool:
    try:
        info = _http("GET", base.rstrip("/") + "/api/health", timeout=3)
        return bool(info.get("ok"))
    except (CliError, OSError, ValueError):
        return False


# ---------------------------------------------------------------- 입력 읽기
def read_items(path: str) -> Any:
    """JSON(목록 또는 {style, items}) 또는 TXT(줄마다 한 문장, # 주석 무시, 빈 줄은 문단 나눔)."""
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    stripped = raw.lstrip()
    if path.endswith(".json") or stripped.startswith(("[", "{")):
        return json.loads(raw)
    if path.endswith(".jsonl"):
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    items: list[dict[str, Any]] = []
    paragraph = 1
    for line in raw.splitlines():
        if not line.strip():
            if items and items[-1]["paragraph"] == paragraph:
                paragraph += 1  # 빈 줄 = 문단 경계(--timeline 에서 더 길게 쉰다)
            continue
        if line.lstrip().startswith("#"):
            continue
        items.append({"text": line.strip(), "paragraph": paragraph})
    return items


# ---------------------------------------------------------------- 명령
def _add_audio_options(p) -> None:
    p.add_argument("--loudness", type=float, help="통합 음량(LUFS)으로 맞춤. 예: -16(영상), -14(유튜브)")
    p.add_argument("--sample-rate", type=int, dest="sample_rate", help="저장 표본율. 예: 48000(영상 편집)")
    p.add_argument("--speed", type=float, help="말 빠르기(0.8–1.25, 음높이는 그대로). 예: 1.1 = 10%% 빠르게")


def cmd_say(args, base: str | None) -> dict:
    out = str(Path(args.output).expanduser().resolve()) if args.output else None
    if base:
        body = {"text": args.text, "style": args.style, "engine": args.engine, "format": "json", "seed": args.seed, "output_path": out,
                "loudness": args.loudness, "sample_rate": args.sample_rate, "speed": args.speed}
        if args.no_lexicon:
            body["use_lexicon"] = False
        return _http("POST", base + "/api/tts", body)
    import service

    result = service.synthesize(
        args.text, args.style, output_path=out, seed=args.seed, engine_name=args.engine,
        use_lexicon=not args.no_lexicon, loudness=args.loudness, sample_rate=args.sample_rate, speed=args.speed,
    )
    return result.to_dict()


def cmd_batch(args, base: str | None) -> dict:
    data = read_items(args.file)
    out_dir = str(Path(args.output).expanduser().resolve())
    if base:
        body: dict[str, Any] = {"out_dir": out_dir, "skip_existing": not args.force, "format": "json",
                                **_batch_options(args)}
        if isinstance(data, dict):
            body.update({k: v for k, v in data.items() if k in {"items", "style", "engine", "replace"}})
            if args.style:
                body["style"] = args.style
            if args.engine:
                body["engine"] = args.engine
        else:
            body["items"] = data
            body["style"] = args.style
            body["engine"] = args.engine
        if not args.quiet:
            print(f"서버({base})에 {len(body.get('items') or [])}개를 보냅니다.", file=sys.stderr)
            return _with_progress(base, lambda: _http("POST", base + "/api/batch", body, timeout=24 * 3600))
        return _http("POST", base + "/api/batch", body, timeout=24 * 3600)
    import service

    if args.engine:
        if isinstance(data, dict):
            data = {**data, "engine": args.engine}
        else:
            data = {"items": data, "engine": args.engine}
    items = service.parse_items(data, default_style=args.style)

    def progress(index: int, total: int, entry: dict) -> None:
        if args.quiet:
            return
        mark = "재사용" if entry.get("cached") else ("완료" if entry.get("ok") else "실패")
        print(f"[{index}/{total}] {mark} {entry.get('id')} {entry.get('error', '')}", file=sys.stderr)

    return service.run_batch(items, out_dir, default_style=args.style, skip_existing=not args.force, on_item=progress,
                             **_batch_options(args))


def _batch_options(args) -> dict[str, Any]:
    return {"loudness": args.loudness, "sample_rate": args.sample_rate, "prune": args.prune,
            "timeline": args.timeline, "gap_sec": args.gap, "paragraph_gap_sec": args.paragraph_gap, "speed": args.speed}


def _with_progress(base: str, call):
    """서버에 일괄 생성을 맡기는 동안 /api/health 의 진행 상황을 보여 준다."""
    import threading
    import time

    done = threading.Event()

    def watch() -> None:
        shown = None
        while not done.wait(3):
            try:
                info = _http("GET", base + "/api/health", timeout=3)
            except Exception:
                continue
            batch = info.get("batch") if isinstance(info, dict) else None
            if batch and (batch["done"], batch["id"]) != shown:
                shown = (batch["done"], batch["id"])
                print(f"[{batch['done'] + 1}/{batch['total']}] {batch['id']} 만드는 중…", file=sys.stderr, flush=True)

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        return call()
    finally:
        done.set()
        thread.join(1)


def cmd_styles(args, base: str | None) -> dict:
    if base:
        return _http("GET", base + "/api/styles")
    import voices

    return {"ok": True, "styles": [s.public_dict() for s in voices.list_styles()]}


def cmd_engines(args, base: str | None) -> dict:
    if base:
        return _http("GET", base + "/api/engines")
    import backends

    return {"ok": True, "platform": backends.current_platform(), "default_engine": backends.default_engine_id(),
            "engines": backends.all_status()}


def cmd_register(args, base: str | None) -> dict:
    # 녹음 등록은 파일을 references/ 에 쓰므로 항상 이 프로세스에서 한다(서버와 같은 폴더).
    import service

    style = service.register_reference(args.style, args.audio, args.script, label=args.label)
    return {"ok": True, "style": style.public_dict()}


def cmd_health(args, base: str | None) -> dict:
    if base:
        return _http("GET", base + "/api/health")
    return {"ok": True, "server": False, "note": "서버가 꺼져 있습니다. 명령은 이 프로세스에서 직접 실행됩니다."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voicelab", description="내 목소리 TTS 명령줄 도구")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="서버 주소(기본 %(default)s, 환경변수 VOICELAB_URL)")
    parser.add_argument("--mode", choices=["auto", "server", "local"], default="auto",
                        help="auto: 서버가 켜져 있으면 서버, 아니면 직접 / server: 서버만 / local: 직접만")
    parser.add_argument("--quiet", "-q", action="store_true", help="진행 문구 없이 JSON 만 출력")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("say", help="문장 하나 → WAV 하나")
    p.add_argument("text")
    p.add_argument("-s", "--style", default="default", help="말투 id 또는 이름(default/talk/guide/joy, 기본/대화/안내/기쁨)")
    p.add_argument("-o", "--output", help="결과 WAV 경로(없으면 outputs/)")
    p.add_argument("--seed", type=int)
    p.add_argument("-e", "--engine", help="모델(qwen3, chatterbox) 또는 엔진 id(qwen3-mlx, chatterbox-torch 등). 없으면 기본 엔진")
    p.add_argument("--no-lexicon", action="store_true", help="발음 사전(lexicon.json)을 쓰지 않음")
    _add_audio_options(p)
    p.set_defaults(func=cmd_say)

    p = sub.add_parser("batch", help="목록 → WAV 여러 개 + manifest.json")
    p.add_argument("file", help=".json / .jsonl / .txt, 또는 - (표준 입력)")
    p.add_argument("-o", "--output", required=True, help="결과 폴더")
    p.add_argument("-s", "--style", help="항목에 style 이 없을 때 쓸 말투")
    p.add_argument("-e", "--engine", help="항목에 engine 이 없을 때 쓸 모델·엔진")
    p.add_argument("--force", action="store_true", help="이미 만든 같은 문장도 다시 만듦")
    _add_audio_options(p)
    p.add_argument("--timeline", action="store_true", help="이어 붙인 narration.wav 와 자막 narration.srt 도 만듦")
    p.add_argument("--gap", type=float, default=0.4, help="--timeline 의 문장 사이 쉼(초, 기본 0.4)")
    p.add_argument("--paragraph-gap", type=float, default=1.0, dest="paragraph_gap",
                   help="--timeline 의 문단 사이 쉼(초, 기본 1.0). TXT 는 빈 줄, JSON 은 항목의 paragraph 번호로 문단을 나눔")
    p.add_argument("--prune", action="store_true", help="이번 목록에 없는 예전 결과를 _stale/ 로 옮김")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("styles", help="말투 목록과 등록 상태")
    p.set_defaults(func=cmd_styles)

    p = sub.add_parser("engines", help="엔진(모델 × 실행 방식) 목록과 이 컴퓨터에서 쓸 수 있는지")
    p.set_defaults(func=cmd_engines)

    p = sub.add_parser("register", help="참조 녹음(WAV/M4A)을 말투에 등록")
    p.add_argument("style", help="말투 id(default/talk/guide/joy 또는 새 id)")
    p.add_argument("audio", help="녹음 파일")
    p.add_argument("--script", required=True, help="녹음에서 실제로 읽은 문장")
    p.add_argument("--label", help="화면에 보일 이름(새 말투일 때)")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("health", help="서버 상태")
    p.set_defaults(func=cmd_health)

    args = parser.parse_args(argv)
    base = args.server.rstrip("/")
    if args.command == "register" or args.mode == "local":
        use = None
    elif args.mode == "server":
        if not server_alive(base):
            print(json.dumps({"ok": False, "error": f"서버 {base} 에 연결하지 못했습니다."}, ensure_ascii=False))
            return 2
        use = base
    else:
        use = base if server_alive(base) else None
    if use is None and args.command != "health":
        sys.path.insert(0, str(HERE))
        if not args.quiet and args.command in {"say", "batch"}:
            print("서버를 쓰지 않고 이 프로세스에서 모델을 올려 만듭니다.", file=sys.stderr)
    try:
        result = args.func(args, use)
    except CliError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
