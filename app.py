"""내 목소리 생성기 — 127.0.0.1 전용 화면 + HTTP API 서버.

화면: 만들기(말투 · 문장 · 만들기 · 결과) / 목소리 등록(녹음 검사 포함) / 고급 · 에이전트 연결.
API: /api/* (api.py), 예전 Gradio 호출 /synthesize 도 그대로 받는다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import local_env

import gradio as gr
import uvicorn
from fastapi import FastAPI

import api
import engine
import service
import backends
import voices
from audio_prep import UserInputError

PRESETS: dict[str, tuple[str, str]] = {
    "대화": ("talk", "오늘 저녁에는 뭐 먹을까요? 날씨도 좋은데 오랜만에 밖에서 먹는 건 어때요?"),
    "안내": ("guide", "오늘은 인공지능을 활용해서 일상생활을 더욱 편리하게 만드는 방법을 소개하겠습니다."),
    "기쁨": ("joy", "정말요? 드디어 성공했다고요? 와, 너무 잘됐다! 이렇게 기쁜 소식을 듣게 될 줄은 몰랐어요."),
}
CONSENT_LABEL = "이 목소리는 본인 것이고 생성에 동의합니다"
# 예전 화면의 역할 이름 → 말투 id (예전 /synthesize 호출의 edit_* 필드용)
LEGACY_ROLE_OF = {"default": "timbre", "talk": "question", "guide": "guide", "joy": "joy"}
SERVER = {"url": "http://127.0.0.1:7860"}


# ---------------------------------------------------------------- 화면 조각(HTML)
def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_status_chip() -> str:
    info = service.health()
    if info["busy"]:
        batch = info.get("batch")
        label = f"만드는 중 {batch['done'] + 1}/{batch['total']}" if batch else "만드는 중"
        kind = "busy"
    elif info["phase"] == "error":
        label, kind = "최근 생성에 오류가 있었습니다", "err"
    elif info["model_loaded"]:
        loaded = backends.info(info["loaded_engine"]).label.split(" · ")[0] if info.get("loaded_engine") else "모델"
        label, kind = f"{loaded} 준비됨", "ok"
    else:
        label, kind = "준비됨 · 첫 생성은 모델을 불러와 조금 더 걸립니다", "idle"
    return f'<div class="vl-chips"><span class="vl-chip {kind}">{_esc(label)}</span></div>'


def _qc_warnings(style: voices.Style) -> list[str]:
    return [c["item"] for c in ((style.qc or {}).get("checks") or []) if c.get("level") in ("warn", "fail")]


def render_style_info(style_id: str | None) -> str:
    """고른 말투의 설명·참조 녹음 듣기·녹음 검사 경고."""
    ready = voices.ready_styles()
    style = next((s for s in ready if s.id == style_id), None)
    if style is None:
        return '<div class="vl-hint">위에서 말투를 고르세요.</div>' if ready else ""
    seconds = style.duration_sec() or 0.0
    warns = _qc_warnings(style)
    badge = (
        f' · <span class="vl-warn">⚠️ 녹음 확인 필요: {_esc(", ".join(warns))}</span>' if warns else ""
    )
    src = f"/api/references/{quote(style.id)}/audio"
    return (
        '<div class="vl-info">'
        f'<div class="vl-desc">{_esc(style.description or "직접 추가한 말투")}</div>'
        f'<div class="vl-meta">참조 녹음 {seconds:.1f}초{badge}</div>'
        f'<audio controls preload="none" src="{_esc(src)}" aria-label="{_esc(style.label)} 참조 녹음 듣기"></audio>'
        "</div>"
    )


def render_empty_banner() -> str:
    return (
        '<div class="vl-banner" role="note"><b>먼저 내 목소리를 10초쯤 녹음하세요.</b>'
        "<span>등록한 녹음이 있어야 그 목소리로 문장을 읽을 수 있습니다. 녹음은 이 컴퓨터에만 저장됩니다.</span></div>"
    )


def render_history(history: list[dict]) -> str:
    """지난 결과(가장 최근 것은 위 결과 칸에 있으므로 뺀다)."""
    older = history[1:]
    if not older:
        return (
            '<div class="vl-empty">아직 지난 결과가 없습니다. 이 목록은 새로고침하면 사라지고, '
            "파일은 outputs 폴더에 남습니다.</div>"
        )
    return '<div class="vl-hist">' + "".join(_result_row(item) for item in older) + "</div>"


def _result_row(item: dict, number: int | None = None) -> str:
    if not item.get("ok", True):
        label = f"{number:02d} · " if number else ""
        return (
            f'<div class="vl-row vl-fail"><span class="vl-tag">{label}실패</span>'
            f'<span class="vl-text">{_esc(item.get("text", ""))}</span>'
            f'<span class="vl-err">{_esc(item.get("error", ""))}</span></div>'
        )
    url = item.get("url") or ""
    text = item.get("text", "")
    spoken = item.get("spoken_text") or ""
    engine_short = (item.get("engine") or "").split("-")[0]
    tag = f"{number:02d}" if number else _esc(item.get("style_label", ""))
    extra = ""
    if spoken and spoken != text:
        extra += f'<div class="vl-spoken">읽은 문장: {_esc(spoken)}</div>'
    if item.get("warning"):
        extra += f'<div class="vl-warn">⚠️ {_esc(item["warning"])}</div>'
    seed = f" · seed {item['seed']}" if item.get("seed") is not None else ""
    return (
        '<div class="vl-row">'
        f'<span class="vl-tag">{tag}</span>'
        f'<div class="vl-textbox"><div class="vl-text" title="{_esc(text)}">{_esc(text)}</div>{extra}'
        f'<div class="vl-meta">{_esc(item.get("style_label", ""))} · {_esc(engine_short)} · '
        f'{float(item.get("duration_sec", 0)):.1f}초{seed}{" · 재사용" if item.get("cached") else ""}</div></div>'
        f'<audio controls preload="none" src="{_esc(url)}"></audio>'
        f'<a class="vl-dl" href="{_esc(url)}" download="{_esc(item.get("file", "voice.wav"))}">⬇ WAV</a>'
        "</div>"
    )


RUNTIME_LABEL = {"mlx": "MLX(Apple Silicon)", "torch": "PyTorch"}


def engine_choices() -> list[tuple[str, str]]:
    """모델 계열마다 하나. 이 컴퓨터에서 가장 빠른 실행 방식이 자동으로 쓰인다."""
    ready = backends.available_ids()
    items = []
    for family in backends.families():
        members = [engine_id for engine_id in backends.family_members(family) if engine_id in ready]
        if not members:
            continue
        info = backends.info(members[0])
        name = info.label.split(" · ")[0].split(" 0.")[0].split(" 다국어")[0]
        items.append((f"{name} ({info.origin} · {info.developer.split(' ')[0]})", family))
    return items


def default_family() -> str | None:
    engine_id = backends.default_engine_id()
    return backends.info(engine_id).family if engine_id else None


def render_engine_table() -> str:
    rows = [
        "| 엔진 id | 모델 | 실행 방식 | 개발 주체(국가) | 라이선스 | 대본 필요 | 이 컴퓨터 |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in backends.all_status():
        state = "✅ 사용 가능" if item["available"] else f"— {item['reason']}"
        rows.append(
            f"| `{item['id']}` | {item['label'].split(' · ')[0]} | {RUNTIME_LABEL.get(item['runtime'], item['runtime'])} | "
            f"{item['developer']} ({item['origin']}) | {item['license']} | {'예' if item['needs_ref_text'] else '아니오'} | {state} |"
        )
    default = backends.default_engine_id()
    rows.append("")
    rows.append(
        f"기본 엔진: `{default}`. 모델(`qwen3`, `chatterbox`)로 고르면 이 컴퓨터에서 가장 빠른 실행 방식이 자동으로 쓰입니다"
        " (맥은 MLX, 윈도우·리눅스는 PyTorch CUDA, GPU가 없으면 CPU)."
    )
    return "\n".join(rows)


def style_choices() -> list[tuple[str, str]]:
    return [(s.label, s.id) for s in voices.ready_styles()]


def register_choices() -> list[tuple[str, str]]:
    items = []
    for s in voices.list_styles():
        if not (s.builtin or s.ready):
            continue
        state = f"녹음 있음 {s.duration_sec() or 0:.0f}초" if s.ready else "녹음 없음"
        items.append((f"{s.label} · {state}", s.id))
    return items


def split_pieces(text: str, mode: str) -> list[tuple[str, int]]:
    """만들 조각과 문단 번호: none(한 덩어리) · line(줄마다) · sentence(문장마다). 빈 줄은 문단 경계."""
    raw = (text or "").strip()
    if not raw:
        return []
    if mode == "none":
        return [(raw, 1)]
    pieces: list[tuple[str, int]] = []
    paragraph = 1
    for line in raw.splitlines():
        if not line.strip():
            if pieces and pieces[-1][1] == paragraph:
                paragraph += 1
            continue
        if mode == "sentence":
            pieces += [(p.strip(), paragraph) for p in re.split(r"(?<=[.?!…。])\s+", line) if p.strip()]
        else:
            pieces.append((line.strip(), paragraph))
    return pieces


def split_text(text: str, mode: str) -> list[str]:
    return [piece for piece, _paragraph in split_pieces(text, mode)]


def render_readiness(text: str, mode: str, style_id: str | None, consent: bool) -> str:
    pieces = split_text(text, mode)
    chars = len((text or "").strip())
    lines = len([line for line in (text or "").splitlines() if line.strip()])
    parts: list[str] = []
    if not chars:
        parts.append("✗ 문장을 적으세요")
    else:
        size = f"{chars}자" + (f" · {lines}줄" if lines > 1 else "")
        if mode == "none":
            parts.append(f"✓ 문장 {size} → 파일 1개" + (" (줄바꿈은 쉼으로 읽음)" if lines > 1 else ""))
        else:
            paragraphs = len({n for _t, n in split_pieces(text, mode)})
            parts.append(f"✓ 문장 {size} → 파일 {len(pieces)}개" + (f" · 문단 {paragraphs}개" if paragraphs > 1 else ""))
        longest = max((len(p) for p in pieces), default=0)
        if longest > service.MAX_TEXT_CHARS:
            parts.append(f"✗ 한 파일에 {longest}자 — {service.MAX_TEXT_CHARS}자 이하로 나누세요")
        elif mode == "none" and chars > 300:
            parts.append("⚠️ 길면 발음이 흔들릴 수 있어 '문장마다'를 권합니다")
    ready = {s.id: s.label for s in voices.ready_styles()}
    parts.append(f"✓ 말투 {ready[style_id]}" if style_id in ready else "✗ 말투를 고르세요")
    parts.append("✓ 동의함" if consent else "✗ 아래 동의에 체크하세요")
    return '<div class="vl-ready" role="status" aria-live="polite">' + " · ".join(_esc(p) for p in parts) + "</div>"


# ---------------------------------------------------------------- 만들기
STOP = threading.Event()  # 멈추기 버튼(이 컴퓨터 한 사람만 쓰는 화면이라 하나로 충분)


def _run_in_thread(fn):
    """fn 을 다른 스레드에서 돌리고, 1초마다 ("tick", 지난 초)를, 끝나면 ("done", 결과)를 내보낸다."""
    holder: dict[str, object] = {}

    def worker() -> None:
        try:
            holder["result"] = fn()
        except Exception as exc:
            holder["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    started = time.perf_counter()
    thread.start()
    while thread.is_alive():
        thread.join(1.0)
        if thread.is_alive():
            yield ("tick", time.perf_counter() - started)
    if "error" in holder:
        raise holder["error"]  # type: ignore[misc]
    yield ("done", holder["result"])


def _file_url(path: Path) -> str:
    try:
        return "/api/files/" + quote(path.resolve().relative_to(local_env.OUTPUTS.resolve()).as_posix())
    except ValueError:
        return ""


def _project_dir(name: str) -> Path:
    cleaned = service.safe_name((name or "").strip()) if (name or "").strip() else ""
    return local_env.OUTPUTS / "projects" / (cleaned or f"narration-{time.strftime('%Y%m%d-%H%M')}")


def _load_takes(folder: Path) -> dict[str, int]:
    try:
        return {str(k): int(v) for k, v in json.loads((folder / "takes.json").read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def _zip_project(folder: Path, summary: dict) -> Path:
    target = folder.with_suffix(".zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in summary["items"]:
            if entry.get("ok") and entry.get("path"):
                archive.write(entry["path"], arcname=Path(entry["path"]).name)
        archive.write(summary["manifest"], arcname="manifest.json")
        for extra in ("narration_wav", "narration_srt", "narration_markers"):
            if summary.get(extra):
                archive.write(summary[extra], arcname=Path(summary[extra]).name)
    return target


def list_projects() -> list[str]:
    root = local_env.OUTPUTS / "projects"
    if not root.is_dir():
        return []
    folders = [p for p in root.iterdir() if p.is_dir() and (p / "manifest.json").is_file()]
    return [p.name for p in sorted(folders, key=lambda p: p.stat().st_mtime, reverse=True)]


def load_project(name: str):
    """이전 프로젝트 폴더의 결과를 대본 순서대로 다시 보여 준다(생성하지 않음)."""
    folder = local_env.OUTPUTS / "projects" / (name or "")
    manifest_path = folder / "manifest.json"
    if not name or not manifest_path.is_file():
        return {COMPONENTS["gen_status"]: "불러올 프로젝트를 고르세요."}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = data.get("items", {})
    order = data.get("order") or sorted(items)
    rows, entries = [], []
    for number, key in enumerate(order, start=1):
        entry = dict(items.get(key) or {"ok": False, "text": key, "error": "기록 없음"})
        wav = folder / f"{key}.wav"
        entry.setdefault("ok", wav.is_file())
        if wav.is_file():
            entry.update(path=str(wav), file=wav.name, url=_file_url(wav))
        rows.append(_result_row(entry, number))
        entries.append(entry)
    summary = {"items": [e for e in entries if e.get("path")], "manifest": str(manifest_path)}
    for extra, fname in (("narration_wav", "narration.wav"), ("narration_srt", "narration.srt"), ("narration_markers", "narration_markers.csv")):
        if (folder / fname).is_file():
            summary[extra] = str(folder / fname)
    zip_path = _zip_project(folder, summary)
    files = [str(zip_path)] + [summary[k] for k in ("narration_wav", "narration_srt", "narration_markers") if summary.get(k)]
    return {
        COMPONENTS["gen_status"]: f"📂 '{name}' 프로젝트 {len(order)}개를 불러왔습니다. 같은 폴더 이름으로 만들면 바뀐 줄만 다시 만듭니다.",
        COMPONENTS["batch_box"]: gr.update(visible=True),
        COMPONENTS["batch_html"]: '<div class="vl-hist">' + "".join(rows) + "</div>",
        COMPONENTS["batch_files"]: files,
        COMPONENTS["folder_state"]: str(folder),
        COMPONENTS["open_btn"]: gr.update(visible=True),
        COMPONENTS["project"]: name,
    }


def _fmt_sec(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}분 {sec % 60}초" if sec >= 60 else f"{sec}초"


def generate(
    consent: bool, style_id: str, text: str, mode: str, engine_family: str | None, seed_value,
    loud: bool, hq: bool, speed_value, project: str, timeline_on: bool, retake: str, history: list[dict] | None,
):
    """만들기·다른 버전·번호 다시 만들기 공용. 결과 칸들을 dict 로 갱신한다."""
    made = list(history or [])
    STOP.clear()
    status = {"value": ""}

    def out(**kw):
        data = {
            COMPONENTS["gen_status"]: kw.get("status", status["value"]),
            COMPONENTS["status_chip"]: render_status_chip(),
        }
        if "status" in kw:
            status["value"] = kw["status"]
        for key, value in kw.items():
            if key != "status":
                data[COMPONENTS[key]] = value
        return data

    try:
        if not consent:
            raise UserInputError("본인 목소리이고 생성에 동의할 때만 만듭니다. 만들기 버튼 옆의 동의에 체크하세요.")
        if not style_id:
            raise UserInputError("말투를 고르세요. 말투가 없으면 목소리 등록 탭에서 먼저 녹음하세요.")
        pieces = split_text(text, mode)
        if not pieces:
            raise UserInputError("만들 문장을 적으세요.")
        loudness = -16.0 if loud else None
        sample_rate = 48000 if hq else None
        speed = float(speed_value) if speed_value and abs(float(speed_value) - 1.0) > 1e-3 else None
        seed_text = str(seed_value or "").strip()
        if seed_text and not seed_text.isdigit():
            raise UserInputError("seed 는 숫자만 적거나 비워 두세요.")
        seed = int(seed_text) if seed_text else None
        if mode == "none":
            yield out(status="⏳ 만드는 중…", batch_box=gr.update(visible=False))
            for kind, value in _run_in_thread(
                lambda: service.synthesize(pieces[0], style_id, engine_name=engine_family, seed=seed,
                                           loudness=loudness, sample_rate=sample_rate, speed=speed)
            ):
                if kind == "tick":
                    loading = not engine.is_model_loaded()
                    label = "모델 불러오는 중(처음 한 번만 느립니다)" if loading else "음성 만드는 중"
                    yield out(status=f"⏳ {label} · {_fmt_sec(value)}")
                    continue
                data = value.to_dict()
                data["url"] = _file_url(value.path)
                made.insert(0, data)
                note = f"✅ 완료 · {data['duration_sec']:.1f}초 · seed {data['seed']}"
                if data.get("warning"):
                    note += f"\n\n⚠️ {data['warning']}"
                if data.get("spoken_text") and data["spoken_text"] != data["text"]:
                    note += f"\n\n읽은 문장: {data['spoken_text']}"
                yield out(
                    status=note, result_audio=str(value.path), result_dl=gr.update(value=str(value.path), visible=True),
                    again=gr.update(visible=True), history_html=render_history(made), history_state=made,
                )
            return
        # 여러 파일: 프로젝트 폴더에 순번 이름으로(같은 문장은 재사용, 실패해도 계속)
        folder = _project_dir(project)
        folder.mkdir(parents=True, exist_ok=True)
        takes = _load_takes(folder)
        for number in [int(n) for n in re.findall(r"\d+", retake or "")]:
            if 1 <= number <= len(pieces):
                takes[pieces[number - 1]] = secrets.randbelow(2**31 - 1)  # 그 번호만 다른 버전으로
        (folder / "takes.json").write_text(json.dumps(takes, ensure_ascii=False, indent=1), encoding="utf-8")
        items = [
            service.BatchItem(
                text=piece, id=f"{i:03d}_{service.safe_name(piece)[:24]}", style=style_id,
                engine=engine_family, seed=takes.get(piece, seed), paragraph=paragraph,
            )
            for i, (piece, paragraph) in enumerate(split_pieces(text, mode), start=1)
        ]
        progress = {"done": 0, "made": 0, "made_sec": 0.0}

        def on_item(index: int, total: int, entry: dict) -> None:
            progress["done"] = index
            if entry.get("ok") and not entry.get("cached"):
                progress["made"] += 1
                progress["made_sec"] += float(entry.get("generate_sec") or 0)

        total = len(items)
        yield out(status=f"⏳ 0/{total} · 준비 중…", batch_box=gr.update(visible=True))
        for kind, value in _run_in_thread(
            lambda: service.run_batch(
                items, folder, default_style=style_id, default_engine=engine_family, on_item=on_item,
                loudness=loudness, sample_rate=sample_rate, prune=True, timeline=timeline_on,
                speed=speed, should_stop=STOP.is_set,
            )
        ):
            if kind == "tick":
                done = progress["done"]
                eta = ""
                if progress["made"]:
                    per = progress["made_sec"] / progress["made"]
                    eta = f" · 남은 시간 약 {_fmt_sec(per * (total - done))}"
                stop_note = " · 멈추는 중(지금 문장까지 만듭니다)" if STOP.is_set() else ""
                yield out(status=f"⏳ {min(done + 1, total)}/{total} 만드는 중 · {_fmt_sec(value)}{eta}{stop_note}")
                continue
            summary = value
            rows = []
            for number, entry in enumerate(summary["items"], start=1):
                if entry.get("ok"):
                    entry["url"] = _file_url(Path(entry["path"]))
                rows.append(_result_row(entry, number))
            zip_path = _zip_project(folder, summary)
            files = [str(zip_path)] + [summary[k] for k in ("narration_wav", "narration_srt", "narration_markers") if summary.get(k)]
            failed = [str(n) for n, e in enumerate(summary["items"], start=1) if not e.get("ok")]
            reused = sum(1 for e in summary["items"] if e.get("cached"))
            note = f"✅ {total}개 중 {summary['succeeded']}개 완료"
            if reused:
                note += f"(재사용 {reused}개)"
            note += f" · 폴더 `{folder}`"
            if summary.get("stopped"):
                note = "⏹ 멈췄습니다. " + note + " · 다시 누르면 남은 것만 만듭니다"
            elif failed:
                note += f"\n\n⚠️ 실패 {len(failed)}개(번호 {', '.join(failed)}). 만들기를 다시 누르면 실패한 것만 다시 만듭니다."
            if summary.get("warning"):
                note += f"\n\n⚠️ {summary['warning']}"
            yield out(
                status=note, batch_html='<div class="vl-hist">' + "".join(rows) + "</div>",
                batch_files=files, folder_state=str(folder), open_btn=gr.update(visible=True),
            )
    except (UserInputError, RuntimeError) as exc:
        yield out(status=f"⚠️ {exc}")
    except Exception as exc:
        yield out(status=f"⚠️ 생성에 실패했습니다. {type(exc).__name__}: {exc}")


COMPONENTS: dict[str, Any] = {}  # build_demo 가 채운다(generate·do_register 가 이름으로 갱신)


def open_folder(path: str) -> str:
    """결과 폴더를 파일 탐색기로 연다(이 컴퓨터에서만)."""
    if not path or not Path(path).is_dir():
        return "열 폴더가 없습니다."
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return f"폴더를 열었습니다: `{path}`"


def on_preset(name: str, current: str):
    style_id, sample = PRESETS[name]
    ready_ids = {s.id for s in voices.ready_styles()}
    current = (current or "").rstrip()
    text = sample if not current else f"{current}\n{sample}"  # 쓰던 문장은 지우지 않고 아래에 덧붙인다
    return text, (style_id if style_id in ready_ids else gr.update())


def preview_spoken(text: str, engine_family: str | None) -> str:
    """발음 사전·숫자 읽기를 적용한, 모델이 실제로 읽을 문장(생성하지 않음)."""
    raw = (text or "").strip()
    if not raw:
        return "문장을 먼저 적으세요."
    spoken = service.apply_lexicon(raw)
    try:
        engine_id = engine.resolve_engine(engine_family)
        if not backends.info(engine_id).reads_digits:
            spoken = service.spell_numbers(spoken)
    except Exception:
        pass
    return "읽을 문장(바뀐 곳이 없으면 그대로 읽음):\n\n" + spoken


# ---------------------------------------------------------------- 목소리 등록
RECORDING_GUIDE = """
<div class="vl-guide">
<b>녹음 요령</b>
<ul>
<li>조용한 방에서, 입과 마이크 사이 한 뼘. 처음부터 끝까지 거리·자세를 그대로.</li>
<li>녹음을 켜고 0.5초 쉰 뒤 읽기 시작하고, 끝까지 읽은 뒤 0.5초 쉬고 멈춥니다.</li>
<li>말투마다 감정을 처음부터 끝까지 일정하게. 5–15초 분량이 가장 안정적입니다.</li>
<li>블루투스 이어폰 마이크는 피하세요(소리가 좁아짐). 맥은 제어 센터의 마이크 모드를 '표준'으로, 아이폰 음성 메모는 '녹음 향상'을 끕니다.</li>
<li>오른쪽 <b>고음질로 녹음</b>은 브라우저의 잡음 제거·에코 제거·자동 음량을 끄고 압축 없이 녹음합니다. 아래 칸의 마이크 녹음은 이것들이 켜질 수 있어 권하지 않습니다. 음성 메모·QuickTime으로 녹음해 올려도 좋습니다.</li>
<li>등록한 뒤 <b>시험 문장 만들어 듣기</b>로 바로 확인하세요. 대본과 녹음이 어긋나거나 잡음·울림이 크면 여기서 드러납니다.</li>
</ul>
</div>
"""


def reg_info(style_id: str):
    style = voices.resolve(style_id)
    guide = (
        f"#### 이 문장을 읽어 주세요\n<div class='vl-script'>{_esc(style.script)}</div>\n\n"
        f"**억양 안내(읽지 않음):** {style.prosody or '평소처럼 읽습니다.'}"
    )
    current = str(style.path) if style.ready and style.path else None
    current_note = (
        f"지금 녹음 {style.duration_sec() or 0:.1f}초"
        + (f" · ⚠️ {', '.join(_qc_warnings(style))}" if _qc_warnings(style) else "")
        if style.ready else "아직 녹음이 없습니다."
    )
    label = "이 녹음으로 바꾸기" if style.ready else "이 녹음으로 등록"
    return guide, style.script, current, current_note, gr.update(value=label)


def new_style_box():
    return gr.update(visible=True), gr.update(value="")


def _auto_style_id(label: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:24]
    taken = {s.id for s in voices.list_styles()}
    if base and base not in taken and re.match(r"^[a-z0-9][a-z0-9_-]{0,31}$", base):
        return base
    number = 1
    while f"my{number}" in taken:
        number += 1
    return f"my{number}"


def check_recording(audio_path: str | None, script: str) -> str:
    if not audio_path:
        return ""
    try:
        qc = service.check_reference(audio_path, script)
    except UserInputError as exc:
        return f"⚠️ {exc}"
    import audio_fx

    head = "#### 녹음 검사 — ❌ 이대로는 등록되지 않습니다" if audio_fx.has_failure(qc) else "#### 녹음 검사"
    return head + "\n\n" + audio_fx.qc_text(qc)


def do_register(style_id: str, new_label: str, new_mode: bool, audio_path: str | None, script: str, selected: str, confirmed: bool):
    if not confirmed:
        return {reg_status_ref(): "등록을 취소했습니다. 지금 녹음은 그대로입니다."}
    try:
        if not audio_path:
            raise UserInputError("마이크로 녹음하거나 파일을 올리세요.")
        if new_mode:
            label = (new_label or "").strip()
            if not label:
                raise UserInputError("새 말투의 이름을 적으세요(예: 뉴스, 차분함).")
            target = _auto_style_id(label)
        else:
            target, label = style_id, None
        style = service.register_reference(target, audio_path, script, label=label)
    except UserInputError as exc:
        return {reg_status_ref(): f"⚠️ {exc}"}
    import audio_fx

    note = f"✅ '{style.label}' 말투에 녹음을 등록했습니다 · {style.duration_sec() or 0:.1f}초\n\n" + audio_fx.qc_text(style.qc or {})
    keep_selected = selected if selected in {s.id for s in voices.ready_styles()} else style.id
    return {
        reg_status_ref(): note,
        COMPONENTS["style"]: gr.update(choices=style_choices(), value=keep_selected),
        COMPONENTS["style_info"]: render_style_info(keep_selected),
        COMPONENTS["reg_style"]: gr.update(choices=register_choices(), value=style.id),
        COMPONENTS["reg_current"]: str(style.path),
        COMPONENTS["new_box"]: gr.update(visible=False),
        COMPONENTS["new_mode"]: False,
        COMPONENTS["go_make"]: gr.update(visible=True),
        COMPONENTS["trial_btn"]: gr.update(visible=True),
        COMPONENTS["empty_box"]: gr.update(visible=False),
        COMPONENTS["registered_id"]: style.id,
    }


TRIAL_TEXT = "오늘도 좋은 하루 보내세요. 궁금한 점은 언제든 물어봐 주세요."


def trial_generate(style_id: str, engine_family: str | None):
    """등록한 녹음으로 짧은 문장을 seed 0 으로 한 번 만들어 대본·녹음 불일치 징후를 본다."""
    if not style_id:
        return None, "먼저 녹음을 등록하세요."
    try:
        result = service.synthesize(TRIAL_TEXT, style_id, engine_name=engine_family, seed=0)
    except (UserInputError, RuntimeError) as exc:
        return None, f"❌ 시험 생성 실패: {exc}"
    ending = (result.quality or {}).get("ending") or {}
    if ending.get("runaways"):
        verdict = "⚠️ 문장 길이가 맞지 않아 다시 만든 적이 있습니다. 대본이 녹음과 같은지 확인하세요."
    elif ending and not ending.get("coda", True):
        verdict = "⚠️ 말끝 보정이 잘 안 됩니다(잡음·울림이 원인일 수 있음). 들어 보고 어색하면 더 조용한 곳에서 다시 녹음하세요."
    else:
        verdict = "✅ 정상입니다. 들어 보고 내 목소리와 비슷한지 확인하세요."
    return str(result.path), f"{verdict}\n\n시험 문장: {TRIAL_TEXT} · {result.duration_sec:.1f}초 · {result.engine}"


def reg_status_ref():
    return COMPONENTS["reg_status"]


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
            ".venv/bin/python voicelab_cli.py styles\n"
            "# 엔진 목록(모델 × 실행 방식, 국가·라이선스) / 모델 지정\n"
            ".venv/bin/python voicelab_cli.py engines\n"
            '.venv/bin/python voicelab_cli.py say "안녕하세요" -s talk -e chatterbox -o hello_cb.wav'
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
            f"# 모델 고르기: engine 에 qwen3 또는 chatterbox (실행 방식은 자동)\n"
            f"curl -s -X POST {url}/api/tts -H 'Content-Type: application/json' \\\n"
            "  -d '{\"text\":\"안녕하세요\",\"style\":\"talk\",\"engine\":\"chatterbox\"}' -o hello_cb.wav\n\n"
            f"# 상태·말투·엔진\n"
            f"curl -s {url}/api/health\n"
            f"curl -s {url}/api/styles\n"
            f"curl -s {url}/api/engines"
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
- “같은 대사를 **qwen3**와 **chatterbox** 두 모델로 만들어 비교할 수 있게 폴더를 나눠 줘.”

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
        f"기본 엔진: `{info['default_engine']}` · 모델 `{info['model']}` · {'메모리에 있음' if info['model_loaded'] else '첫 생성 때 불러옴'}",
        f"이 컴퓨터에서 쓸 수 있는 엔진: {', '.join(e['id'] for e in info['engines'] if e['available']) or '없음'}",
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
.vl-sub{color:var(--body-text-color-subdued);font-size:.95rem}
.vl-chips{display:flex;gap:8px;flex-wrap:wrap}
.vl-chip{font-size:.85rem;padding:4px 12px;border-radius:999px;border:1px solid var(--border-color-primary);color:var(--body-text-color)}
.vl-chip.ok{color:#166534;border-color:#86efac;background:rgba(34,197,94,.08)}
.vl-chip.busy{color:#92400e;border-color:#fcd34d;background:rgba(245,158,11,.1)}
.vl-chip.err{color:#991b1b;border-color:#fca5a5;background:rgba(239,68,68,.08)}
.vl-sec{font-size:1rem;font-weight:650;margin:2px 0 6px}
.vl-sec small{font-weight:400;color:var(--body-text-color-subdued);margin-left:6px;font-size:.88rem}
.vl-panel{border:1px solid var(--border-color-primary) !important;border-radius:14px !important;padding:14px !important;background:var(--background-fill-primary)}
.vl-banner{display:flex;flex-direction:column;gap:4px;padding:14px 16px;border-radius:12px;border:2px solid var(--color-accent);background:var(--color-accent-soft);font-size:1rem}
.vl-info{display:flex;flex-direction:column;gap:6px;margin-top:4px}
.vl-info audio{width:100%;height:36px}
.vl-hint{color:var(--body-text-color-subdued);font-size:.9rem}
.vl-desc{font-size:.9rem;color:var(--body-text-color)}
.vl-meta{font-size:.85rem;color:var(--body-text-color-subdued);margin-top:2px}
.vl-warn{color:#92400e;font-size:.88rem}
.vl-err{color:#991b1b;font-size:.85rem}
.vl-spoken{font-size:.85rem;color:var(--body-text-color-subdued)}
#vl-style .wrap{flex-direction:column !important;gap:6px !important}
#vl-style label{width:100% !important;border-radius:12px !important;padding:10px 14px !important;font-size:1.02rem !important}
#vl-text textarea{font-size:1.3rem !important;line-height:1.7 !important;min-height:150px}
#vl-go{font-size:1.1rem !important;min-height:52px}
.vl-ready{font-size:.92rem;padding:6px 2px;color:var(--body-text-color)}
.vl-empty{padding:12px;color:var(--body-text-color-subdued);font-size:.92rem}
.vl-hist{display:flex;flex-direction:column}
.vl-row{display:grid;grid-template-columns:auto minmax(0,1fr) minmax(180px,260px) auto;gap:10px;align-items:center;padding:8px 2px;border-bottom:1px solid var(--border-color-primary)}
.vl-row:last-child{border-bottom:none}
.vl-row audio{width:100%;height:34px}
.vl-row.vl-fail{grid-template-columns:auto minmax(0,1fr) minmax(0,1fr)}
.vl-tag{font-size:.8rem;padding:2px 10px;border-radius:999px;background:var(--color-accent-soft);color:var(--body-text-color);white-space:nowrap}
.vl-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vl-dl{font-size:.9rem;text-decoration:none;white-space:nowrap}
.vl-script{font-size:1.3rem;line-height:1.7;font-weight:600;padding:12px 14px;border-radius:12px;background:var(--background-fill-secondary);margin:6px 0 10px}
.vl-guide{font-size:.95rem;line-height:1.6}
.vl-guide ul{margin:4px 0 0 18px}
.vl-diagram{display:flex;align-items:stretch;gap:8px;flex-wrap:wrap;margin:6px 0 4px}
.vl-node{flex:1 1 150px;display:flex;flex-direction:column;gap:4px;justify-content:center;padding:12px 14px;border:1px solid var(--border-color-primary);border-radius:12px}
.vl-node b{font-size:.95rem}.vl-node span{font-size:.85rem;color:var(--body-text-color-subdued)}
.vl-node.accent{border:2px solid var(--color-accent);background:var(--color-accent-soft)}
.vl-node .vl-pill{display:block;padding:4px 8px;border-radius:8px;background:var(--background-fill-secondary);color:var(--body-text-color)}
.vl-node .vl-pill i{font-style:normal;color:var(--body-text-color-subdued);font-size:.8rem}
.vl-arrow{display:flex;align-items:center;font-size:1.3rem;color:var(--body-text-color-subdued)}
@media (max-width:720px){
 .vl-row{grid-template-columns:auto minmax(0,1fr)}.vl-row audio,.vl-row .vl-dl{grid-column:1/-1}
 .vl-arrow{display:none}.vl-chip{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:92vw}
 .vl-col-make{order:-1}
 .vl-head{flex-direction:column !important;align-items:flex-start !important}
}
.vl-rec{border:1px dashed var(--border-color-primary);border-radius:12px;padding:10px 12px;margin-bottom:6px}
.vl-rec-row{display:flex;align-items:center;gap:10px}
.vl-rec-btn{padding:8px 16px;border-radius:999px;border:1px solid var(--color-accent);background:var(--color-accent);color:#fff;font-weight:600;cursor:pointer}
.vl-rec-btn.on{background:#dc2626;border-color:#dc2626}
.vl-rec-time{font-variant-numeric:tabular-nums;min-width:4em}
.vl-rec-meter{flex:1;height:8px;border-radius:4px;background:var(--background-fill-secondary);overflow:hidden}
.vl-rec-meter i{display:block;height:100%;width:0;background:#94a3b8}
.vl-rec-note{font-size:.88rem;color:var(--body-text-color-subdued);margin-top:6px}
"""

