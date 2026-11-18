"""HTTP API (FastAPI). 화면과 같은 서버(기본 127.0.0.1:7860)에 붙는다.

요청·응답 형식은 docs/API.md 에 정리했다. api_version 이 같으면 형식을 깨지 않는다.
"""

from __future__ import annotations

import base64
import io
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

import audio_prep
import local_env
import service
import voices
from audio_prep import UserInputError

router = APIRouter()


class TTSRequest(BaseModel):
    text: str = Field(..., description="읽을 문장")
    style: str | None = Field(None, description="말투 id 또는 이름. 예: talk, 대화, '대화(talk)'")
    style_id: str | None = Field(None, description="style 의 다른 이름(예전 호출 호환)")
    voice: str | None = Field(None, description="style 의 다른 이름")
    engine: str | None = Field(
        None,
        description="모델: qwen3·chatterbox(이 컴퓨터에서 가장 빠른 실행 방식 자동) 또는 정확한 엔진 id(qwen3-mlx, chatterbox-torch 등). 없으면 기본 엔진",
    )
    format: Literal["wav", "json", "base64"] = "wav"
    seed: int | None = None
    replace: dict[str, str] | None = Field(None, description="이번 요청에만 쓰는 발음 치환 {원문: 소리}")
    use_lexicon: bool = Field(True, description="lexicon.json 발음 사전을 적용할지")
    ref_text: str | None = Field(None, description="참조 녹음 대본을 이번에만 바꿀 때")
    output_path: str | None = Field(None, description="결과를 쓸 경로(서버와 같은 컴퓨터). 없으면 outputs/")
    speed: float | None = Field(None, description="말 빠르기 0.8–1.25(음높이는 그대로). 1 = 그대로, 1.1 = 10% 빠르게")
    loudness: float | None = Field(None, description="통합 음량(LUFS)으로 맞춤. 예: -16(영상), -14(유튜브). 없으면 모델 출력 그대로")
    sample_rate: int | None = Field(None, description="저장 표본율. 예: 48000(영상 편집). 없으면 모델 그대로(24000)")

    def style_name(self) -> str | None:
        return self.style or self.style_id or self.voice


class BatchRequest(BaseModel):
    items: list[Any] = Field(..., description='["문장", ...] 또는 [{"id","text","style","seed","replace"}, ...]')
    style: str | None = None
    engine: str | None = Field(None, description="항목에 engine 이 없을 때 쓸 모델·엔진")
    replace: dict[str, str] | None = None
    out_dir: str | None = Field(None, description="결과 폴더(서버 컴퓨터). 없으면 outputs/batch-시각")
    skip_existing: bool = True
    format: Literal["json", "zip"] = "json"
    loudness: float | None = Field(None, description="모든 문장을 같은 통합 음량(LUFS)으로. 예: -16")
    sample_rate: int | None = Field(None, description="저장 표본율. 예: 48000")
    prune: bool = Field(False, description="이번 목록에 없는 예전 파일을 _stale/ 로 옮김")
    timeline: bool = Field(False, description="이어 붙인 narration.wav 와 자막 narration.srt 도 만듦")
    gap_sec: float = Field(0.4, description="timeline 에서 문장 사이 쉼(초)")
    paragraph_gap_sec: float = Field(1.0, description="timeline 에서 문단(항목의 paragraph 번호가 바뀜) 사이 쉼(초)")
    speed: float | None = Field(None, description="말 빠르기 0.8–1.25(음높이는 그대로)")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), None
    except UserInputError as exc:
        return None, _error(400, str(exc))
    except Exception as exc:  # 모델·메모리 오류도 숨기지 않고 돌려준다.
        return None, _error(500, f"{type(exc).__name__}: {exc}")


