"""참조 녹음을 16-bit 모노 PCM WAV 로 맞춘다. 맥·윈도우·리눅스 공통.

변환 순서:
1. WAV 는 표준 라이브러리 + numpy 로 직접 읽는다(8/16/24/32-bit, 여러 채널 → 모노).
2. 그 밖의 형식(M4A·MP3·FLAC 등)은 PyAV(pip install av)로 디코딩한다. ffmpeg 를 따로 설치할 필요가 없다.
3. PyAV 가 없으면 맥에서는 내장 afconvert 를 쓴다.
"""

from __future__ import annotations

import re
import subprocess
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

import local_env

ALLOWED_SUFFIXES = {".wav", ".m4a", ".mp3", ".aiff", ".aif", ".caf", ".flac", ".ogg", ".webm"}
AFCONVERT = "/usr/bin/afconvert"
# 음성 복제 안내의 권장 구간. 생성 코드가 이 길이로 자르지는 않는다.
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
            "WAV·M4A·MP3·FLAC·AIFF·CAF·OGG·WEBM만 올릴 수 있습니다. "
            f"지금 확장자는 '{suffix or '없음'}' 입니다. 아이폰 음성 메모는 보통 .m4a 입니다."
        )
    return path, display_name


# ---------------------------------------------------------------- 디코딩
def _read_wav_numpy(path: Path) -> tuple[np.ndarray, int]:
    """PCM WAV → float32 모노. 지원하지 않는 WAV(부동소수 등)는 wave.Error."""
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        bytes3 = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = (bytes3[:, 0].astype(np.int32) | (bytes3[:, 1].astype(np.int32) << 8) | (bytes3[:, 2].astype(np.int32) << 16))
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        data = ints.astype(np.float32) / float(1 << 23)
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / float(1 << 31)
    else:
        raise wave.Error(f"샘플 폭 {width}바이트 WAV는 읽지 못합니다.")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def _read_with_av(path: Path) -> tuple[np.ndarray, int]:
    import av  # PyAV: ffmpeg 라이브러리를 품은 휠이라 따로 설치할 것이 없다.

    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise UserInputError("파일에 오디오 트랙이 없습니다.")
        rate = int(stream.rate or stream.codec_context.sample_rate)
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        chunks: list[np.ndarray] = []
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        raise UserInputError("디코딩한 오디오가 비어 있습니다.")
    return np.concatenate(chunks).astype(np.float32), rate


def _read_with_afconvert(path: Path, tmp_wav: Path) -> tuple[np.ndarray, int]:
    done = subprocess.run(
        [AFCONVERT, "-f", "WAVE", "-d", "LEI16", "-c", "1", str(path), str(tmp_wav)],
        check=False, capture_output=True, text=True,
    )
    if done.returncode != 0 or not tmp_wav.is_file():
        detail = (done.stderr or done.stdout or "").strip()
        raise UserInputError(f"macOS afconvert 변환에 실패했습니다.\n{detail}")
    try:
        return _read_wav_numpy(tmp_wav)
    finally:
        tmp_wav.unlink(missing_ok=True)


def decode_audio(path: Path | str) -> tuple[np.ndarray, int, str]:
    """(float32 모노, 샘플레이트, 사용한 방법)."""
    path = Path(path)
    errors: list[str] = []
    if path.suffix.lower() == ".wav":
        try:
            data, rate = _read_wav_numpy(path)
            return data, rate, "wav"
        except (wave.Error, EOFError, ValueError) as exc:
            errors.append(f"WAV 직접 읽기: {exc}")
    try:
        data, rate = _read_with_av(path)
        return data, rate, "pyav"
    except ImportError:
        errors.append("PyAV 없음(pip install av)")
    except UserInputError:
        raise
    except Exception as exc:
        errors.append(f"PyAV: {exc}")
    if Path(AFCONVERT).is_file():
        data, rate = _read_with_afconvert(path, path.with_name(path.stem + ".afconvert.wav"))
        return data, rate, "afconvert"
    raise UserInputError(
        "이 파일을 읽지 못했습니다. WAV로 저장해 올리거나 PyAV를 설치하세요(.venv 의 pip install av).\n"
        + "\n".join(errors)
    )