THEME = gr.themes.Soft(
    primary_hue="indigo",
    neutral_hue="slate",
    font=["Pretendard", "Apple SD Gothic Neo", "system-ui", "sans-serif"],
)

RECORDER_HTML = """
<div class="vl-rec" id="vl-rec">
  <div class="vl-rec-row">
    <button type="button" class="vl-rec-btn" id="vl-rec-btn" onclick="vlRecToggle()" aria-pressed="false">● 고음질로 녹음</button>
    <span class="vl-rec-time" id="vl-rec-time" aria-live="polite">0.0초</span>
    <span class="vl-rec-meter" aria-hidden="true"><i id="vl-rec-level"></i></span>
  </div>
  <div class="vl-rec-note" id="vl-rec-note">브라우저의 잡음 제거·에코 제거·자동 음량을 끄고 압축 없이 WAV로 녹음합니다(복제에 가장 좋음). 멈추면 아래 칸에 들어가고 바로 검사합니다.</div>
</div>
"""

RECORDER_JS = """
<script>
(function(){
  const S = {stream:null, ctx:null, proc:null, chunks:[], peak:0, start:0, timer:null};
  function setNote(t){ const n=document.getElementById('vl-rec-note'); if(n) n.textContent=t; }
  function wav(samples, rate){
    const buf = new ArrayBuffer(44 + samples.length*2), v = new DataView(buf);
    const w = (o,s)=>{ for(let i=0;i<s.length;i++) v.setUint8(o+i, s.charCodeAt(i)); };
    w(0,'RIFF'); v.setUint32(4, 36+samples.length*2, true); w(8,'WAVE'); w(12,'fmt ');
    v.setUint32(16,16,true); v.setUint16(20,1,true); v.setUint16(22,1,true); v.setUint32(24,rate,true);
    v.setUint32(28,rate*2,true); v.setUint16(32,2,true); v.setUint16(34,16,true); w(36,'data'); v.setUint32(40,samples.length*2,true);
    for(let i=0;i<samples.length;i++){ const x=Math.max(-1,Math.min(1,samples[i])); v.setInt16(44+i*2, x<0?x*0x8000:x*0x7fff, true); }
    return new Blob([buf], {type:'audio/wav'});
  }
  async function start(){
    try{
      S.stream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false, noiseSuppression:false, autoGainControl:false, channelCount:1}});
    }catch(e){ setNote('마이크를 열지 못했습니다: '+e.message+' — 브라우저 주소창의 마이크 권한을 허용하거나, 음성 메모로 녹음해 파일로 올리세요.'); return; }
    S.ctx = new (window.AudioContext||window.webkitAudioContext)();
    const src = S.ctx.createMediaStreamSource(S.stream);
    S.proc = S.ctx.createScriptProcessor(4096,1,1);
    S.chunks=[]; S.peak=0;
    S.proc.onaudioprocess = e => {
      const d = new Float32Array(e.inputBuffer.getChannelData(0)); S.chunks.push(d);
      let p=0; for(const x of d){ const a=Math.abs(x); if(a>p) p=a; } S.peak=Math.max(S.peak,p);
      const lv=document.getElementById('vl-rec-level'); if(lv){ lv.style.width=Math.min(100,p*100)+'%'; lv.style.background = p>0.98?'#dc2626':(p>0.5?'#16a34a':'#94a3b8'); }
    };
    src.connect(S.proc); S.proc.connect(S.ctx.destination);
    S.start = performance.now();
    S.timer = setInterval(()=>{ const t=document.getElementById('vl-rec-time'); if(t) t.textContent=((performance.now()-S.start)/1000).toFixed(1)+'초'; }, 100);
    const b=document.getElementById('vl-rec-btn'); b.textContent='■ 멈추고 넣기'; b.setAttribute('aria-pressed','true'); b.classList.add('on');
    setNote('녹음 중… 0.5초 쉰 뒤 읽기 시작하고, 끝까지 읽은 뒤 0.5초 쉬고 멈추세요. 막대가 빨개지면 너무 큽니다.');
  }
  async function stop(){
    clearInterval(S.timer);
    S.proc.disconnect(); S.stream.getTracks().forEach(t=>t.stop());
    const rate = S.ctx.sampleRate; await S.ctx.close();
    let n=0; for(const c of S.chunks) n+=c.length; const all=new Float32Array(n); let o=0; for(const c of S.chunks){ all.set(c,o); o+=c.length; }
    const b=document.getElementById('vl-rec-btn'); b.textContent='● 다시 녹음'; b.setAttribute('aria-pressed','false'); b.classList.remove('on');
    const file = new File([wav(all, rate)], 'recording-'+Date.now()+'.wav', {type:'audio/wav'});
    const input = document.querySelector('#vl-reg-audio input[type=file]');
    if(!input){ setNote('녹음은 끝났지만 아래 칸에 넣지 못했습니다. 아래 칸의 업로드(↑) 아이콘을 눌러 업로드 모드로 바꾼 뒤 다시 녹음하세요.'); return; }
    const dt = new DataTransfer(); dt.items.add(file); input.files = dt.files;
    input.dispatchEvent(new Event('change', {bubbles:true}));
    setNote((n/rate).toFixed(1)+'초 녹음을 넣었습니다' + (S.peak>0.98?' — 소리가 찢어졌을 수 있습니다. 조금 떨어져 다시 녹음하세요.':'. 아래 검사 결과를 확인하세요.'));
  }
  window.vlRecToggle = function(){ (S.stream && S.stream.active) ? stop() : start(); };
})();
</script>
"""

