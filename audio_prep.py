"""iPhone 음성 메모(M4A)와 WAV를 macOS afconvert로 PCM WAV로 맞춘다."""

from __future__ import annotations

import re
import subprocess
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

import local_env

AFCONVERT = "/usr/bin/afconvert"
AFINFO = "/usr/bin/afinfo"
ALLOWED_SUFFIXES = {".wav", ".m4a", ".mp3", ".aiff", ".aif", ".caf", ".flac"}
# mlx-audio 음성 복제 안내의 권장 구간. 설치된 generate()가 이 길이로 자르지는 않는다.
GUIDE_MIN_SECONDS = 5.0
GUIDE_MAX_SECONDS = 15.0
NEAR_SILENCE_RMS = 0.008


class UserInputError(Exception):
    pass


@dataclass(frozen=True)
class PreparedAudio:
    wav_path: Path
    source_name: str
    duration_sec: float
    source_sample_rate: int | None
    wav_sample_rate: int
    rms: float
    summary: str


def coerce_upload(file_obj: object) -> tuple[Path, str]:
    if file_obj is None:
        raise UserInputError("음성 파일을 선택하세요.")
    original_name: str | None = None
    if isinstance(file_obj, (str, Path)):
        path = Path(file_obj)
        original_name = getattr(file_obj, "orig_name", None)
    elif isinstance(file_obj, dict):
        raw_path = file_obj.get("path") or file_obj.get("name")
        if not raw_path:
            raise UserInputError("올린 파일 경로를 읽지 못했습니다.")
        path = Path(str(raw_path))
        orig = file_obj.get("orig_name") or file_obj.get("orig_path")
        original_name = str(orig) if orig else None
    else:
        raw_path = getattr(file_obj, "path", None) or getattr(file_obj, "name", None)
        if not raw_path:
            raise UserInputError("올린 파일 경로를 읽지 못했습니다.")
        path = Path(str(raw_path))
        orig = getattr(file_obj, "orig_name", None)
        original_name = str(orig) if orig else None
    if not path.is_file():
        raise UserInputError(f"파일을 찾지 못했습니다: {path}")
    suffix = Path(original_name).suffix.lower() if original_name else path.suffix.lower()
    display_name = Path(original_name).name if original_name else path.name
    if suffix not in ALLOWED_SUFFIXES:
        raise UserInputError(
            "WAV·M4A·MP3·AIFF·CAF·FLAC만 올릴 수 있습니다. "
            f"지금 확장자는 '{suffix or '없음'}' 입니다. "
            "iPhone 음성 메모는 보통 .m4a 입니다."
        )
    return path, display_name


def _afinfo_text(path: Path) -> str:
    if not Path(AFINFO).is_file():
        return ""
    completed = subprocess.run(
        [AFINFO, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _parse_afinfo(text: str) -> tuple[float | None, int | None]:
    duration = None
    sample_rate = None
    duration_match = re.search(r"duration:\s*([0-9.]+)\s*sec", text, re.IGNORECASE)
    if duration_match:
        duration = float(duration_match.group(1))
    rate_match = re.search(r"(\d+)\s*Hz", text)
    if rate_match:
        sample_rate = int(rate_match.group(1))
    return duration, sample_rate


def convert_to_pcm_wav(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    completed = subprocess.run(
        [AFCONVERT, "-f", "WAVE", "-d", "LEI16", "-c", "1", str(source), str(dest)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not dest.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()
        raise UserInputError(
            "macOS afconvert로 PCM WAV 변환에 실패했습니다. ffmpeg는 설치하지 않습니다.\n"
            f"{detail or 'afconvert가 오류 문구를 남기지 않았습니다.'}"
        )


def _wav_stats(path: Path) -> tuple[float, int, float]:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_rate = handle.getframerate()
            width = handle.getsampwidth()
            frames = handle.getnframes()
            if channels != 1 or width != 2 or sample_rate <= 0:
                raise UserInputError(
                    "변환된 WAV가 16-bit 모노 PCM이 아닙니다. "
                    f"채널 {channels}, 샘플 폭 {width}, 샘플레이트 {sample_rate}."
                )
            raw = handle.readframes(frames)
    except UserInputError:
        raise
    except wave.Error as exc:
        raise UserInputError(f"WAV를 열지 못했습니다: {exc}") from exc
    if frames <= 0 or not raw:
        raise UserInputError("변환된 음성에 샘플이 없습니다.")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    duration = frames / float(sample_rate)
    rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
    return duration, sample_rate, rms


def _guidance(duration: float, rms: float) -> str:
    notes: list[str] = [f"실제 길이: {duration:.2f}초"]
    if rms < NEAR_SILENCE_RMS:
        notes.append(
            f"경고: 무음에 가깝습니다 (RMS {rms:.4f}). "
            "이 녹음은 완료로 치지 않습니다. 다시 녹음하기 전에는 만들지 않습니다."
        )
    elif duration < GUIDE_MIN_SECONDS or duration > GUIDE_MAX_SECONDS:
        notes.append(
            "mlx-audio 음성 복제 안내는 깨끗한 말 5–15초를 권합니다. "
            "너무 짧으면 화자 정보가 부족할 수 있고, 너무 길면 모델을 혼란시킬 수 있다고 적혀 있습니다. "
            "설치된 generate()는 이 파일을 잘라 내지 않습니다. 유사도나 MOS는 재지 않았습니다."
        )
    else:
        notes.append(
            "길이는 안내의 5–15초 안에 있습니다. 무음 경고는 없습니다. "
            "음질이 좋아졌다는 측정은 아닙니다."
        )
    notes.append("참조 대본에는 읽은 문장만 넣습니다. 억양 지시문은 넣지 않습니다.")
    return "\n".join(notes)


def prepare_upload(file_obj: object) -> PreparedAudio:
    source, display_name = coerce_upload(file_obj)
    info = _afinfo_text(source)
    source_duration, source_rate = _parse_afinfo(info)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(display_name).stem).strip("-") or "reference"
    dest = local_env.REFERENCES / f"{stamp}-{stem}.wav"
    convert_to_pcm_wav(source, dest)
    duration, wav_rate, rms = _wav_stats(dest)
    shown_duration = source_duration if source_duration is not None else duration
    summary = (
        f"{_guidance(shown_duration, rms)}\n"
        f"길이: {shown_duration:.2f}초"
        + (f" (변환 WAV {duration:.2f}초)" if source_duration is not None else "")
        + "\n"
        f"샘플레이트: 원본 {source_rate if source_rate is not None else 'afinfo에서 확인 못 함'} Hz, "
        f"변환 WAV {wav_rate} Hz\n"
        f"RMS: {rms:.4f}\n"
        f"파일: {display_name}\n"
        f"저장 위치: {dest.resolve()}"
    )
    return PreparedAudio(
        wav_path=dest.resolve(),
        source_name=display_name,
        duration_sec=shown_duration,
        source_sample_rate=source_rate,
        wav_sample_rate=wav_rate,
        rms=rms,
        summary=summary,
    )


def reference_kind(path: Path) -> str:
    name = path.name.lower()
    if "system-fixture" in name or "say-yuna" in name:
        return "system-say-fixture"
    return "user-upload"