def _file_url(path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(local_env.OUTPUTS.resolve())
    except ValueError:
        return None
    return f"/api/files/{rel.as_posix()}"


def _tts_response(req: TTSRequest):
    result, err = _run(
        service.synthesize,
        req.text,
        req.style_name(),
        output_path=req.output_path,
        seed=req.seed,
        engine_name=req.engine,
        replace=req.replace,
        use_lexicon=req.use_lexicon,
        ref_text=req.ref_text,
        loudness=req.loudness,
        sample_rate=req.sample_rate,
        speed=req.speed,
    )
    if err is not None:
        return err
    data = result.to_dict()
    data["url"] = _file_url(result.path)
    if req.format == "json":
        return data
    if req.format == "base64":
        data["audio_base64"] = base64.b64encode(result.path.read_bytes()).decode("ascii")
        return data
    headers = {
        # 헤더는 ASCII 만 되므로 퍼센트 인코딩한다(urllib.parse.unquote 로 되돌림).
        "X-Output-Path": quote(str(result.path)),
        "X-Output-File": quote(result.path.name),
        "X-Duration-Sec": f"{result.duration_sec:.3f}",
        "X-Sample-Rate": str(result.sample_rate),
        "X-Style": result.style,
        "X-Engine": result.engine,
    }
    return Response(result.path.read_bytes(), media_type="audio/wav", headers=headers)


@router.get("/api/health")
def health():
    return service.health()


@router.get("/api/styles")
def styles():
    return {"ok": True, "styles": [s.public_dict() for s in voices.list_styles()]}


@router.get("/api/engines")
def engines(refresh: bool = False):
    """엔진(모델 × 실행 방식) 목록. 개발 주체 국가·라이선스·이 컴퓨터에서 쓸 수 있는지."""
    import backends

    return {
        "ok": True,
        "platform": backends.current_platform(),
        "default_engine": backends.default_engine_id(),
        "engines": backends.all_status(refresh=refresh),
    }


class DefaultEngine(BaseModel):
    engine: str


@router.put("/api/engines/default")
def set_default_engine(body: DefaultEngine):
    import backends
    import engine as engine_mod

    try:
        engine_id = engine_mod.resolve_engine(body.engine)
    except engine_mod.ModelDisabled as exc:
        return _error(400, str(exc))
    backends.save_settings({"default_engine": engine_id})
    return {"ok": True, "default_engine": engine_id}


@router.post("/api/tts")
def tts(req: TTSRequest):
    return _tts_response(req)


@router.post("/tts")
async def tts_compat(request: Request):
    """간단한 HTTP 호출용 별칭. JSON {"text": ..., "style": ...} → WAV 본문.

    form 데이터나 ?text= 쿼리도 받는다. speed 는 받기만 한다.
    """
    payload: dict[str, Any] = dict(request.query_params)
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            body = await request.json()
        except ValueError:
            return _error(400, "JSON 본문을 읽지 못했습니다.")
        if isinstance(body, dict):
            payload.update(body)
    elif "form" in ctype:
        form = await request.form()
        payload.update({k: v for k, v in form.items() if isinstance(v, str)})
    if not payload.get("text"):
        return _error(400, "text 가 필요합니다.")
    try:
        req = TTSRequest(**{k: v for k, v in payload.items() if k in TTSRequest.model_fields})
    except Exception as exc:
        return _error(400, f"요청 형식 오류: {exc}")
    if req.speed is not None:  # 일반 TTS 클라이언트 호환: 범위를 넘으면 오류 대신 가장 가까운 값으로
        req.speed = min(1.25, max(0.8, float(req.speed)))
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(_tts_response, req)


@router.post("/api/batch")
def batch(req: BatchRequest):
    items, err = _run(
        service.parse_items,
        {"items": req.items, "style": req.style, "engine": req.engine, "replace": req.replace or {}},
    )
    if err is not None:
        return err
    try:
        for item in items:
            voices.resolve(item.style)
    except UserInputError as exc:
        return _error(400, str(exc))
    out_dir = req.out_dir
    temp_dir = None
    if req.format == "zip" and not out_dir:
        temp_dir = tempfile.mkdtemp(prefix="voicelab-batch-")
        out_dir = temp_dir
    if not out_dir:
        out_dir = str(local_env.OUTPUTS / f"batch-{datetime.now().strftime('%Y%m%dT%H%M%S')}")
    summary, err = _run(
        service.run_batch, items, out_dir, skip_existing=req.skip_existing, loudness=req.loudness,
        sample_rate=req.sample_rate, prune=req.prune, timeline=req.timeline, gap_sec=req.gap_sec,
        paragraph_gap_sec=req.paragraph_gap_sec, speed=req.speed,
    )
    if err is not None:
        return err
    for entry in summary["items"]:
        if entry.get("path"):
            entry["url"] = _file_url(Path(entry["path"]))
    if req.format == "json":
        return summary
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in summary["items"]:
            if entry.get("ok") and entry.get("path"):
                archive.write(entry["path"], arcname=Path(entry["path"]).name)
        archive.write(summary["manifest"], arcname="manifest.json")
        for extra in ("narration_wav", "narration_srt", "narration_markers"):
            if summary.get(extra):
                archive.write(summary[extra], arcname=Path(summary[extra]).name)
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)
    headers = {"X-Succeeded": str(summary["succeeded"]), "X-Failed": str(summary["failed"])}
    return Response(buffer.getvalue(), media_type="application/zip", headers=headers)


