"""내 목소리 생성기 — 127.0.0.1 전용 화면 + HTTP API 서버.

화면: ① 내 목소리 → ② 문장 → ③ 말투 → ④ 만들기 → ⑤ 결과 를 한 화면에 둔다.
API: /api/* (api.py), 예전 Gradio 호출 /synthesize 도 그대로 받는다.
"""

from __future__ import annotations

import argparse
import html
import json
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import quote

import local_env

import gradio as gr
import uvicorn
from fastapi import FastAPI

import api
import engine
import records
import service
import system_probe
import voices
from audio_prep import UserInputError

PRESETS: dict[str, tuple[str, str]] = {
    "일상": ("talk", "오늘 저녁에는 뭐 먹을까요? 날씨도 좋은데 오랜만에 밖에서 먹는 건 어때요?"),
    "안내": ("guide", "오늘은 인공지능을 활용해서 일상생활을 더욱 편리하게 만드는 방법을 소개하겠습니다."),
    "감정": ("joy", "정말요? 드디어 성공했다고요? 와, 너무 잘됐다! 이렇게 기쁜 소식을 듣게 될 줄은 몰랐어요."),
}
CONSENT_LABEL = "이 목소리는 본인 것이고 생성에 동의합니다"
NEW_STYLE = "__new__"
# 예전 화면의 역할 이름 → 말투 id (예전 /synthesize 호출의 edit_* 필드용)
LEGACY_ROLE_OF = {"default": "timbre", "talk": "question", "guide": "guide", "joy": "joy"}
SERVER = {"url": "http://127.0.0.1:7860"}


# ---------------------------------------------------------------- 화면 조각(HTML)
def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_status_chip() -> str:
    info = service.health()
    if info["busy"]:
        label, kind = "생성 중", "busy"
    elif info["phase"] == "error":
        label, kind = "오류", "err"
    elif info["model_loaded"]:
        label, kind = "모델 준비됨", "ok"
    else:
        label, kind = "모델 대기(첫 생성 때 불러옴)", "idle"
    return (
        '<div class="vl-chips">'
        '<span class="vl-chip ok">● 로컬 전용 · 음성이 밖으로 나가지 않음</span>'
        f'<span class="vl-chip {kind}">{_esc(label)}</span>'
        "</div>"
    )


def render_steps(text: str = "", style_id: str | None = None, made: bool = False) -> str:
    ready = voices.ready_styles()
    style_ok = bool(style_id) and any(s.id == style_id for s in ready)
    steps = [
        ("내 목소리", bool(ready)),
        ("문장", bool((text or "").strip())),
        ("말투", style_ok),
        ("만들기", made),
    ]
    items = []
    current_found = False
    for index, (label, done) in enumerate(steps, start=1):
        if done:
            cls, mark = "done", "✓"
        elif not current_found:
            cls, mark = "now", str(index)
            current_found = True
        else:
            cls, mark = "", str(index)
        items.append(f'<div class="vl-step {cls}"><span class="vl-dot">{mark}</span>{label}</div>')
    return '<div class="vl-steps">' + '<span class="vl-line"></span>'.join(items) + "</div>"


def render_voice_cards(selected: str | None) -> str:
    rows = []
    for style in voices.list_styles():
        if not style.ready and not style.builtin:
            continue
        on = " on" if style.id == selected else ""
        if style.ready:
            seconds = style.duration_sec() or 0.0
            meta = f'<span class="vl-ok">✓ 등록</span> · {seconds:.1f}초'
            src = f"/api/references/{quote(style.id)}/audio"
            play = (
                f'<button class="vl-play" title="참조 녹음 듣기" aria-label="{_esc(style.label)} 참조 녹음 듣기" '
                f'onclick="event.stopPropagation();var a=this._a||(this._a=new Audio(\'{src}\'));'
                "if(a.paused){a.currentTime=0;a.play();this.textContent='■'}else{a.pause();this.textContent='▶'}"
                "a.onended=()=>{this.textContent='▶'}\">▶</button>"
            )
            pick = (
                "onclick=\"var r=document.querySelectorAll('#vl-style input[type=radio]');"
                f"for(var i of r){{if(i.value==='{_esc(style.id)}'||i.parentElement.innerText.trim()==='{_esc(style.label)}'){{i.click();}}}}\""
            )
        else:
            meta = '<span class="vl-miss">미등록</span> · 목소리 등록 탭에서 녹음'
            play = ""
            pick = ""
        rows.append(
            f'<div class="vl-card{on}{"" if style.ready else " off"}" {pick}>'
            f'<div><div class="vl-name">{_esc(style.label)} <span class="vl-id">{_esc(style.id)}</span></div>'
            f'<div class="vl-meta">{meta}</div>'
            f'<div class="vl-desc">{_esc(style.description)}</div></div>{play}</div>'
        )
    return '<div class="vl-cards">' + "".join(rows) + "</div>"


