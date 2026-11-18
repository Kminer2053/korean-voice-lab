"""오디오 측정·다듬기: 참조 녹음 검사(등록 전 QC)와 결과 후처리(음량·표본율·앞 무음).

참조 녹음 검사는 '이 녹음으로 복제하면 결과가 망가질 이유'를 미리 찾는다.
- 대본과 녹음이 어긋남(말 빠르기로 추정) → Qwen3 가 끝맺지 못하거나 덜 읽는다(tools/stress.py 로 확인)
- 찢어짐(클리핑) → 결과도 찢어진다
- 잡음비가 낮음 → 결과에 잡음이 섞이고 말끝 보정이 자주 실패한다
- 끝이 잘림, 협대역(전화·블루투스), 낮은 표본율, 너무 짧거나 김

결과 후처리는 영상 작업용이다.
- 앞 무음을 0.1초로 맞춘다(문장 클립을 타임라인에 붙일 때 간격이 고르게)
- 선택: 통합 음량(LUFS, ITU-R BS.1770) 맞추기와 트루 피크 제한, 48kHz 로 내보내기
"""

from __future__ import annotations

import re
from math import gcd

import numpy as np

FRAME_SEC = 0.02
HOP_SEC = 0.01
FLOOR_DB = -100.0

# 참조 녹음 기준값
REF_MIN_SPEECH_SEC = 3.0  # 말소리 구간이 이보다 짧으면 거절(화자 정보 부족)
REF_GOOD_SPEECH = (5.0, 15.0)
REF_MAX_SPEECH_SEC = 30.0
RATE_FAIL = (1.5, 10.0)  # 대본 음절 ÷ 말소리 초. 밖이면 대본과 녹음이 어긋난 것
RATE_WARN = (4.0, 8.5)
SNR_FAIL_DB = 15.0
SNR_WARN_DB = 25.0
CLIP_FAIL_RATIO = 0.001
CLIP_WARN_RATIO = 0.0001
CLIP_EVENTS_FAIL_PER_SEC = 0.5
MIN_SOURCE_RATE = 16000
SPEECH_TARGET_DBFS = -20.0  # 참조 녹음 말소리 크기 목표
MAX_GAIN_DB = 24.0
PEAK_CEIL = 0.89  # -1 dBFS

# 결과 후처리
HEAD_KEEP_SEC = 0.1
HEAD_TRIM_OVER_SEC = 0.15


def db(x: float) -> float:
    return float(20 * np.log10(max(float(x), 1e-10)))


def frame_db(audio: np.ndarray, rate: int) -> np.ndarray:
    """20ms 창·10ms 간격 RMS(dBFS)."""
    win = max(1, int(rate * FRAME_SEC))
    hop = max(1, int(rate * HOP_SEC))
    if audio.size < win:
        return np.array([db(np.sqrt(np.mean(audio**2))) if audio.size else FLOOR_DB])
    n = 1 + (audio.size - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(audio[idx] ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-10))


def speech_mask(levels: np.ndarray) -> tuple[np.ndarray, float, float]:
    """(말소리 프레임, 잡음 바닥 dB, 말소리 수준 dB)."""
    floor = max(float(np.percentile(levels, 3)), -90.0)  # 쉼 구간의 바닥(디지털 무음은 -90 으로 본다)
    speech = float(np.percentile(levels, 95))
    threshold = max(floor + 12.0, speech - 40.0)
    return levels > threshold, floor, speech


def count_syllables(text: str) -> float:
    """대본 길이를 음절로 어림(한글 음절 + 로마자는 2.5글자에 한 음절 + 숫자 한 자에 1.5음절)."""
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    digits = len(re.findall(r"\d", text))
    return hangul + latin / 2.5 + digits * 1.5