CONFIRM_JS = """
(...args) => {
  const btn = document.querySelector('#vl-reg-go');
  const replacing = btn && btn.innerText.includes('바꾸기');
  const ok = !replacing || window.confirm('지금 등록된 녹음을 새 녹음으로 바꿀까요? 이전 녹음 파일은 지우지 않고 references 폴더에 남습니다.');
  args[args.length - 1] = ok;
  return args;
}
"""


def build_demo() -> gr.Blocks:
    ready = voices.ready_styles()
    initial_style = "default" if any(s.id == "default" for s in ready) else (ready[0].id if ready else None)
    snippets = agent_snippets()

    with gr.Blocks(title="내 목소리 생성기", analytics_enabled=False) as demo:
        with gr.Row(elem_classes=["vl-head"]):
            gr.HTML(
                '<div><div class="vl-title">🎙️ 내 목소리 생성기</div>'
                '<div class="vl-sub">내 녹음으로 한국어 문장을 읽게 합니다. 이 컴퓨터 안에서만 돌고, 음성이 밖으로 나가지 않습니다.</div></div>'
            )
            status_chip = gr.HTML(render_status_chip())
        consent_store = gr.BrowserState(False, storage_key="voicelab-consent", secret="voicelab-consent-v1")  # 비밀값이 아님: 서버를 다시 켜도 동의를 기억하도록 고정
        folder_state = gr.State("")
        registered_id = gr.State("")

        with gr.Tabs() as tabs:
            # ------------------------------------------------ 만들기
            with gr.Tab("만들기", id="make"):
                history_state = gr.State([])
                with gr.Column(visible=not ready) as empty_box:
                    gr.HTML(render_empty_banner())
                    to_register_first = gr.Button("🎙️ 목소리 등록하러 가기", variant="primary")
                with gr.Row(equal_height=False):
                    with gr.Column(scale=4, min_width=240, elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">말투 <small>내 녹음 중 하나를 고릅니다</small></div>')
                        style = gr.Radio(choices=style_choices(), value=initial_style, show_label=False, elem_id="vl-style")
                        style_info = gr.HTML(render_style_info(initial_style))
                        to_register = gr.Button("🎙️ 녹음 다시 하기 · 새 말투 추가", size="sm", variant="secondary")
                    with gr.Column(scale=8, elem_classes=["vl-panel", "vl-col-make"]):
                        gr.HTML('<div class="vl-sec">문장 <small>한국어로 적거나 대본을 붙여 넣으세요</small></div>')
                        text = gr.Textbox(
                            show_label=False, lines=4, max_lines=16,
                            placeholder="오늘은 인공지능으로 일상을 더 편하게 만드는 방법을 소개하겠습니다.",
                            elem_id="vl-text",
                        )
                        with gr.Row():
                            preset_buttons = [
                                gr.Button(f"예시 문장: {name}", size="sm", variant="secondary", min_width=110) for name in PRESETS
                            ]
                        mode = gr.Radio(
                            choices=[("한 덩어리(파일 1개)", "none"), ("줄마다 파일 하나", "line"), ("문장마다 파일 하나", "sentence")],
                            value="none", label="나누기",
                            info="여러 문장을 영상용으로 따로 받으려면 줄마다·문장마다. 한 덩어리는 줄바꿈을 자연스러운 쉼으로 읽습니다.",
                        )
                        with gr.Accordion("고급 설정 — 모델 · 같은 결과 다시 얻기 · 영상용 음량 · 파일 묶음", open=False):
                            engine_pick = gr.Radio(
                                choices=engine_choices(), value=default_family(), label="음성 모델",
                                info="실행 방식은 자동(맥 MLX, 윈도우 PyTorch). 바꾸면 첫 생성 때 모델을 다시 불러와 수십 초 걸립니다. "
                                "한 영상 안에서는 모델을 섞지 마세요(목소리 느낌이 달라집니다).",
                            )
                            with gr.Row():
                                seed_box = gr.Textbox(
                                    value="", label="seed(비우면 무작위)", placeholder="예: 1212032485",
                                    info="결과마다 seed 가 표시됩니다. 같은 seed 면 같은 결과가 다시 나옵니다.",
                                )
                                loud = gr.Checkbox(value=False, label="영상용 음량으로 맞추기(-16 LUFS)", info="문장마다 음량이 고르게. 유튜브·교육 영상에 맞춤")
                                hq = gr.Checkbox(value=False, label="48kHz로 저장", info="영상 편집 프로젝트와 같은 표본율")
                            speed_pick = gr.Slider(
                                minimum=0.8, maximum=1.25, step=0.05, value=1.0, label="말 빠르기",
                                info="1 = 그대로. 음높이는 그대로 두고 빠르기만 바꿉니다(화면 전환에 맞출 때).",
                            )
                            with gr.Row():
                                project = gr.Textbox(
                                    label="여러 파일 폴더 이름", placeholder="비우면 narration-날짜-시각",
                                    info="outputs/projects/<이름>/ 에 001_문장.wav 순서로 저장. 같은 이름이면 바뀐 문장만 다시 만듭니다.",
                                )
                                timeline_on = gr.Checkbox(
                                    value=True, label="이어 붙인 WAV·자막(SRT)·편집 마커(CSV)도 만들기",
                                    info="문장 사이 0.4초, 빈 줄로 나눈 문단 사이 1초를 쉽니다.",
                                )
                        with gr.Accordion("발음 고치기 — 잘못 읽는 단어를 소리 나는 대로", open=False):
                            gr.Markdown(
                                "예: `배지` → `뺏지`. 화면·API·명령줄에 모두 적용됩니다. 영문은 단어 단위로 바꿉니다(`AI`를 넣어도 `OpenAI`는 그대로). "
                                "문장 안에 `[뺏지]`처럼 대괄호로 소리를 바로 적어도 됩니다."
                            )
                            lexicon = gr.Dataframe(
                                value=load_lexicon_rows(), headers=["원문", "읽을 소리"], column_count=(2, "fixed"),
                                interactive=True, row_count=(1, "dynamic"),
                            )
                            with gr.Row():
                                lex_go = gr.Button("발음 사전 저장", size="sm")
                                preview_btn = gr.Button("읽을 문장 미리 보기(생성 안 함)", size="sm", variant="secondary")
                            lex_status = gr.Markdown("")
                        ready_line = gr.HTML(render_readiness("", "none", initial_style, False))
                        with gr.Row(equal_height=True):
                            consent = gr.Checkbox(
                                value=False, label=CONSENT_LABEL, scale=3,
                                info="체크하면 이 브라우저가 기억합니다.",
                            )
                            go = gr.Button("▶ 만들기", variant="primary", scale=2, elem_id="vl-go", interactive=False)
                        stop_btn = gr.Button("⏹ 멈추기(지금 문장까지 만들고 멈춤)", variant="stop", size="sm", visible=False)
                        gen_status = gr.Markdown("", elem_id="vl-status")
                        result_audio = gr.Audio(
                            show_label=False, type="filepath", interactive=False, autoplay=True, buttons=["download"],
                        )
                        with gr.Row():
                            result_dl = gr.DownloadButton("⬇ WAV 받기", visible=False, size="sm")
                            again = gr.Button("🔁 같은 문장 다른 버전", visible=False, size="sm", variant="secondary")
                        with gr.Column(visible=False) as batch_box:
                            gr.HTML('<div class="vl-sec">여러 파일 결과 <small>번호 순서 = 대본 순서</small></div>')
                            batch_html = gr.HTML("")
                            batch_files = gr.File(label="한 번에 받기(zip · 이어 붙인 WAV · 자막 SRT)", file_count="multiple", interactive=False)
                            with gr.Row():
                                open_btn = gr.Button("📂 폴더 열기", size="sm", visible=False)
                                retake = gr.Textbox(
                                    label="다른 버전으로 다시 만들 번호", placeholder="예: 3, 7", scale=2,
                                    info="그 번호만 새로 만들고 나머지는 그대로 둡니다. 이전 버전은 폴더의 .voicelab-cache 에 남습니다.",
                                )
                                retake_btn = gr.Button("이 번호만 다시 만들기", size="sm")
                            open_status = gr.Markdown("")
                with gr.Column(elem_classes=["vl-panel"]):
                    gr.HTML('<div class="vl-sec">지난 결과 <small>이번에 연 화면에서 만든 것</small></div>')
                    history_html = gr.HTML(render_history([]))
                    with gr.Accordion("이전 프로젝트 불러오기 — 여러 파일로 만든 폴더", open=False):
                        with gr.Row():
                            project_pick = gr.Dropdown(choices=list_projects(), label="프로젝트", scale=3, allow_custom_value=False)
                            project_refresh = gr.Button("목록 새로 고침", size="sm", scale=1)
                            project_load = gr.Button("불러오기", size="sm", variant="secondary", scale=1)

            # ------------------------------------------------ 목소리 등록
            with gr.Tab("목소리 등록", id="register"):
                first_id = initial_style or "default"
                first = reg_info(first_id)
                with gr.Row(equal_height=False):
                    with gr.Column(scale=5, elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">1. 말투 고르기</div>')
                        reg_style = gr.Radio(choices=register_choices(), value=first_id, show_label=False)
                        new_btn = gr.Button("+ 새 말투 만들기", size="sm", variant="secondary")
                        new_mode = gr.State(False)
                        with gr.Column(visible=False) as new_box:
                            new_label = gr.Textbox(label="새 말투 이름", placeholder="예: 뉴스, 차분함, 강의")
                            gr.Markdown("읽을 문장은 오른쪽 칸에 직접 적으세요(5–15초 분량).")
                        gr.HTML('<div class="vl-sec" style="margin-top:8px">지금 등록된 녹음</div>')
                        reg_current = gr.Audio(value=first[2], type="filepath", interactive=False, show_label=False)
                        reg_current_note = gr.Markdown(first[3])
                        gr.HTML(RECORDING_GUIDE)
                    with gr.Column(scale=6, elem_classes=["vl-panel"]):
                        reg_guide = gr.Markdown(first[0])
                        gr.HTML('<div class="vl-sec">2. 녹음하거나 파일 올리기 <small>WAV·M4A(아이폰 음성 메모)·MP3</small></div>')
                        gr.HTML(RECORDER_HTML)
                        reg_audio = gr.Audio(
                            sources=["upload", "microphone"], type="filepath", show_label=False, elem_id="vl-reg-audio",
                        )
                        reg_check = gr.Markdown("", elem_id="vl-check")
                        gr.HTML('<div class="vl-sec">3. 녹음에서 실제로 읽은 문장 <small>틀리게 읽었다면 읽은 그대로 고치세요</small></div>')
                        reg_script = gr.Textbox(value=first[1], show_label=False, lines=3)
                        reg_confirm = gr.Checkbox(value=True, visible=False)
                        reg_go = gr.Button(first[4]["value"], variant="primary", elem_id="vl-reg-go")
                        reg_status = gr.Markdown("", elem_id="vl-reg-status")
                        with gr.Row():
                            trial_btn = gr.Button("🔊 이 녹음으로 시험 문장 만들어 듣기", visible=False, size="sm")
                            go_make = gr.Button("이 말투로 만들러 가기 →", visible=False, variant="secondary", size="sm")
                        trial_audio = gr.Audio(type="filepath", interactive=False, show_label=False, autoplay=True)
                        trial_note = gr.Markdown("")

            # ------------------------------------------------ 에이전트·MCP
            with gr.Tab("고급 · 에이전트 연결", id="agent"):
                with gr.Column(elem_classes=["vl-panel"]):
                    gr.HTML(
                        '<div class="vl-sec">AI 에이전트가 내 목소리로 대사를 만들게 하기 '
                        "<small>영상 내레이션 대사를 한꺼번에 뽑을 때 편합니다</small></div>"
                    )
                    gr.HTML(AGENT_DIAGRAM)
                    with gr.Accordion("엔진 목록 — 모델 × 실행 방식, 개발 주체 국가·라이선스", open=False):
                        gr.Markdown(render_engine_table())
                    check = gr.Button("연결 확인", size="sm", variant="secondary")
                    check_out = gr.Markdown("")
                with gr.Row(equal_height=False):
                    with gr.Column(elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">1. MCP로 연결 <small>에이전트가 도구로 바로 씁니다(추천)</small></div>')
                        gr.Markdown("**Claude Code** — 터미널에서 한 번 실행:")
                        gr.Code(snippets["claude"], language="shell", interactive=False, show_label=False, wrap_lines=True)
                        gr.Markdown("**Cursor · Claude Desktop** — `mcp.json`(또는 설정 파일)의 `mcpServers`에 추가:")
                        gr.Code(snippets["json"], language="json", interactive=False, show_label=False, wrap_lines=True)
                        gr.Markdown("**Codex** — `~/.codex/config.toml`에 추가:")
                        gr.Code(snippets["codex"], language="shell", interactive=False, show_label=False, wrap_lines=True)
                        gr.Markdown(
                            "도구: `list_styles` 말투 목록 · `speak` 문장 하나 · `speak_batch` 대사 여러 개 · `health` 상태"
                        )
                    with gr.Column(elem_classes=["vl-panel"]):
                        gr.Markdown(AGENT_PROMPTS)
                with gr.Row(equal_height=False):
                    with gr.Column(elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">2. 명령줄 <small>스크립트·영상 파이프라인에서</small></div>')
                        gr.Code(snippets["cli"], language="shell", interactive=False, show_label=False, wrap_lines=True)
                        gr.Markdown("`lines.json` 예시(문자열 목록, `.txt` 줄 목록도 됩니다):")
                        gr.Code(snippets["lines"], language="json", interactive=False, show_label=False, wrap_lines=True)
                    with gr.Column(elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">3. HTTP API <small>어떤 언어에서든</small></div>')
                        gr.Code(snippets["curl"], language="shell", interactive=False, show_label=False, wrap_lines=True)
                        gr.Code(snippets["python"], language="python", interactive=False, show_label=False, wrap_lines=True)
                    with gr.Column(elem_classes=["vl-panel"]):
                        gr.HTML('<div class="vl-sec">파일 위치</div>')
                        gr.Markdown(
                            f"- 녹음: `{local_env.REFERENCES.resolve()}`\n"
                            f"- 결과: `{local_env.OUTPUTS.resolve()}`\n"
                            f"- 모델 캐시: `{local_env.HF_HUB_CACHE.resolve()}`\n\n"
                            "모두 이 컴퓨터에만 있습니다. 녹음과 결과는 git에 올라가지 않도록 막혀 있습니다."
                        )

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

        COMPONENTS.update(
            gen_status=gen_status, status_chip=status_chip, result_audio=result_audio, result_dl=result_dl, again=again,
            history_html=history_html, history_state=history_state, batch_box=batch_box, batch_html=batch_html,
            batch_files=batch_files, folder_state=folder_state, open_btn=open_btn, style=style, style_info=style_info,
            reg_style=reg_style, reg_current=reg_current, new_box=new_box, new_mode=new_mode, go_make=go_make,
            empty_box=empty_box, registered_id=registered_id, reg_status=reg_status, project=project,
            trial_btn=trial_btn,
        )
        gen_outputs = [
            gen_status, status_chip, result_audio, result_dl, again, history_html, history_state,
            batch_box, batch_html, batch_files, folder_state, open_btn,
        ]
        private = {"api_visibility": "private"}

        # ------------------------------------------------ 이벤트
        timer = gr.Timer(2.0)
        timer.tick(render_status_chip, outputs=[status_chip], queue=False, show_progress="hidden", **private)

        readiness_inputs = [text, mode, style, consent]
        for comp in (text, mode, consent):
            comp.change(render_readiness, inputs=readiness_inputs, outputs=[ready_line], queue=False, show_progress="hidden", **private)
        style.change(
            lambda t, m, s, c: (render_readiness(t, m, s, c), render_style_info(s)),
            inputs=readiness_inputs, outputs=[ready_line, style_info], queue=False, show_progress="hidden", **private,
        )
        # 동의는 이 브라우저에 기억한다
        demo.load(lambda v: bool(v), inputs=[consent_store], outputs=[consent], queue=False, **private)
        consent.change(lambda v: (v, gr.update(interactive=bool(v))), inputs=[consent], outputs=[consent_store, go], queue=False, **private)

        for button, name in zip(preset_buttons, PRESETS):
            button.click(lambda cur, n=name: on_preset(n, cur), inputs=[text], outputs=[text, style], queue=False, **private)
        for button in (to_register, to_register_first):
            button.click(lambda: gr.Tabs(selected="register"), outputs=[tabs], queue=False, **private)

        def lock():
            return gr.update(interactive=False, value="만드는 중…"), gr.update(visible=True), gr.update(interactive=False)

        def unlock(consent_value):
            return gr.update(interactive=bool(consent_value), value="▶ 만들기"), gr.update(visible=False), gr.update(interactive=True)

        gen_inputs = [consent, style, text, mode, engine_pick, seed_box, loud, hq, speed_pick, project, timeline_on]
        for trigger, with_retake in ((go, False), (again, False), (retake_btn, True)):
            trigger.click(lock, outputs=[go, stop_btn, again], queue=False, **private).then(
                (lambda *a: (yield from generate(*a))) if with_retake else
                (lambda *a: (yield from generate(*a[:-1], "", a[-1]))),
                inputs=gen_inputs + ([retake] if with_retake else []) + [history_state],
                outputs=gen_outputs, show_progress="hidden", concurrency_limit=1, concurrency_id="tts", **private,
            ).then(unlock, inputs=[consent], outputs=[go, stop_btn, again], queue=False, **private)
        stop_btn.click(lambda: (STOP.set(), "⏹ 멈추는 중입니다. 지금 만드는 문장까지 끝내고 멈춥니다.")[1],
                       outputs=[gen_status], queue=False, **private)
        open_btn.click(open_folder, inputs=[folder_state], outputs=[open_status], queue=False, **private)
        lex_go.click(save_lexicon_rows, inputs=[lexicon], outputs=[lex_status], **private)
        preview_btn.click(preview_spoken, inputs=[text, engine_pick], outputs=[lex_status], queue=False, **private)

        reg_style.change(
            reg_info, inputs=[reg_style], outputs=[reg_guide, reg_script, reg_current, reg_current_note, reg_go],
            queue=False, **private,
        ).then(lambda: (False, gr.update(visible=False)), outputs=[new_mode, new_box], queue=False, **private)
        new_btn.click(
            lambda: (True, gr.update(visible=True), "", "#### 새 말투\n5–15초 분량으로 읽을 문장을 정해 아래 3번 칸에 그대로 적고 녹음하세요.",
                     None, "아직 녹음이 없습니다.", gr.update(value="이 녹음으로 등록")),
            outputs=[new_mode, new_box, reg_script, reg_guide, reg_current, reg_current_note, reg_go], queue=False, **private,
        )
        reg_audio.change(check_recording, inputs=[reg_audio, reg_script], outputs=[reg_check], **private)
        reg_script.blur(check_recording, inputs=[reg_audio, reg_script], outputs=[reg_check], **private)
        reg_go.click(
            do_register,
            inputs=[reg_style, new_label, new_mode, reg_audio, reg_script, style, reg_confirm],
            outputs=[reg_status, style, style_info, reg_style, reg_current, new_box, new_mode, go_make, empty_box, registered_id, trial_btn],
            js=CONFIRM_JS, concurrency_limit=1, **private,
        ).then(
            lambda t, m, s, c: render_readiness(t, m, s, c), inputs=readiness_inputs, outputs=[ready_line], queue=False, **private,
        )
        go_make.click(
            lambda sid: (gr.Tabs(selected="make"), gr.update(value=sid) if sid else gr.update()),
            inputs=[registered_id], outputs=[tabs, style], queue=False, **private,
        )
        check.click(check_connection, outputs=[check_out], queue=False, **private)
        trial_btn.click(
            lambda: gr.update(interactive=False, value="만드는 중…"), outputs=[trial_btn], queue=False, **private,
        ).then(
            trial_generate, inputs=[registered_id, engine_pick], outputs=[trial_audio, trial_note],
            concurrency_limit=1, concurrency_id="tts", **private,
        ).then(lambda: gr.update(interactive=True, value="🔊 이 녹음으로 시험 문장 만들어 듣기"), outputs=[trial_btn], queue=False, **private)
        project_refresh.click(lambda: gr.update(choices=list_projects()), outputs=[project_pick], queue=False, **private)
        project_load.click(
            load_project, inputs=[project_pick],
            outputs=[gen_status, batch_box, batch_html, batch_files, folder_state, open_btn, project], **private,
        )

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
            if sys.platform != "win32":
                # 방금 끈 서버의 연결이 TIME_WAIT 로 남아 있어도 다시 쓸 수 있다(uvicorn 도 같은 설정). 실제로
                # 다른 프로그램이 듣고 있으면 여전히 실패한다.
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
        head=RECORDER_JS,
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
    app = create_app()
    print(f"화면: {SERVER['url']}", flush=True)
    print(f"API 문서: {SERVER['url']}/docs", flush=True)
    default = backends.default_engine_id()
    print(f"기본 엔진: {default} — 쓸 수 있는 엔진: {', '.join(backends.available_ids()) or '없음'} (첫 생성 때 불러옵니다)", flush=True)
    print("외부 공유는 켜지 않습니다. 이 컴퓨터에서만 열립니다.", flush=True)
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(SERVER["url"])).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