@router.get("/api/references/{style}/audio")
def reference_audio(style: str):
    """등록된 말투의 참조 녹음(화면의 미리 듣기용)."""
    try:
        chosen = voices.resolve(style)
    except UserInputError:
        raise HTTPException(status_code=404)
    path = chosen.path
    if path is None or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="audio/wav")


@router.get("/api/files/{name:path}")
def files(name: str):
    target = (local_env.OUTPUTS / name).resolve()
    try:
        target.relative_to(local_env.OUTPUTS.resolve())
    except ValueError:
        raise HTTPException(status_code=404)
    if not target.is_file() or target.suffix.lower() != ".wav":
        raise HTTPException(status_code=404)
    return FileResponse(target, media_type="audio/wav", filename=target.name)


@router.post("/api/references")
def register_reference(
    style: str = Form(..., description="말투 id. 기본 4종(default/talk/guide/joy) 또는 새 id"),
    script: str = Form(..., description="녹음에서 실제로 읽은 문장"),
    file: UploadFile = File(..., description="WAV 또는 M4A"),
    label: str | None = Form(None),
    description: str | None = Form(None),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in audio_prep.ALLOWED_SUFFIXES:
        return _error(400, "WAV·M4A·MP3·AIFF·CAF·FLAC 파일만 받습니다.")
    with tempfile.TemporaryDirectory(prefix="voicelab-ref-") as tmp:
        src = Path(tmp) / f"upload{suffix}"
        with src.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        style_obj, err = _run(
            service.register_reference, style, src, script, label=label, description=description
        )
    if err is not None:
        return err
    return {"ok": True, "style": style_obj.public_dict(), "qc": style_obj.qc}


@router.post("/api/references/check")
def check_reference(
    file: UploadFile = File(..., description="WAV 또는 M4A"),
    script: str | None = Form(None, description="녹음에서 읽은 문장(주면 대본·녹음 맞춤도 검사)"),
):
    """등록하지 않고 녹음 상태만 검사한다(길이·대본 맞춤·잡음·찢어짐·끝 잘림·음질)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in audio_prep.ALLOWED_SUFFIXES:
        return _error(400, "WAV·M4A·MP3·AIFF·CAF·FLAC 파일만 받습니다.")
    with tempfile.TemporaryDirectory(prefix="voicelab-check-") as tmp:
        src = Path(tmp) / f"upload{suffix}"
        with src.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        qc, err = _run(service.check_reference, src, script)
    if err is not None:
        return err
    import audio_fx

    return {"ok": not audio_fx.has_failure(qc), "qc": qc}


@router.get("/api/lexicon")
def get_lexicon():
    return {"ok": True, "replace": service.load_lexicon()}


@router.put("/api/lexicon")
def put_lexicon(body: dict[str, str]):
    service.save_lexicon(body)
    return {"ok": True, "replace": service.load_lexicon()}