def write_pcm16(path: Path, data: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(np.nan_to_num(data), -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm.tobytes())


def convert_to_pcm_wav(source: Path, dest: Path) -> None:
    data, rate, _method = decode_audio(source)
    if data.size == 0:
        raise UserInputError("변환된 음성에 샘플이 없습니다.")
    write_pcm16(dest, data, rate)


def _wav_stats(path: Path) -> tuple[float, int, float]:
    try:
        data, rate = _read_wav_numpy(path)
    except (wave.Error, EOFError) as exc:
        raise UserInputError(f"WAV를 열지 못했습니다: {exc}") from exc
    if data.size == 0 or rate <= 0:
        raise UserInputError("음성에 샘플이 없습니다.")
    rms = float(np.sqrt(np.mean(np.square(data))))
    return data.size / float(rate), rate, rms


def _guidance(duration: float, rms: float) -> str:
    notes: list[str] = [f"실제 길이: {duration:.2f}초"]
    if rms < NEAR_SILENCE_RMS:
        notes.append(f"경고: 무음에 가깝습니다 (RMS {rms:.4f}). 다시 녹음하기 전에는 등록하지 않습니다.")
    elif duration < GUIDE_MIN_SECONDS or duration > GUIDE_MAX_SECONDS:
        notes.append("깨끗한 말 5–15초를 권합니다. 너무 짧으면 화자 정보가 부족하고, 너무 길면 모델이 흔들릴 수 있습니다.")
    else:
        notes.append("길이는 권장 범위(5–15초) 안에 있습니다.")
    return "\n".join(notes)


def prepare_upload(file_obj: object) -> PreparedAudio:
    source, display_name = coerce_upload(file_obj)
    data, source_rate, method = decode_audio(source)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(display_name).stem).strip("-") or "reference"
    dest = local_env.REFERENCES / f"{stamp}-{stem}.wav"
    if data.size == 0:
        raise UserInputError("변환된 음성에 샘플이 없습니다.")
    write_pcm16(dest, data, source_rate)
    duration, wav_rate, rms = _wav_stats(dest)
    summary = (
        f"{_guidance(duration, rms)}\n"
        f"샘플레이트: {wav_rate} Hz · RMS {rms:.4f} · 변환 방법 {method}\n"
        f"파일: {display_name}\n"
        f"저장 위치: {dest.resolve()}"
    )
    return PreparedAudio(
        wav_path=dest.resolve(),
        source_name=display_name,
        duration_sec=duration,
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


def ensure_tail_silence(audio: np.ndarray, rate: int, min_sec: float) -> np.ndarray:
    """끝 무음이 min_sec 보다 짧으면 무음을 덧붙인다(이미 충분하면 그대로).

    Qwen3 는 마지막 음절 직후 바로 끝나(끝 무음 0.01~0.07초) 다음 문장과 붙어 들린다. 문장 사이 쉼을
    고르게 하려고 쉼만 더한다(말끝 자체는 ending.py 가 고친다).
    """
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if min_sec <= 0 or audio.size == 0:
        return audio
    rms = float(np.sqrt(np.mean(audio**2)))
    voiced = np.flatnonzero(np.abs(audio) > max(rms * 0.1, 1e-3))
    tail_sec = (audio.size - 1 - voiced[-1]) / rate if voiced.size else audio.size / rate
    if tail_sec >= min_sec:
        return audio
    if abs(float(audio[-1])) > 0.01:  # 끝 샘플이 0이 아니면 5ms 페이드로 '틱' 소리를 막는다
        n = min(audio.size, max(1, int(rate * 0.005)))
        audio = audio.copy()
        audio[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    return np.concatenate([audio, np.zeros(int(round((min_sec - tail_sec) * rate)), dtype=np.float32)])