def _clip_events(audio: np.ndarray) -> tuple[int, float]:
    """(평평하게 잘린 꼭대기 사건 수, 찢어진 표본 비율)."""
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak <= 0:
        return 0, 0.0
    hot = np.abs(audio) >= 0.98 * peak
    flat = np.concatenate([[False], np.abs(np.diff(audio)) < 1e-4]) & hot
    # 3표본 이상 이어진 평평한 꼭대기 = 사건 하나
    events = 0
    run = 0
    for value in flat:
        if value:
            run += 1
            if run == 3:
                events += 1
        else:
            run = 0
    ratio = float(np.mean(np.abs(audio) >= 0.999)) if peak >= 0.999 else float(np.mean(flat))
    return events, ratio


def _high_band_db(audio: np.ndarray, rate: int, mask: np.ndarray) -> float:
    """말소리 프레임에서 4–8kHz 에너지가 전체에서 차지하는 비율(dB). 협대역 녹음은 -45dB 아래."""
    if rate < 16000:
        return -100.0
    win = max(256, int(rate * 0.032))
    hop = max(1, int(rate * HOP_SEC))
    spectrum = np.zeros(win // 2 + 1)
    for i in np.flatnonzero(mask)[::3]:
        chunk = audio[i * hop : i * hop + win]
        if chunk.size == win:
            spectrum += np.abs(np.fft.rfft(chunk * np.hanning(win))) ** 2
    if spectrum.sum() <= 0:
        return 0.0
    freqs = np.fft.rfftfreq(win, 1 / rate)
    high = spectrum[(freqs >= 4000) & (freqs < 8000)].sum()
    return float(10 * np.log10(high / spectrum.sum() + 1e-12))


def _reverb_t60(levels: np.ndarray, speech_db: float, floor_db: float) -> float | None:
    """말이 멈추고 0.25초 넘게 쉬는 곳의 꼬리가 줄어드는 기울기로 울림 시간(T60, 초)을 어림한다.

    마른 녹음은 말이 멈추면 곧바로 잡음 바닥까지 떨어진다. 울리는 방은 소리가 천천히 잦아든다.
    말소리 수준 -10dB 지점부터 잡음 바닥 +5dB 까지(최대 0.6초)의 기울기를 쓴다. 쉼이 없으면 None.
    """
    frames_per_sec = 1.0 / HOP_SEC
    quiet_len = int(0.25 * frames_per_sec)
    loud = levels >= speech_db - 10
    estimates: list[float] = []
    i = 0
    n = levels.size
    while i < n - quiet_len:
        if loud[i] and not loud[i + 1 : i + 1 + quiet_len].any() and levels[i + quiet_len] < levels[i] - 8:
            stop = i + 1
            limit = min(n, i + int(0.6 * frames_per_sec))
            while stop < limit and levels[stop] > floor_db + 5:
                stop += 1
            part = levels[i:stop]
            if part.size >= 4 and part[0] - part[-1] >= 15:
                slope = np.polyfit(np.arange(part.size) / frames_per_sec, part, 1)[0]
                if slope < -1:
                    estimates.append(60.0 / -slope)
            i += quiet_len
            continue
        i += 1
    if not estimates:
        return None
    return float(np.median(estimates))


def _hum(audio: np.ndarray, rate: int, levels: np.ndarray, floor_db: float) -> int | None:
    """쉼 구간에서 전원 험(50·60Hz와 배음)이 이웃보다 15dB 이상 크면 그 주파수."""
    hop = int(rate * HOP_SEC)
    quiet = np.flatnonzero(levels < floor_db + 6)
    if quiet.size < 30 or floor_db < -85:
        return None
    win = 1 << int(np.ceil(np.log2(rate * 0.25)))  # 4Hz 안팎 해상도
    spectrum = np.zeros(win // 2 + 1)
    used = 0
    for i in quiet[:: max(1, quiet.size // 40)]:
        chunk = audio[i * hop : i * hop + win]
        if chunk.size == win:
            spectrum += np.abs(np.fft.rfft(chunk * np.hanning(win))) ** 2
            used += 1
    if used < 5:
        return None
    freqs = np.fft.rfftfreq(win, 1 / rate)
    power_db = 10 * np.log10(spectrum + 1e-20)
    for base in (50, 60):
        for f in (base, 2 * base, 3 * base):
            k = int(np.argmin(np.abs(freqs - f)))
            neighbours = np.r_[power_db[max(0, k - 12) : k - 3], power_db[k + 4 : k + 13]]
            if neighbours.size and power_db[k - 1 : k + 2].max() - np.median(neighbours) > 15:
                return base
    return None


def analyse_reference(audio: np.ndarray, rate: int, script: str | None = None, source_rate: int | None = None) -> dict:
    """참조 녹음 검사. {"metrics": {...}, "checks": [{"level": ok|warn|fail, "item", "message"}]}."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    checks: list[dict] = []

    def add(level: str, item: str, message: str) -> None:
        checks.append({"level": level, "item": item, "message": message})

    total = audio.size / rate if rate else 0.0
    levels = frame_db(audio, rate)
    mask, floor_db, speech_db = speech_mask(levels)
    voiced = np.flatnonzero(mask)
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    metrics: dict = {"duration_sec": round(total, 2), "peak_dbfs": round(db(peak), 1)}
    if speech_db < -55 or voiced.size < 10:
        add("fail", "소리", "말소리가 거의 없습니다(무음에 가까움). 마이크가 켜졌는지 확인하고 다시 녹음하세요.")
        metrics.update(speech_sec=0.0)
        return {"metrics": metrics, "checks": checks}
    first, last = voiced[0] * HOP_SEC, voiced[-1] * HOP_SEC + FRAME_SEC
    speech_sec = last - first
    snr = speech_db - max(floor_db, FLOOR_DB)
    speech_rms_db = db(np.sqrt(np.mean(audio[int(first * rate) : int(last * rate)] ** 2)))
    events, clip_ratio = _clip_events(audio)
    metrics.update(
        speech_sec=round(speech_sec, 2), lead_sec=round(first, 2), tail_sec=round(total - last, 2),
        snr_db=round(min(snr, 99.0), 1), noise_floor_dbfs=round(floor_db, 1), speech_rms_dbfs=round(speech_rms_db, 1),
        clip_ratio=round(clip_ratio, 5), clip_events=events, dc_offset=round(float(np.mean(audio)), 4),
    )

    # 길이
    if speech_sec < REF_MIN_SPEECH_SEC:
        add("fail", "길이", f"말소리가 {speech_sec:.1f}초뿐입니다. {REF_GOOD_SPEECH[0]:.0f}–{REF_GOOD_SPEECH[1]:.0f}초 읽어 주세요.")
    elif speech_sec > REF_MAX_SPEECH_SEC:
        add("fail", "길이", f"말소리가 {speech_sec:.0f}초로 너무 깁니다. 5–15초 분량만 남겨 주세요(길면 모델이 흔들립니다).")
    elif not REF_GOOD_SPEECH[0] <= speech_sec <= REF_GOOD_SPEECH[1]:
        add("warn", "길이", f"말소리 {speech_sec:.1f}초. 5–15초가 가장 안정적입니다.")
    else:
        add("ok", "길이", f"말소리 {speech_sec:.1f}초")

    # 대본과 녹음 맞춤(말 빠르기)
    if script is not None:
        syllables = count_syllables(script)
        if syllables < 5:
            add("fail", "대본", "녹음에서 읽은 문장을 그대로 적어 주세요(대본이 비어 있거나 너무 짧음).")
        else:
            pace = syllables / max(speech_sec, 0.1)
            metrics["syllables_per_sec"] = round(pace, 1)
            if not RATE_FAIL[0] <= pace <= RATE_FAIL[1]:
                hint = "녹음이 대본보다 짧습니다. 끝까지 읽기 전에 녹음이 끊겼거나 대본이 더 깁니다" if pace > RATE_FAIL[1] \
                    else "녹음이 대본보다 훨씬 깁니다. 대본에 없는 말을 했거나 대본이 일부만 적혀 있습니다"
                add("fail", "대본 맞춤", f"{hint}(초당 {pace:.1f}음절). 대본을 실제로 읽은 그대로 고치세요.")
            elif not RATE_WARN[0] <= pace <= RATE_WARN[1]:
                add("warn", "대본 맞춤", f"말 빠르기가 초당 {pace:.1f}음절로 보통(4–7)과 다릅니다. 대본이 녹음과 같은지 확인하세요.")
            else:
                add("ok", "대본 맞춤", f"초당 {pace:.1f}음절(대본과 녹음 길이가 맞음)")

    # 찢어짐
    events_per_sec = events / max(total, 0.1)
    if clip_ratio > CLIP_FAIL_RATIO or events_per_sec > CLIP_EVENTS_FAIL_PER_SEC:
        add("fail", "찢어짐", "소리가 너무 커서 찢어졌습니다(결과도 찢어집니다). 입력 음량을 낮추거나 마이크에서 조금 떨어져 다시 녹음하세요.")
    elif clip_ratio > CLIP_WARN_RATIO or events:
        add("warn", "찢어짐", "몇 군데 소리가 찢어졌습니다. 가능하면 조금 작게 다시 녹음하세요.")
    else:
        add("ok", "찢어짐", f"없음(최대 {db(peak):.1f} dBFS)")

    # 잡음
    if snr < SNR_FAIL_DB:
        add("fail", "잡음", f"말소리와 잡음 차이가 {snr:.0f}dB로 작습니다. 조용한 곳에서 다시 녹음하세요(결과에 잡음이 섞입니다).")
    elif snr < SNR_WARN_DB:
        add("warn", "잡음", f"잡음이 조금 있습니다(말소리 대비 {snr:.0f}dB). 더 조용한 곳이면 결과가 깨끗해집니다.")
    else:
        add("ok", "잡음", f"깨끗함(말소리 대비 {min(snr, 99):.0f}dB)")

    # 끝 잘림
    tail_level = float(np.mean(levels[-5:])) if levels.size >= 5 else floor_db
    if total - last < 0.1 and tail_level > floor_db + 20:
        add("warn", "끝 잘림", "말이 끝나기 전에 녹음이 끊긴 것 같습니다. 끝까지 읽고 0.5초 쉰 뒤 멈추세요.")
    if first < 0.03 and levels[0] > floor_db + 20:
        add("warn", "첫소리", "첫소리가 잘렸을 수 있습니다. 녹음을 켜고 0.5초 뒤에 읽기 시작하세요.")

    # 음질(표본율·대역)
    high_db = _high_band_db(audio, rate, mask)
    metrics["high_band_db"] = round(high_db, 1)
    if (source_rate or rate) < MIN_SOURCE_RATE:
        add("fail", "음질", f"표본율 {source_rate or rate}Hz는 너무 낮습니다(전화 음질). 16kHz 이상으로 녹음하세요.")
    elif high_db < -45:
        add("warn", "음질", "고음이 잘린 좁은 대역 녹음입니다(블루투스 이어폰 마이크·전화). 기기 내장 마이크나 유선 마이크를 쓰세요.")
    if abs(metrics["dc_offset"]) > 0.005:
        add("warn", "직류 치우침", "녹음 신호가 한쪽으로 치우쳐 있어 등록할 때 바로잡습니다.")

    # 울림·전원 험
    t60 = _reverb_t60(levels, speech_db, max(floor_db, FLOOR_DB))
    if t60 is not None:
        metrics["reverb_t60_sec"] = round(t60, 2)
        if t60 > 0.8:
            add("warn", "울림", f"방 울림이 큽니다(잔향 약 {t60:.1f}초). 결과에도 울림이 실립니다. 커튼·옷장 근처나 작은 방에서 다시 녹음하세요.")
        elif t60 > 0.5:
            add("warn", "울림", f"방 울림이 조금 있습니다(잔향 약 {t60:.1f}초). 마이크에 조금 더 가까이 대면 줄어듭니다.")
    hum = _hum(audio, rate, levels, floor_db)
    if hum:
        metrics["hum_hz"] = hum
        add("warn", "웅 소리", f"쉼 구간에 {hum}Hz 전원 웅 소리가 섞여 있습니다. 충전기·전원선을 빼거나 노트북 배터리로 녹음해 보세요.")
    return {"metrics": metrics, "checks": checks}


def pick_channel(channels: np.ndarray) -> tuple[np.ndarray, dict]:
    """스테레오 녹음을 모노로. 한쪽이 비었거나(10dB 이상 약함) 두 채널이 딴판이면(위상 반전 등) 강한 쪽만 쓴다.

    channels: (채널 수, 표본 수). 돌려주는 값: (모노, 기록). 채널마다 찢어짐도 따로 잰다.
    """
    channels = np.asarray(channels, dtype=np.float32)
    if channels.ndim == 1 or channels.shape[0] == 1:
        return channels.reshape(-1), {}
    rms = np.sqrt(np.mean(channels**2, axis=1)) + 1e-12
    strong = int(np.argmax(rms))
    note: dict = {"channels": int(channels.shape[0])}
    clip = [float(np.mean(np.abs(c) >= 0.999)) for c in channels]
    note["clip_ratio_by_channel"] = [round(c, 5) for c in clip]
    weak_db = 20 * np.log10(rms.min() / rms.max())
    if channels.shape[1] > 1 and rms.min() > 1e-6:
        corr = float(np.corrcoef(channels[0], channels[1])[0, 1])
    else:
        corr = 1.0
    if weak_db < -10 or corr < 0.3:
        note["used_channel"] = strong
        note["reason"] = "한쪽 채널이 비었음" if weak_db < -10 else "두 채널이 서로 달라 강한 쪽만 씀"
        return channels[strong].copy(), note
    return channels.mean(axis=0), note


def has_failure(qc: dict) -> bool:
    return any(c["level"] == "fail" for c in qc.get("checks", []))


def qc_text(qc: dict) -> str:
    marks = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    return "\n".join(f"- {marks[c['level']]} **{c['item']}** — {c['message']}" for c in qc.get("checks", []))


def clean_reference(audio: np.ndarray, rate: int) -> tuple[np.ndarray, dict]:
    """등록용 다듬기: 직류 제거, 70Hz 아래 웅웅거림 줄이기, 앞뒤 무음 0.2/0.3초로, 말소리 크기 -20dBFS 근처로."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    notes: dict = {}
    audio = audio - float(np.mean(audio))
    try:
        from scipy.signal import butter, sosfiltfilt

        sos = butter(2, 70, "highpass", fs=rate, output="sos")
        audio = sosfiltfilt(sos, audio).astype(np.float32)
    except Exception:  # scipy 가 없으면 건너뜀
        pass
    levels = frame_db(audio, rate)
    mask, _floor, _speech = speech_mask(levels)
    voiced = np.flatnonzero(mask)
    if voiced.size:
        start = max(0, int((voiced[0] * HOP_SEC - 0.2) * rate))
        end = min(audio.size, int((voiced[-1] * HOP_SEC + FRAME_SEC + 0.3) * rate))
        if start > 0 or end < audio.size:
            notes["trimmed_sec"] = round((start + audio.size - end) / rate, 2)
        audio = audio[start:end].copy()
        fade = min(audio.size // 2, int(rate * 0.01))
        if fade:
            audio[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            audio[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    audio, gain_db = level_speech(audio, rate, SPEECH_TARGET_DBFS)
    if abs(gain_db) >= 1:
        notes["gain_db"] = round(gain_db, 1)
    return audio, notes


def level_speech(audio: np.ndarray, rate: int, target_dbfs: float, only_if_below: float | None = None) -> tuple[np.ndarray, float]:
    """말소리 구간 RMS 를 target 으로(피크 -1dBFS·최대 +24dB 제한). only_if_below 를 주면 그보다 작을 때만."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not audio.size:
        return audio, 0.0
    levels = frame_db(audio, rate)
    mask, _floor, _speech = speech_mask(levels)
    voiced = np.flatnonzero(mask)
    if not voiced.size:
        return audio, 0.0
    hop = int(rate * HOP_SEC)
    segment = audio[voiced[0] * hop : voiced[-1] * hop + int(rate * FRAME_SEC)]
    current = db(np.sqrt(np.mean(segment**2))) if segment.size else FLOOR_DB
    if only_if_below is not None and current >= only_if_below:
        return audio, 0.0
    gain_db = min(target_dbfs - current, MAX_GAIN_DB)
    peak = float(np.abs(audio).max())
    if peak > 0:
        gain_db = min(gain_db, db(PEAK_CEIL / peak))
    if gain_db <= 0 and only_if_below is not None:
        return audio, 0.0
    return (audio * (10 ** (gain_db / 20))).astype(np.float32), gain_db


# ---------------------------------------------------------------- 결과 후처리

def tidy_head(audio: np.ndarray, rate: int) -> np.ndarray:
    """앞 무음이 HEAD_TRIM_OVER_SEC 보다 길면 HEAD_KEEP_SEC 만 남긴다(10ms 페이드인)."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size < rate * 0.3:
        return audio
    levels = frame_db(audio, rate)
    mask, _floor, _speech = speech_mask(levels)
    voiced = np.flatnonzero(mask)
    if not voiced.size:
        return audio
    lead = voiced[0] * HOP_SEC
    if lead <= HEAD_TRIM_OVER_SEC:
        return audio
    out = audio[int((lead - HEAD_KEEP_SEC) * rate) :].copy()
    fade = int(rate * 0.01)
    out[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    return out


def _k_weight(audio: np.ndarray, rate: int) -> np.ndarray:
    from scipy.signal import lfilter

    # ITU-R BS.1770-4 K 가중(48kHz 계수를 표본율에 맞게 다시 계산)
    f0, gain, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = np.tan(np.pi * f0 / rate)
    vh = 10 ** (gain / 20)
    vb = vh**0.4996667741545416
    a0 = 1 + k / q + k * k
    b1 = [(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0]
    a1 = [1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    f0, q = 38.13547087602444, 0.5003270373238773
    k = np.tan(np.pi * f0 / rate)
    a0 = 1 + k / q + k * k
    b2 = [1, -2, 1]
    a2 = [1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    return lfilter(b2, a2, lfilter(b1, a1, audio))


def loudness_lufs(audio: np.ndarray, rate: int) -> float:
    """통합 음량(LUFS, 400ms 블록·절대 -70/상대 -10 게이트). 너무 짧으면 전체 평균."""
    audio = np.asarray(audio, dtype=np.float64).reshape(-1)
    if not audio.size:
        return -70.0
    weighted = _k_weight(audio, rate)
    block, step = int(rate * 0.4), int(rate * 0.1)
    if weighted.size < block:
        power = float(np.mean(weighted**2))
        return -0.691 + 10 * np.log10(max(power, 1e-12))
    n = 1 + (weighted.size - block) // step
    powers = np.array([np.mean(weighted[i * step : i * step + block] ** 2) for i in range(n)])
    loud = -0.691 + 10 * np.log10(np.maximum(powers, 1e-12))
    gated = powers[loud > -70]
    if not gated.size:
        return -70.0
    relative = -0.691 + 10 * np.log10(np.mean(gated)) - 10
    gated = powers[(loud > -70) & (loud > relative)]
    return float(-0.691 + 10 * np.log10(np.mean(gated if gated.size else powers)))


def true_peak_db(audio: np.ndarray, rate: int) -> float:
    from scipy.signal import resample_poly

    audio = np.asarray(audio, dtype=np.float64).reshape(-1)
    if not audio.size:
        return -100.0
    return db(float(np.abs(resample_poly(audio, 4, 1)).max()))


def _limit(audio: np.ndarray, rate: int, ceiling: float) -> np.ndarray:
    """부드러운 피크 리미터: 3ms 앞을 보고 줄이고 80ms 에 걸쳐 되돌린다(말소리 음량은 거의 그대로)."""
    from scipy.ndimage import minimum_filter1d

    peak = np.abs(audio)
    if peak.max() <= ceiling:
        return audio
    need = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
    look = max(1, int(rate * 0.003))
    need = minimum_filter1d(need, size=2 * look + 1, mode="nearest")  # 봉우리 앞뒤로 미리 줄임
    release = 1.0 / max(1, int(rate * 0.08))
    smooth = np.empty_like(need)
    current = 1.0
    for i, value in enumerate(need):  # 줄일 때는 바로, 되돌릴 때는 천천히
        current = value if value < current else min(value, current + release)
        smooth[i] = current
    return (audio * smooth).astype(np.float32)


def normalize_loudness(audio: np.ndarray, rate: int, target_lufs: float, ceiling_dbtp: float = -1.0) -> tuple[np.ndarray, dict]:
    """통합 음량을 target 으로 맞추고, 넘치는 봉우리는 리미터로 눌러 트루 피크를 ceiling 아래로 둔다."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    before = loudness_lufs(audio, rate)
    ceiling = 10 ** ((ceiling_dbtp - 0.5) / 20)  # 표본 피크는 트루 피크보다 낮게 잡는다
    out = audio * (10 ** ((target_lufs - before) / 20))
    for _ in range(2):  # 리미터가 줄인 만큼 한 번 더 맞춘다
        out = _limit(out, rate, ceiling)
        now = loudness_lufs(out, rate)
        if abs(now - target_lufs) < 0.3:
            break
        out = out * (10 ** ((target_lufs - now) / 20))
    out = _limit(out, rate, ceiling)
    tp = true_peak_db(out, rate)
    if tp > ceiling_dbtp:
        out = out * (10 ** ((ceiling_dbtp - tp) / 20))
    out = out.astype(np.float32)
    return out, {"lufs": round(loudness_lufs(out, rate), 1), "gain_db": round(target_lufs - before, 1),
                 "true_peak_dbtp": round(true_peak_db(out, rate), 1)}


SPEED_RANGE = (0.8, 1.25)


def change_tempo(audio: np.ndarray, rate: int, speed: float) -> np.ndarray:
    """음높이는 그대로 두고 말 빠르기만 바꾼다(ffmpeg atempo, PyAV 내장). speed 1.1 = 10% 빠르게."""
    speed = float(speed)
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if abs(speed - 1.0) < 1e-3 or not audio.size:
        return audio
    import av
    from av.filter import Graph

    graph = Graph()
    src = graph.add_abuffer(format="flt", sample_rate=rate, layout="mono")
    tempo = graph.add("atempo", f"{speed:.4f}")
    sink = graph.add("abuffersink")
    src.link_to(tempo)
    tempo.link_to(sink)
    graph.configure()
    frame = av.AudioFrame.from_ndarray(audio.reshape(1, -1), format="flt", layout="mono")
    frame.sample_rate = rate
    frame.pts = 0
    graph.push(frame)
    graph.push(None)
    pieces: list[np.ndarray] = []
    while True:
        try:
            out = graph.pull()
        except Exception:  # 끝(EOF) 또는 더 나올 것이 없음
            break
        pieces.append(out.to_ndarray().reshape(-1))
    return np.concatenate(pieces).astype(np.float32) if pieces else audio


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return np.asarray(audio, dtype=np.float32)
    from scipy.signal import resample_poly

    g = gcd(int(src), int(dst))
    return resample_poly(np.asarray(audio, dtype=np.float64), dst // g, src // g).astype(np.float32)


def measure_output(audio: np.ndarray, rate: int) -> dict:
    """결과 기록용: 통합 음량·피크."""
    try:
        return {"lufs": round(loudness_lufs(audio, rate), 1), "peak_dbfs": round(db(float(np.abs(audio).max())), 1)}
    except Exception:
        return {"peak_dbfs": round(db(float(np.abs(audio).max())) if np.size(audio) else -100.0, 1)}
