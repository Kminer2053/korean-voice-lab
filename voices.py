"""말투(참조 음성) 레지스트리.

말투 하나 = 참조 녹음 WAV 한 개 + 그 녹음에서 실제로 읽은 문장(대본).
생성할 때는 고른 말투의 녹음 하나와 대본만 모델에 넘긴다. 녹음을 이어 붙이지 않는다.

등록 정보는 references/voices.json 에 저장한다(개인 자료이므로 git에 올리지 않는다).
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

import local_env
import audio_prep
from audio_prep import UserInputError

VOICES_PATH = local_env.REFERENCES / "voices.json"
_LOCK = threading.Lock()
STYLE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class BuiltinStyle:
    id: str
    label: str
    script: str
    prosody: str
    description: str
    legacy_script: str = ""  # 예전 기본 대본. 대본 칸 없이 저장된 예전 등록은 이것을 읽었다고 본다.


# 기본 말투 4종. 대본은 녹음할 때 읽을 권장 문장이다(8–12초 분량, 받침·된소리·거센소리·이중모음을 고루).
BUILTIN_STYLES: tuple[BuiltinStyle, ...] = (
    BuiltinStyle(
        "default",
        "기본",
        "오늘은 집에 들어와서 창문을 열어 두었어요. 바람이 시원해서 한참 그냥 서 있었어요. "
        "저녁에는 따뜻한 보리차를 끓여 마시고, 읽다 만 책을 끝까지 펼쳐 봤습니다.",
        "또박또박, 평소 속도로 읽습니다. 끝을 올리거나 감정을 싣지 않습니다.",
        "담담한 평서문. 음색 기준.",
        "오늘은 집에 들어와서 창문을 열어 두었어요. 바람이 시원해서 한참 그냥 서 있었어요.",
    ),
    BuiltinStyle(
        "talk",
        "대화",
        "저녁은 뭐 먹을까요? 시장에 잠깐 같이 나가 볼까요? 요즘 떡볶이 집이 새로 생겼다던데, "
        "줄이 꽤 길대요. 그래도 한번 가 봐요, 궁금하잖아요.",
        "대화하듯 읽습니다. 질문의 끝은 올립니다.",
        "말을 거는 듯한 구어체. 쿠키 영상·브이로그.",
        "저녁은 뭐 먹을까요? 시장에 잠깐 같이 나가 볼까요?",
    ),
    BuiltinStyle(
        "guide",
        "안내",
        "내일 아침에는 병원에 들렀다가 시장에 갑니다. 주차는 건물 뒷문이 더 편합니다. "
        "접수는 아홉 시부터이고, 진료 카드는 의자 옆 창구에 내시면 됩니다.",
        "차근차근 알려 주듯 읽습니다. 서두르거나 들뜨지 않습니다.",
        "차분한 설명조. 발표·강의 내레이션.",
        "내일 아침에는 병원에 들렀다가 시장에 갑니다. 주차는 건물 뒷문이 더 편합니다.",
    ),
    BuiltinStyle(
        "joy",
        "기쁨",
        "정말요? 그 소식 사실이에요? 와, 너무 반가워요. 이런 날이 오다니요! "
        "다 같이 축하하러 꼭 모여요. 케이크는 제가 쏠게요.",
        "반갑고 조금 놀란 톤으로 읽습니다. 처음부터 끝까지 한 톤으로 눕히지 않습니다.",
        "밝고 들뜬 감정 표현.",
        "정말요? 그 소식 사실이에요? 와, 너무 반가워요. 이런 날이 오다니요.",
    ),
)
BUILTIN_BY_ID = {style.id: style for style in BUILTIN_STYLES}
# 예전 화면의 역할 이름(timbre/question/…)도 받는다.
LEGACY_ALIASES = {"timbre": "default", "question": "talk"}


@dataclass(frozen=True)
class Style:
    id: str
    label: str
    file: str  # references/ 안의 파일 이름. 비어 있으면 미등록.
    script: str  # 녹음에서 실제로 읽은 문장
    prosody: str = ""
    description: str = ""
    builtin: bool = False
    qc: dict | None = None  # 등록할 때 녹음 검사 결과(audio_fx.analyse_reference)

    @property
    def path(self) -> Path | None:
        if not self.file:
            return None
        return local_env.REFERENCES / Path(self.file).name

    @property
    def ready(self) -> bool:
        path = self.path
        # 대본은 엔진에 따라 필요하다(Qwen3 필요, Chatterbox 불필요). 녹음만 있으면 준비된 것으로 본다.
        return path is not None and usable_reference(path)

    def duration_sec(self) -> float | None:
        path = self.path
        if path is None or not path.is_file():
            return None
        try:
            duration, _rate, _rms = audio_prep._wav_stats(path)
        except UserInputError:
            return None
        return duration

    def public_dict(self) -> dict:
        data = asdict(self)
        data["ready"] = self.ready
        data["duration_sec"] = self.duration_sec()
        return data


def usable_reference(path: Path) -> bool:
    if audio_prep.reference_kind(path) == "system-say-fixture":
        return False
    if not path.is_file() or path.resolve().parent != local_env.REFERENCES.resolve():
        return False
    try:
        duration, _rate, rms = audio_prep._wav_stats(path)
    except (OSError, UserInputError):
        return False
    return duration > 0 and rms >= audio_prep.NEAR_SILENCE_RMS


def _read_raw() -> dict:
    if not VOICES_PATH.is_file():
        return {}
    try:
        data = json.loads(VOICES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    styles = data.get("styles") if isinstance(data, dict) else None
    return styles if isinstance(styles, dict) else {}


def _write_raw(styles: dict) -> None:
    VOICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = VOICES_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"version": 1, "styles": styles}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(VOICES_PATH)


def list_styles() -> list[Style]:
    """기본 말투 4종(미등록 포함) + 사용자가 추가한 말투."""
    raw = _read_raw()
    result: list[Style] = []
    for builtin in BUILTIN_STYLES:
        entry = raw.get(builtin.id) or {}
        result.append(
            Style(
                id=builtin.id,
                label=str(entry.get("label") or builtin.label),
                file=str(entry.get("file") or ""),
                # 대본 칸이 있는 기록은 그대로 쓴다(빈 대본을 읽지 않은 기본 대본으로 바꾸지 않음).
                # 예전 기록(대본 칸 없음)만 기본 대본을 읽었다고 본다.
                script=str(entry["script"] if "script" in entry else (builtin.legacy_script or builtin.script)) if entry.get("file") else builtin.script,
                prosody=builtin.prosody,
                description=builtin.description,
                builtin=True,
                qc=entry.get("qc") if isinstance(entry.get("qc"), dict) else None,
            )
        )
    for style_id, entry in raw.items():
        if style_id in BUILTIN_BY_ID or not isinstance(entry, dict):
            continue
        if not STYLE_ID_PATTERN.match(style_id):
            continue
        result.append(
            Style(
                id=style_id,
                label=str(entry.get("label") or style_id),
                file=str(entry.get("file") or ""),
                script=str(entry.get("script") or ""),
                prosody=str(entry.get("prosody") or ""),
                description=str(entry.get("description") or ""),
                builtin=False,
                qc=entry.get("qc") if isinstance(entry.get("qc"), dict) else None,
            )
        )
    return result


def resolve(name: str | None) -> Style:
    """id(talk), 이름(대화), '대화(talk)' 형식, 예전 역할 이름을 모두 받는다."""
    key = (name or "default").strip()
    match = re.search(r"\(([^()]+)\)\s*$", key)
    candidates = [key]
    if match:
        candidates.insert(0, match.group(1).strip())
        candidates.append(key[: match.start()].strip())
    styles = list_styles()
    for cand in candidates:
        low = cand.lower()
        low = LEGACY_ALIASES.get(low, low)
        for style in styles:
            if style.id == low or style.label == cand:
                return style
    known = ", ".join(f"{s.id}({s.label})" for s in styles)
    raise UserInputError(f"말투 '{name}'를 찾지 못했습니다. 쓸 수 있는 말투: {known}")


def register(
    style_id: str,
    wav_path: Path,
    script: str,
    *,
    label: str | None = None,
    description: str | None = None,
    qc: dict | None = None,
) -> Style:
    """참조 녹음을 말투에 연결한다. wav_path 는 references/ 안의 준비된 WAV 여야 한다."""
    style_id = (style_id or "").strip().lower()
    style_id = LEGACY_ALIASES.get(style_id, style_id)
    if not STYLE_ID_PATTERN.match(style_id):
        raise UserInputError("말투 ID는 영문 소문자·숫자·-·_ 로 1–32자여야 합니다. 예: narration2")
    cleaned = (script or "").strip()
    if not cleaned:
        raise UserInputError("녹음에서 실제로 읽은 문장을 적어 주세요. 대본이 녹음과 다르면 Qwen3 가 문장을 끝맺지 못합니다.")
    path = Path(wav_path)
    if not usable_reference(path):
        raise UserInputError("참조 녹음이 없거나 무음에 가깝습니다. 다시 녹음하거나 다른 파일을 올리세요.")
    with _LOCK:
        raw = _read_raw()
        entry = dict(raw.get(style_id) or {})
        entry["file"] = path.name
        entry["script"] = cleaned
        if qc is not None:
            entry["qc"] = qc
        else:
            entry.pop("qc", None)
        if style_id in BUILTIN_BY_ID:
            entry.pop("label", None)
            if label and label.strip() and label.strip() != BUILTIN_BY_ID[style_id].label:
                entry["label"] = label.strip()
        else:
            entry["label"] = (label or entry.get("label") or style_id).strip()
            if description is not None:
                entry["description"] = description.strip()
        raw[style_id] = entry
        _write_raw(raw)
    return resolve(style_id)


def unregister(style_id: str) -> None:
    """말투 연결만 지운다. 녹음 파일은 지우지 않는다."""
    with _LOCK:
        raw = _read_raw()
        raw.pop(style_id, None)
        _write_raw(raw)


def ready_styles() -> list[Style]:
    return [style for style in list_styles() if style.ready]
