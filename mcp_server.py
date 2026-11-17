#!/usr/bin/env python3
"""MCP 서버(stdio). 코딩 에이전트가 도구로 음성을 만들게 한다.

서버(기본 http://127.0.0.1:7860)가 켜져 있으면 그쪽에 보내고, 꺼져 있으면 이 프로세스에서 모델을 올린다.
등록 예(Claude Code):
  claude mcp add voicelab -- "<이 폴더>/.venv/bin/python" "<이 폴더>/mcp_server.py"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import voicelab_cli as cli  # noqa: E402

BASE = os.environ.get("VOICELAB_URL", cli.DEFAULT_SERVER).rstrip("/")

server = MCPServer(
    name="voicelab",
    instructions=(
        "로컬 한국어 목소리 복제 TTS. 사용자 본인의 참조 녹음으로 문장을 읽어 WAV 를 만든다. "
        "먼저 list_styles 로 등록된 말투(ready=true)를 확인하고, speak(문장 하나) 또는 "
        "speak_batch(대사 여러 개 → 폴더에 WAV 여러 개 + manifest.json)를 쓴다. "
        "생성은 한 번에 하나씩 순서대로 처리되며 문장당 수 초가 걸린다. 결과 path 는 이 컴퓨터의 절대 경로다."
    ),
)


def _base() -> str | None:
    return BASE if cli.server_alive(BASE) else None


def _call(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except cli.CliError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _styles() -> dict[str, Any]:
    base = _base()
    if base:
        return cli._http("GET", base + "/api/styles")
    import voices

    return {"ok": True, "styles": [s.public_dict() for s in voices.list_styles()]}


def _speak(text: str, style: str, output_path: str | None, seed: int | None) -> dict[str, Any]:
    out = str(Path(output_path).expanduser().resolve()) if output_path else None
    base = _base()
    if base:
        return cli._http(
            "POST", base + "/api/tts",
            {"text": text, "style": style, "format": "json", "output_path": out, "seed": seed},
        )
    import service

    return service.synthesize(text, style, output_path=out, seed=seed).to_dict()


def _batch(items: list[Any], out_dir: str, style: str | None, force: bool) -> dict[str, Any]:
    folder = str(Path(out_dir).expanduser().resolve())
    base = _base()
    if base:
        return cli._http(
            "POST", base + "/api/batch",
            {"items": items, "style": style, "out_dir": folder, "skip_existing": not force},
        )
    import service

    parsed = service.parse_items(items, default_style=style)
    return service.run_batch(parsed, folder, default_style=style, skip_existing=not force)


@server.tool()
async def list_styles() -> dict[str, Any]:
    """말투 목록. ready=true 인 말투만 생성에 쓸 수 있다. id(default/talk/guide/joy…)와 이름(기본/대화/안내/기쁨) 모두 style 로 받는다."""
    return await anyio.to_thread.run_sync(_call, _styles)


@server.tool()
async def speak(text: str, style: str = "default", output_path: str | None = None, seed: int | None = None) -> dict[str, Any]:
    """문장 하나를 사용자 목소리로 읽어 WAV 하나를 만든다.

    text: 읽을 한국어 문장(2000자 이하). style: 말투 id 또는 이름(예: talk, 대화, guide, 안내).
    output_path: 결과 WAV 절대 경로(없으면 프로젝트 outputs/). seed: 같은 결과를 다시 얻고 싶을 때.
    반환: {ok, path, duration_sec, sample_rate, style, ...}
    """
    return await anyio.to_thread.run_sync(_call, _speak, text, style, output_path, seed)


@server.tool()
async def speak_batch(items: list[Any], out_dir: str, style: str | None = None, force: bool = False) -> dict[str, Any]:
    """대사 여러 개를 한 번에 만든다. 항목마다 out_dir/<id>.wav 하나, 그리고 out_dir/manifest.json.

    items: ["문장", ...] 또는 [{"id": "s01", "text": "문장", "style": "talk"}, ...]
    style: 항목에 style 이 없을 때 쓸 말투. force: 이미 만든 같은 문장도 다시 만든다(기본은 재사용).
    반환: {ok, succeeded, failed, items: [{id, ok, path, duration_sec, error?}], manifest}
    """
    return await anyio.to_thread.run_sync(_call, _batch, items, out_dir, style, force)


@server.tool()
async def health() -> dict[str, Any]:
    """서버 상태(켜짐 여부, 모델 메모리 적재, 진행 중 생성)."""

    def run() -> dict[str, Any]:
        base = _base()
        if base:
            return cli._http("GET", base + "/api/health")
        return {"ok": True, "server": False, "note": "서버가 꺼져 있습니다. 요청 시 이 MCP 프로세스가 모델을 올립니다."}

    return await anyio.to_thread.run_sync(_call, run)


if __name__ == "__main__":
    server.run()