def render_history(history: list[dict]) -> str:
    if not history:
        return '<div class="vl-empty">아직 만든 음성이 없습니다. 위에서 문장을 적고 만들기를 누르세요.</div>'
    rows = []
    for item in history:
        url = item.get("url") or ""
        text = item.get("text", "")
        short = text if len(text) <= 60 else text[:58] + "…"
        rows.append(
            '<div class="vl-row">'
            f'<span class="vl-tag">{_esc(item.get("style_label", ""))}</span>'
            f'<span class="vl-text" title="{_esc(text)}">{_esc(short)}</span>'
            f'<span class="vl-dur">{float(item.get("duration_sec", 0)):.1f}초</span>'
            f'<audio controls preload="none" src="{_esc(url)}"></audio>'
            f'<a class="vl-dl" href="{_esc(url)}" download="{_esc(item.get("file", "voice.wav"))}" title="WAV 받기">⬇ WAV</a>'
            "</div>"
        )
    return '<div class="vl-hist">' + "".join(rows) + "</div>"


def style_choices() -> list[tuple[str, str]]:
    return [(s.label, s.id) for s in voices.ready_styles()]


def register_choices() -> list[tuple[str, str]]:
    items = [(f"{s.label}{' ✓' if s.ready else ''}", s.id) for s in voices.list_styles() if s.builtin or s.ready]
    items.append(("+ 새 말투", NEW_STYLE))
    return items


# ---------------------------------------------------------------- 만들기
def _run_with_phases(fn):
    """생성을 다른 스레드에서 돌리고, 단계가 바뀔 때마다 단계 이름을 내보낸다."""
    holder: dict[str, object] = {}
    box = {"name": "loading"}

    def worker() -> None:
        try:
            holder["result"] = fn(lambda name: box.__setitem__("name", name))
        except Exception as exc:
            holder["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    shown = None
    while thread.is_alive():
        if box["name"] != shown:
            shown = box["name"]
            yield ("phase", shown)
        thread.join(0.25)
    if "error" in holder:
        raise holder["error"]  # type: ignore[misc]
    yield ("done", holder["result"])


def generate(consent: bool, style_id: str, text: str, per_line: bool, history: list[dict] | None):
    made = list(history or [])
    keep = (gr.update(), gr.update(), gr.update(), gr.update(), gr.update())

    def frame(status: str, audio=gr.update(), done: bool = False):
        return (
            audio,
            status,
            render_history(made),
            made,
            render_steps(text, style_id, done or bool(made)),
            render_status_chip(),
        )

    try:
        if not consent:
            raise UserInputError("본인 목소리이고 생성에 동의할 때만 만듭니다. ④의 동의에 체크하세요.")
        if not style_id:
            raise UserInputError("③에서 말투를 고르세요. 말투가 없으면 목소리 등록 탭에서 먼저 녹음하세요.")
        raw = (text or "").strip()
        if not raw:
            raise UserInputError("②에 만들 문장을 적으세요.")
        lines = [line.strip() for line in raw.splitlines() if line.strip()] if per_line else [raw]
        total = len(lines)
        last_path = None
        for index, line in enumerate(lines, start=1):
            prefix = f"{index}/{total} · " if total > 1 else ""
            for kind, value in _run_with_phases(
                lambda on_phase, line=line: service.synthesize(line, style_id, on_phase=on_phase)
            ):
                if kind == "phase":
                    label = "모델 불러오는 중(처음 한 번만 느립니다)" if value == "loading" else "음성 만드는 중"
                    yield frame(f"⏳ {prefix}{label}…")
                else:
                    data = value.to_dict()
                    data["url"] = f"/api/files/{quote(value.path.name)}"
                    made.insert(0, data)
                    last_path = str(value.path)
                    yield frame(
                        f"✅ {prefix}완료 · {data['style_label']} · {data['duration_sec']:.1f}초 · {data['file']}",
                        audio=last_path,
                        done=True,
                    )
    except (UserInputError, RuntimeError) as exc:
        yield frame(f"⚠️ {exc}")
        raise gr.Error(str(exc)) from exc
    except Exception as exc:
        message = f"생성에 실패했습니다. {type(exc).__name__}: {exc}"
        yield frame(f"⚠️ {message}")
        raise gr.Error(message) from exc
    del keep


def on_preset(name: str):
    style_id, text = PRESETS[name]
    ready_ids = {s.id for s in voices.ready_styles()}
    return text, (style_id if style_id in ready_ids else gr.update())


# ---------------------------------------------------------------- 목소리 등록
def reg_info(style_id: str):
    if style_id == NEW_STYLE:
        guide = (
            "### 새 말투\n"
            "5–15초 정도 소리 내어 읽을 문장을 정하고, 아래 칸에 그대로 적은 뒤 녹음하세요. "
            "말투 ID는 영문 소문자로 정합니다(예: `news`, `calm`)."
        )
        return guide, "", gr.update(visible=True), None
    style = voices.resolve(style_id)
    guide = (
        f"### 이 문장을 읽어 주세요\n<div class='vl-script'>{_esc(style.script)}</div>\n\n"
        f"**억양 안내(읽지 않음):** {style.prosody or '평소처럼 읽습니다.'}"
    )
    current = str(style.path) if style.ready and style.path else None
    return guide, style.script, gr.update(visible=False), current


def do_register(style_id: str, new_id: str, new_label: str, audio_path: str | None, script: str, selected: str):
    try:
        if not audio_path:
            raise UserInputError("마이크로 녹음하거나 파일을 올리세요.")
        target = (new_id or "").strip().lower() if style_id == NEW_STYLE else style_id
        label = (new_label or "").strip() or None
        style = service.register_reference(target, audio_path, script, label=label)
    except UserInputError as exc:
        raise gr.Error(str(exc)) from exc
    seconds = style.duration_sec() or 0.0
    note = f"✅ '{style.label}({style.id})' 말투에 녹음을 등록했습니다 · {seconds:.1f}초"
    if seconds < 5 or seconds > 15:
        note += " · 권장 길이는 5–15초입니다"
    keep_selected = selected if selected in {s.id for s in voices.ready_styles()} else style.id
    return (
        note,
        render_voice_cards(keep_selected),
        gr.update(choices=style_choices(), value=keep_selected),
        gr.update(choices=register_choices(), value=style.id),
        str(style.path),
        gr.update(visible=False),
    )


def load_lexicon_rows():
    rows = [[k, v] for k, v in service.load_lexicon().items()]
    return rows or [["배지", "뺏지"]]


def save_lexicon_rows(rows) -> str:
    mapping: dict[str, str] = {}
    data = rows.values.tolist() if hasattr(rows, "values") else (rows or [])
    for row in data:
        if len(row) >= 2 and str(row[0] or "").strip() and str(row[1] or "").strip():
            mapping[str(row[0]).strip()] = str(row[1]).strip()
    service.save_lexicon(mapping)
    return f"✅ 발음 사전 {len(mapping)}개를 저장했습니다. 화면·API·명령줄 생성에 바로 쓰입니다."


# ---------------------------------------------------------------- 에이전트·MCP 안내
def agent_snippets() -> dict[str, str]:
    root = local_env.ROOT.resolve()
    py = root / ".venv" / "bin" / "python"
    url = SERVER["url"]
    return {
        "claude": f'claude mcp add voicelab -- "{py}" "{root / "mcp_server.py"}"',
        "json": json.dumps(
            {"mcpServers": {"voicelab": {"command": str(py), "args": [str(root / "mcp_server.py")], "env": {"VOICELAB_URL": url}}}},
            ensure_ascii=False,
            indent=2,
        ),
        "codex": f'[mcp_servers.voicelab]\ncommand = "{py}"\nargs = ["{root / "mcp_server.py"}"]\nenv = {{ VOICELAB_URL = "{url}" }}',
        "cli": (
            f'cd "{root}"\n'
            "# 문장 하나\n"
            '.venv/bin/python voicelab_cli.py say "안녕하세요, 반갑습니다." -s talk -o ~/Desktop/hello.wav\n'
            "# 대사 목록(JSON·TXT) → 폴더에 WAV 여러 개 + manifest.json\n"
            ".venv/bin/python voicelab_cli.py batch lines.json -o ~/Desktop/narration -s guide\n"
            "# 말투 목록\n"
            ".venv/bin/python voicelab_cli.py styles"
        ),
        "lines": json.dumps(
            {"style": "guide", "items": [
                {"id": "s01", "text": "안녕하세요, 오늘 발표를 맡은 사람입니다."},
                {"id": "s02", "text": "와, 이게 진짜 되네요?", "style": "joy"},
            ]},
            ensure_ascii=False,
            indent=2,
        ),
        "curl": (
            f"# WAV 하나 받기\n"
            f"curl -s -X POST {url}/api/tts -H 'Content-Type: application/json' \\\n"
            "  -d '{\"text\":\"안녕하세요\",\"style\":\"talk\"}' -o hello.wav\n\n"
            f"# 여러 문장 한 번에(서버가 out_dir 에 WAV 와 manifest.json 을 씀)\n"
            f"curl -s -X POST {url}/api/batch -H 'Content-Type: application/json' \\\n"
            "  -d '{\"style\":\"guide\",\"out_dir\":\"/tmp/narration\",\"items\":[\"첫 문장\",\"둘째 문장\"]}'\n\n"
            f"# 상태와 말투\n"
            f"curl -s {url}/api/health\n"
            f"curl -s {url}/api/styles"
        ),
        "python": (
            "import json, urllib.request\n"
            f'req = urllib.request.Request("{url}/api/tts",\n'
            '    data=json.dumps({"text": "안녕하세요", "style": "talk", "format": "json"}).encode(),\n'
            '    headers={"Content-Type": "application/json"})\n'
            "result = json.load(urllib.request.urlopen(req))\n"
            'print(result["path"], result["duration_sec"])'
        ),
    }


AGENT_DIAGRAM = """
<div class="vl-diagram" role="img" aria-label="에이전트가 MCP·명령줄·HTTP로 이 서버에 요청하면 내 목소리 WAV가 폴더에 생긴다">
  <div class="vl-node"><b>AI 코딩 에이전트</b><span>Claude Code · Codex · Cursor</span></div>
  <div class="vl-arrow">→</div>
  <div class="vl-node vl-stack"><b>연결 방법 셋 중 하나</b>
    <span class="vl-pill">MCP 도구 <i>speak · speak_batch</i></span>
    <span class="vl-pill">명령줄 <i>voicelab_cli.py</i></span>
    <span class="vl-pill">HTTP <i>/api/tts · /api/batch</i></span></div>
  <div class="vl-arrow">→</div>
  <div class="vl-node accent"><b>이 서버</b><span>127.0.0.1 · 모델 1개 · 순서대로 생성</span></div>
  <div class="vl-arrow">→</div>
  <div class="vl-node"><b>WAV 파일</b><span>대사마다 1개 + manifest.json</span></div>
</div>
"""

AGENT_PROMPTS = """
**에이전트에게는 이렇게 부탁하면 됩니다**

- “`plan.json` 의 대사를 voicelab MCP로 **안내** 말투로 만들어 `voice/` 폴더에 넣어 줘. 대사 id를 파일 이름으로 써.”
- “쿠키 영상 대사 5개를 **대화** 말투로 만들고, 각 길이(초)를 표로 정리해 줘.”
- “`배지`는 `뺏지`로 읽게 발음 사전에 넣고 03번 대사만 다시 만들어 줘.”

**알아 두면 좋은 점**

- 서버가 켜져 있으면 MCP·명령줄은 서버로 보냅니다(모델을 두 번 올리지 않음). 꺼져 있으면 그 프로세스가 모델을 직접 올립니다.
- 생성은 한 번에 하나씩 순서대로입니다. 문장당 수 초, 첫 생성은 모델을 불러오느라 더 걸립니다.
- 같은 문장·말투는 다시 만들지 않고 재사용합니다(`manifest.json`). 다시 만들려면 `force`/`--force`.
- 자세한 형식: 프로젝트의 `AGENTS.md`, `docs/API.md`, 그리고 이 서버의 [`/docs`](/docs)(자동 API 문서).
"""


def check_connection() -> str:
    info = service.health()
    ready = [f"{s['label']}({s['id']})" for s in info["styles"] if s["ready"]]
    missing = [f"{s['label']}({s['id']})" for s in info["styles"] if not s["ready"]]
    lines = [
        f"✅ 서버 응답 정상 · {SERVER['url']} · API 버전 {info['api_version']}",
        f"모델: `{info['model']}` · {'메모리에 있음' if info['model_loaded'] else '첫 생성 때 불러옴'}",
        f"쓸 수 있는 말투: {', '.join(ready) if ready else '없음 — 목소리 등록 탭에서 먼저 녹음하세요'}",
    ]
    if missing:
        lines.append(f"미등록 말투: {', '.join(missing)}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------- 예전 /synthesize 호환
def legacy_synthesize(
    consent: bool,
    style_id: str,
    gen_text: str,
    differed_timbre: bool,
    edit_timbre: str,
    differed_question: bool,
    edit_question: str,
    differed_guide: bool,
    edit_guide: str,
    differed_joy: bool,
    edit_joy: str,
):
    """예전 화면과 같은 이름·순서의 인자를 받는다(gradio_client 호출 호환). 문장은 손대지 않고 읽는다."""
    try:
        if not consent:
            raise UserInputError("동의가 없으면 만들지 않습니다. 본인 목소리이고 생성에 동의할 때만 체크하세요.")
        style = voices.resolve(style_id or "default")
        edits = {
            "timbre": (differed_timbre, edit_timbre),
            "question": (differed_question, edit_question),
            "guide": (differed_guide, edit_guide),
            "joy": (differed_joy, edit_joy),
        }
        differed, edited = edits.get(LEGACY_ROLE_OF.get(style.id, ""), (False, ""))
        ref_text = (edited or "").strip() if differed else None
        if differed and not ref_text:
            raise UserInputError("원본 대본이 비어 있습니다. 읽은 문장을 적으세요.")
        result = service.synthesize(gen_text, style.id, ref_text=ref_text, use_lexicon=False)
    except (UserInputError, RuntimeError) as exc:
        raise gr.Error(str(exc)) from exc
    info = (
        f"말투: {result.style_label}\n"
        f"생성 시간: {result.generate_sec:.2f}초\n"
        f"길이: {result.duration_sec:.2f}초\n"
        f"파일: {result.path.name}"
    )
    return str(result.path), info, str(result.path), "만들었습니다."


# ---------------------------------------------------------------- 화면 구성
CSS = """
.gradio-container{max-width:1180px !important;margin:0 auto !important}
.vl-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:4px 2px}
.vl-title{font-size:1.45rem;font-weight:700;letter-spacing:-.01em}
.vl-sub{color:var(--body-text-color-subdued);font-size:.92rem}
.vl-chips{display:flex;gap:8px;flex-wrap:wrap}
.vl-chip{font-size:.8rem;padding:4px 12px;border-radius:999px;border:1px solid var(--border-color-primary);color:var(--body-text-color-subdued)}
.vl-chip.ok{color:#15803d;border-color:#86efac;background:rgba(34,197,94,.08)}
.vl-chip.busy{color:#b45309;border-color:#fcd34d;background:rgba(245,158,11,.1)}
.vl-chip.err{color:#b91c1c;border-color:#fca5a5;background:rgba(239,68,68,.08)}
.vl-steps{display:flex;align-items:center;gap:8px;padding:10px 4px 2px;flex-wrap:wrap}
.vl-step{display:flex;align-items:center;gap:8px;font-size:.95rem;color:var(--body-text-color-subdued)}
.vl-step.now{color:var(--body-text-color);font-weight:600}
.vl-step.done{color:var(--body-text-color)}
.vl-dot{width:26px;height:26px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:.8rem;border:1px solid var(--border-color-primary);background:var(--background-fill-secondary)}
.vl-step.now .vl-dot{border-color:var(--color-accent);color:var(--color-accent);border-width:2px}
.vl-step.done .vl-dot{background:var(--color-accent);border-color:var(--color-accent);color:#fff}
.vl-line{flex:0 1 48px;height:1px;background:var(--border-color-primary)}
.vl-sec{font-size:.98rem;font-weight:650;margin:2px 0 6px}
.vl-sec small{font-weight:400;color:var(--body-text-color-subdued);margin-left:6px}
.vl-panel{border:1px solid var(--border-color-primary) !important;border-radius:14px !important;padding:14px !important;background:var(--background-fill-primary)}
.vl-cards{display:flex;flex-direction:column;gap:8px}
.vl-card{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border:1px solid var(--border-color-primary);border-radius:12px;cursor:pointer;transition:border-color .15s}
.vl-card:hover{border-color:var(--color-accent)}
.vl-card.on{border:2px solid var(--color-accent);padding:9px 11px;background:var(--color-accent-soft)}
.vl-card.off{cursor:default;opacity:.75;border-style:dashed}
.vl-name{font-weight:650}
.vl-id{font-size:.75rem;color:var(--body-text-color-subdued);font-weight:400;margin-left:4px}
.vl-meta{font-size:.8rem;color:var(--body-text-color-subdued);margin-top:2px}
.vl-desc{font-size:.78rem;color:var(--body-text-color-subdued);margin-top:2px}
.vl-ok{color:#16a34a}.vl-miss{color:#b45309}
.vl-play{flex:none;width:34px;height:34px;border-radius:50%;border:1px solid var(--border-color-primary);background:var(--background-fill-secondary);cursor:pointer;font-size:.8rem}
.vl-play:hover{border-color:var(--color-accent);color:var(--color-accent)}
#vl-text textarea{font-size:1.35rem !important;line-height:1.7 !important;min-height:150px}
#vl-style .wrap{gap:8px !important}
#vl-style label{border-radius:999px !important;padding:8px 18px !important;font-size:1rem !important}
#vl-go{font-size:1.1rem !important;min-height:52px}
.vl-empty{padding:14px;color:var(--body-text-color-subdued);font-size:.9rem}
.vl-hist{display:flex;flex-direction:column}
.vl-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto minmax(180px,260px) auto;gap:10px;align-items:center;padding:8px 2px;border-bottom:1px solid var(--border-color-primary)}
.vl-row:last-child{border-bottom:none}
.vl-row audio{width:100%;height:32px}
.vl-tag{font-size:.75rem;padding:2px 10px;border-radius:999px;background:var(--color-accent-soft);color:var(--color-accent);white-space:nowrap}
.vl-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vl-dur{font-size:.85rem;color:var(--body-text-color-subdued)}
.vl-dl{font-size:.85rem;text-decoration:none;white-space:nowrap}
.vl-script{font-size:1.35rem;line-height:1.7;font-weight:600;padding:12px 14px;border-radius:12px;background:var(--background-fill-secondary);margin:6px 0 10px}
.vl-diagram{display:flex;align-items:stretch;gap:8px;flex-wrap:wrap;margin:6px 0 4px}
.vl-node{flex:1 1 150px;display:flex;flex-direction:column;gap:4px;justify-content:center;padding:12px 14px;border:1px solid var(--border-color-primary);border-radius:12px}
.vl-node b{font-size:.95rem}.vl-node span{font-size:.8rem;color:var(--body-text-color-subdued)}
.vl-node.accent{border:2px solid var(--color-accent);background:var(--color-accent-soft)}
.vl-node .vl-pill{display:block;padding:4px 8px;border-radius:8px;background:var(--background-fill-secondary);color:var(--body-text-color)}
.vl-node .vl-pill i{font-style:normal;color:var(--body-text-color-subdued);font-size:.75rem}
.vl-arrow{display:flex;align-items:center;font-size:1.3rem;color:var(--body-text-color-subdued)}
@media (max-width:720px){.vl-row{grid-template-columns:auto minmax(0,1fr) auto}.vl-row audio,.vl-row .vl-dl{grid-column:1/-1}.vl-arrow{display:none}}
"""

THEME = gr.themes.Soft(
    primary_hue="indigo",
    neutral_hue="slate",
    font=["Pretendard", "Apple SD Gothic Neo", "system-ui", "sans-serif"],
)


def build_demo() -> gr.Blocks:
    ready = voices.ready_styles()
    initial_style = "default" if any(s.id == "default" for s in ready) else (ready[0].id if ready else None)
    snippets = agent_snippets()

    with gr.Blocks(title="내 목소리 생성기", analytics_enabled=False) as demo:
        with gr.Row(elem_classes=["vl-head"]):
            gr.HTML(
                '<div><div class="vl-title">🎙️ 내 목소리 생성기</div>'
                '<div class="vl-sub">내 녹음으로 한국어 문장을 읽게 합니다. 이 컴퓨터 안에서만 돕니다.</div></div>'
            )
            status_chip = gr.HTML(render_status_chip())
        steps = gr.HTML(render_steps("", initial_style))

        with gr.Tabs() as tabs:
            # ------------------------------------------------ 만들기
            with gr.Tab("만들기", id="make"):
                history_state = gr.State([])
                with gr.Row(equal_height=False):
                    with gr.Column(scale=4, min_width=260, elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">① 내 목소리 <small>카드를 누르면 그 말투를 고릅니다</small></div>')
                        voice_cards = gr.HTML(render_voice_cards(initial_style))
                        to_register = gr.Button("🎙️ 다시 녹음 · 새 말투 추가", size="sm", variant="secondary")
                    with gr.Column(scale=8, elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">② 문장 <small>한국어로 적으세요</small></div>')
                        text = gr.Textbox(
                            show_label=False,
                            lines=4,
                            max_lines=14,
                            placeholder="오늘은 인공지능으로 일상을 더 편하게 만드는 방법을 소개하겠습니다.",
                            elem_id="vl-text",
                        )
                        with gr.Row():
                            preset_buttons = [gr.Button(f"예시: {name}", size="sm", variant="secondary", min_width=90) for name in PRESETS]
                            per_line = gr.Checkbox(value=False, label="줄마다 따로 만들기(여러 문장 일괄)", min_width=220)
                        gr.HTML('<div class="vl-sec">③ 말투</div>')
                        style = gr.Radio(
                            choices=style_choices(),
                            value=initial_style,
                            show_label=False,
                            elem_id="vl-style",
                        )
                        gr.HTML('<div class="vl-sec">④ 만들기</div>')
                        with gr.Row(equal_height=True):
                            consent = gr.Checkbox(value=False, label=CONSENT_LABEL, scale=3)
                            go = gr.Button("▶ 이 목소리로 만들기", variant="primary", scale=2, elem_id="vl-go")
                        gen_status = gr.Markdown("")
                with gr.Column(elem_classes=["vl-panel"]):
                    gr.HTML('<div class="vl-sec">⑤ 결과 <small>재생하고 WAV로 받으세요</small></div>')
                    result_audio = gr.Audio(
                        show_label=False, type="filepath", interactive=False, buttons=["download"]
                    )
                    gr.HTML('<div class="vl-sec" style="margin-top:8px">이번에 만든 음성</div>')
                    history_html = gr.HTML(render_history([]))

            # ------------------------------------------------ 목소리 등록
            with gr.Tab("목소리 등록", id="register"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=5, elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">1. 등록할 말투</div>')
                        reg_style = gr.Radio(choices=register_choices(), value="default", show_label=False)
                        with gr.Row(visible=False) as new_box:
                            new_id = gr.Textbox(label="말투 ID(영문 소문자)", placeholder="news")
                            new_label = gr.Textbox(label="화면 이름", placeholder="뉴스")
                        first = reg_info("default")
                        reg_guide = gr.Markdown(first[0])
                        gr.HTML(
                            '<div class="vl-sub">조용한 곳에서 입에서 한 뼘 떨어져 5–15초 읽으세요. '
                            "음악·울림·바람 소리는 피합니다.</div>"
                        )
                    with gr.Column(scale=6, elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">2. 녹음하거나 파일 올리기 <small>WAV·M4A(아이폰 음성 메모)·MP3</small></div>')
                        reg_audio = gr.Audio(
                            sources=["microphone", "upload"], type="filepath", show_label=False, buttons=["download"]
                        )
                        gr.HTML('<div class="vl-sec">3. 녹음에서 실제로 읽은 문장</div>')
                        reg_script = gr.Textbox(
                            value=first[1], show_label=False, lines=3,
                            info="다르게 읽었다면 실제로 말한 대로 고치세요. 억양 지시문은 넣지 않습니다.",
                        )
                        reg_go = gr.Button("이 녹음으로 등록", variant="primary")
                        reg_status = gr.Markdown("")
                        gr.HTML('<div class="vl-sec" style="margin-top:8px">지금 등록된 녹음</div>')
                        reg_current = gr.Audio(
                            value=first[3], type="filepath", interactive=False, show_label=False
                        )
                with gr.Accordion("발음 사전 — 잘못 읽는 단어를 소리 나는 대로 바꾸기", open=False):
                    gr.Markdown(
                        "예: `배지` → `뺏지`. 화면·API·명령줄 생성에 모두 적용됩니다. "
                        "문장 안에 `[뺏지]`처럼 대괄호로 소리를 바로 적어도 됩니다."
                    )
                    lexicon = gr.Dataframe(
                        value=load_lexicon_rows(), headers=["원문", "읽을 소리"], column_count=(2, "fixed"),
                        interactive=True, row_count=(1, "dynamic"),
                    )
                    lex_go = gr.Button("발음 사전 저장", size="sm")
                    lex_status = gr.Markdown("")
                with gr.Accordion("파일 위치", open=False):
                    gr.Markdown(
                        f"- 녹음: `{local_env.REFERENCES.resolve()}`\n"
                        f"- 결과: `{local_env.OUTPUTS.resolve()}`\n"
                        f"- 모델 캐시: `{local_env.HF_HUB_CACHE.resolve()}`\n\n"
                        "모두 이 컴퓨터에만 있습니다. 녹음과 결과는 git에 올라가지 않도록 막혀 있습니다."
                    )

            # ------------------------------------------------ 에이전트·MCP
            with gr.Tab("에이전트 · MCP", id="agent"):
                with gr.Column(elem_classes=["vl-panel"]):
                    gr.HTML(
                        '<div class="vl-sec">AI 에이전트가 내 목소리로 대사를 만들게 하기 '
                        "<small>영상 내레이션 대사를 한꺼번에 뽑을 때 편합니다</small></div>"
                    )
                    gr.HTML(AGENT_DIAGRAM)
                    with gr.Row():
                        check = gr.Button("연결 확인", size="sm", variant="secondary", scale=0, min_width=120)
                        check_out = gr.Markdown("")
                with gr.Row(equal_height=False):
                    with gr.Column(elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">1. MCP로 연결 <small>에이전트가 도구로 바로 씁니다(추천)</small></div>')
                        gr.Markdown("**Claude Code** — 터미널에서 한 번 실행:")
                        gr.Code(snippets["claude"], language="shell", interactive=False, show_label=False)
                        gr.Markdown("**Cursor · Claude Desktop** — `mcp.json`(또는 설정 파일)의 `mcpServers`에 추가:")
                        gr.Code(snippets["json"], language="json", interactive=False, show_label=False)
                        gr.Markdown("**Codex** — `~/.codex/config.toml`에 추가:")
                        gr.Code(snippets["codex"], language="shell", interactive=False, show_label=False)
                        gr.Markdown(
                            "도구: `list_styles` 말투 목록 · `speak` 문장 하나 · `speak_batch` 대사 여러 개 · `health` 상태"
                        )
                    with gr.Column(elem_classes=["vl-panel"]):
                        gr.Markdown(AGENT_PROMPTS)
                with gr.Row(equal_height=False):
                    with gr.Column(elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">2. 명령줄 <small>스크립트·영상 파이프라인에서</small></div>')
                        gr.Code(snippets["cli"], language="shell", interactive=False, show_label=False)
                        gr.Markdown("`lines.json` 예시(문자열 목록, `.txt` 줄 목록도 됩니다):")
                        gr.Code(snippets["lines"], language="json", interactive=False, show_label=False)
                    with gr.Column(elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">3. HTTP API <small>어떤 언어에서든</small></div>')
                        gr.Code(snippets["curl"], language="shell", interactive=False, show_label=False)
                        gr.Code(snippets["python"], language="python", interactive=False, show_label=False)

        # ------------------------------------------------ 예전 /synthesize 호출 호환(화면에는 보이지 않음)
        with gr.Column(visible=False):
            l_consent = gr.Checkbox(value=False)
            l_style = gr.Radio(choices=[(s.label, s.id) for s in voices.BUILTIN_STYLES], value="default")
            l_text = gr.Textbox()
            l_fields = []
            for _role in ("timbre", "question", "guide", "joy"):
                l_fields.append(gr.Checkbox(value=False))
                l_fields.append(gr.Textbox())
            l_audio = gr.Audio(type="filepath", label="결과 재생")
            l_info = gr.Textbox(label="이번 결과")
            l_file = gr.File(label="WAV 다운로드")
            l_status = gr.Textbox(label="생성 상태")
            l_button = gr.Button()

        # ------------------------------------------------ 이벤트
        timer = gr.Timer(2.0)
        timer.tick(render_status_chip, outputs=[status_chip], queue=False, api_visibility="private", show_progress="hidden")

        text.change(render_steps, inputs=[text, style], outputs=[steps], queue=False, api_visibility="private", show_progress="hidden")
        style.change(
            lambda t, s: (render_steps(t, s), render_voice_cards(s)),
            inputs=[text, style], outputs=[steps, voice_cards], queue=False, api_visibility="private", show_progress="hidden",
        )
        for button, name in zip(preset_buttons, PRESETS):
            button.click(lambda n=name: on_preset(n), outputs=[text, style], queue=False, api_visibility="private")
        to_register.click(lambda: gr.Tabs(selected="register"), outputs=[tabs], queue=False, api_visibility="private")
        go.click(
            generate,
            inputs=[consent, style, text, per_line, history_state],
            outputs=[result_audio, gen_status, history_html, history_state, steps, status_chip],
            api_visibility="private",
            concurrency_limit=1,
            concurrency_id="tts",
        )

        reg_style.change(
            reg_info, inputs=[reg_style], outputs=[reg_guide, reg_script, new_box, reg_current],
            queue=False, api_visibility="private",
        )
        reg_go.click(
            do_register,
            inputs=[reg_style, new_id, new_label, reg_audio, reg_script, style],
            outputs=[reg_status, voice_cards, style, reg_style, reg_current, new_box],
            api_visibility="private",
            concurrency_limit=1,
        ).then(lambda t, s: render_steps(t, s), inputs=[text, style], outputs=[steps], queue=False, api_visibility="private")
        lex_go.click(save_lexicon_rows, inputs=[lexicon], outputs=[lex_status], api_visibility="private")
        check.click(check_connection, outputs=[check_out], queue=False, api_visibility="private")

        l_button.click(
            legacy_synthesize,
            inputs=[l_consent, l_style, l_text, *l_fields],
            outputs=[l_audio, l_info, l_file, l_status],
            api_name="synthesize",
            concurrency_limit=1,
            concurrency_id="tts",
        )
    return demo


# ---------------------------------------------------------------- 서버
def pick_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit(
        "127.0.0.1에서 쓸 수 있는 포트를 찾지 못했습니다. "
        f"{preferred}부터 {preferred + 19}까지 확인했습니다."
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="qwen3-voice-lab API",
        version=service.API_VERSION,
        description="내 목소리 TTS. 요청·응답 형식은 docs/API.md 참고.",
    )
    app.include_router(api.router)
    demo = build_demo()
    demo.queue(default_concurrency_limit=1)
    return gr.mount_gradio_app(
        app,
        demo,
        path="",
        theme=THEME,
        css=CSS,
        footer_links=["api"],
        allowed_paths=[str(local_env.REFERENCES), str(local_env.OUTPUTS)],
        max_file_size="50mb",
        ssr_mode=False,
        enable_monitoring=False,
        mcp_server=False,
        show_error=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="내 목소리 생성기 서버(127.0.0.1 전용)")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--open", action="store_true", help="브라우저로 화면 열기")
    args = parser.parse_args()
    port = pick_port(args.port)
    if port != args.port:
        print(f"⚠️ {args.port}번 포트를 다른 프로그램이 쓰고 있어 {port}번을 씁니다. "
              "7860을 부르는 도구는 주소를 바꿔야 합니다.", flush=True)
    SERVER["url"] = f"http://127.0.0.1:{port}"
    records.write_comparison()
    app = create_app()
    print(f"화면: {SERVER['url']}", flush=True)
    print(f"API 문서: {SERVER['url']}/docs", flush=True)
    print(f"모델: {system_probe.MODEL_06} (첫 생성 때 불러옵니다)", flush=True)
    print("외부 공유는 켜지 않습니다. 이 컴퓨터에서만 열립니다.", flush=True)
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(SERVER["url"])).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
