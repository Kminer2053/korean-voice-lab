"""Qwen3 생성 감독: 생성 상한(폭주 막기)과 말끝 보정.

폭주 막기
- Qwen3 는 참조 녹음의 대본이 실제 녹음과 어긋나거나(녹음이 문장 중간에서 끊긴 경우 등) 잡음이 심하면
  끝내기 신호를 내지 못하고, 모델 기본 상한
  (8192 프레임, 약 11분)까지 말 같지 않은 소리를 이어 만든다. 생성 하나에 몇 분~몇 시간이 걸리고 메모리도 찬다.
- 그래서 문장 길이로 어림한 길이의 몇 배를 상한으로 넘기고(budget_frames), 상한에 닿거나 어림보다 지나치게
  길면 폭주로 보고 seed 를 바꿔 다시 만든다. 끝내 안 되면 오류를 낸다(긴 엉터리 소리를 돌려주지 않는다).

말끝 보정(VOICELAB_QWEN_CODA=0 이면 끔)
- Qwen3(녹음+대본 복제)는 마지막 음절을 서둘러 닫고 곧바로 끝낸다. 끝에 무음을 더하거나 끝내기 토큰을
  늦춰도 말소리 자체는 그대로다. 그래서 문장 뒤에 " 네."를 붙여 모델이 문장 끝을 '중간'처럼 온전히
  읽게 한 뒤, 문장과 꼬리말 사이의 쉼에서 자른다.
- 자른 결과는 아래를 모두 지켜야 쓴다. 아니면 seed 를 바꿔 다시 만들고, 끝내 안 되면 꼬리말 없이 만든다.
  - 꼬리말 앞 쉼이 MIN_GAP_SEC 이상
  - 쉼 안 소리가 한 번은 최대 음량의 MAX_FLOOR(잡음이 섞인 결과는 그 잡음 바닥의 2배, 최대 1%) 아래로 떨어짐
    (아니면 꼬리말 첫소리가 섞여 끝에 '쿵' 소리가 남)
  - 잘라 낸 꼬리말이 MAX_CODA_SEC 이하(더 길면 문장 중간의 쉼을 잘못 잡은 것)
"""

from __future__ import annotations

import os
import re
from typing import Callable

import numpy as np

VERSION = 1  # 자르는 규칙이 바뀌면 올린다(일괄 생성 캐시 키). 폭주 상한은 정상 결과를 바꾸지 않아 그대로
ENABLED = os.environ.get("VOICELAB_QWEN_CODA", "1") != "0"
CODA = " 네."
CODA_LATIN = " Yes."  # 영어로 끝나는 문장은 한국어 꼬리말과 이어 읽히지 않아 쉼이 짧다(견딤 시험에서 늘 실패)
MAX_TRIES = 3

HOP_SEC = 0.01
LOUD_RATIO = 0.05  # 최대 음량의 5% 이상이면 소리로 본다
SCAN_GAP_SEC = 0.10  # 꼬리말 안의 짧은 틈은 건너뛰고 이보다 긴 쉼을 찾는다
MIN_GAP_SEC = 0.20
MAX_FLOOR = 0.001  # 0.1%
MAX_CODA_SEC = 0.45
MAX_CODA_NEWLINE_SEC = 0.6  # 줄을 바꿔 붙인 꼬리말은 홀로 읽혀 조금 길다(쉼이 확실해 잘못 자를 위험이 작음)
KEEP_SEC = 0.12  # 문장 마지막 음절의 여운으로 남기는 길이
FADE_SEC = 0.02

FRAME_RATE = 12.5  # Qwen3-TTS 12Hz 코덱 프레임(1프레임 0.08초)
BUDGET_FACTOR = 2.5  # 상한 = 어림 길이 × 이 값 + BUDGET_EXTRA_SEC (느린 말투도 넉넉히, CPU 에서 폭주 비용은 줄임)
BUDGET_EXTRA_SEC = 5.0
RUNAWAY_FACTOR = 2.5  # 말소리 구간이 어림 × 이 값 + RUNAWAY_EXTRA_SEC 보다 길면 폭주
RUNAWAY_EXTRA_SEC = 4.0
SHORT_FACTOR = 0.35  # 말소리가 어림 × 이 값보다 짧으면 문장을 다 읽지 못한 것(어림 1.5초 이상일 때)
SILENT_RMS = 0.003


class RunawayError(RuntimeError):
    """여러 번 다시 만들어도 모델이 문장을 끝맺지 못함."""


def estimate_sec(text: str) -> float:
    """보통 빠르기로 읽을 때 길이 어림(초). 한글 음절·로마자·숫자·쉼 수로 센다."""
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    digits = len(re.findall(r"\d", text))
    pauses = len(re.findall(r"[.!?,\n]", text))
    return hangul / 6.5 + latin / 12 + digits * 0.3 + pauses * 0.15 + 0.3


def budget_frames(text: str) -> int:
    """이 문장에 허락하는 최대 생성 프레임 수."""
    return int((estimate_sec(text) * BUDGET_FACTOR + BUDGET_EXTRA_SEC) * FRAME_RATE)


def bad_length_reason(audio: np.ndarray, rate: int, text: str) -> tuple[str, str] | None:
    """길이가 문장과 맞지 않으면 (종류, 설명). 종류: runaway(끝맺지 못함) · short(덜 읽음·무음). 맞으면 None."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    limit_sec = budget_frames(text) / FRAME_RATE
    total = audio.size / rate
    if total >= limit_sec - 0.5:
        return "runaway", f"상한 {limit_sec:.0f}초에 닿음"
    hop = max(1, int(rate * HOP_SEC))
    n = audio.size // hop
    if not n:
        return "short", "소리가 없음"
    env = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1))
    if env.max() < SILENT_RMS:
        return "short", "무음"
    voiced = np.flatnonzero(env > env.max() * LOUD_RATIO)
    span = (voiced[-1] - voiced[0] + 1) * HOP_SEC
    expect = estimate_sec(text)
    if span > expect * RUNAWAY_FACTOR + RUNAWAY_EXTRA_SEC:
        return "runaway", f"말소리 {span:.1f}초(어림 {expect:.1f}초)"
    if expect >= 1.5 and span < expect * SHORT_FACTOR:
        return "short", f"말소리 {span:.1f}초(어림 {expect:.1f}초)"
    return None


def coda_for(text: str) -> str:
    """마지막 문장이 주로 로마자면 영어 꼬리말, 아니면 한국어 꼬리말."""
    last = re.split(r"[.!?…。？！\n]+\s*", text.strip().rstrip(".!?…。？！"))[-1]
    latin = len(re.findall(r"[A-Za-z]", last))
    hangul = len(re.findall(r"[가-힣]", last))
    return CODA_LATIN if latin > hangul * 2 else CODA


def with_coda(text: str, newline: bool = False) -> str:
    """꼬리말을 붙인다. newline 이면 줄을 바꿔 붙인다(모델이 줄바꿈에서 쉼을 두므로 쉼이 짧아 실패한 뒤에 쓴다)."""
    coda = coda_for(text)
    if newline:
        coda = "\n" + coda.lstrip()
    text = text.rstrip()
    if not re.search(r"[.!?…~。？！]$", text):
        text += "."  # 끝에 문장부호가 없으면 꼬리말과 붙어 읽혀 쉼이 안 생긴다("안녕 네.")
    return text + coda


def cut_before_coda(audio: np.ndarray, rate: int, max_coda_sec: float = MAX_CODA_SEC) -> tuple[np.ndarray | None, dict]:
    """꼬리말 앞 쉼에서 자른 소리와 측정값. 기준을 못 맞추면 (None, 측정값)."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    hop = max(1, int(rate * HOP_SEC))
    n = audio.size // hop
    if n < 3:
        return None, {"reason": "too_short"}
    env = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1))
    peak = float(env.max())
    if peak <= 0:
        return None, {"reason": "silent"}
    loud = env > peak * LOUD_RATIO
    voiced = np.flatnonzero(loud)
    last = int(voiced[-1])
    k = last
    while k >= 0 and loud[k]:
        k -= 1
    while k >= 0:
        j = k
        while j >= 0 and not loud[j]:
            j -= 1
        gap = (k - j) * HOP_SEC
        if j >= 0 and gap >= SCAN_GAP_SEC:
            start = j + 1  # 쉼 시작(문장 마지막 음절이 잦아든 곳)
            # 잡음이 섞인 결과(잡음 있는 참조 녹음)는 쉼이 -60dB 까지 안 내려간다. 쉼이 그 결과의 잡음 바닥
            # 근처까지 내려갔으면 꼬리말 첫소리가 섞이지 않은 진짜 쉼으로 본다(상한 -40dB).
            noise = float(np.percentile(env, 5)) / peak
            allowed = min(0.01, max(MAX_FLOOR, noise * 2.0))
            info = {
                "gap_sec": round(gap, 3),
                "coda_sec": round((last - k) * HOP_SEC, 3),
                "floor": round(float(env[start : k + 1].min()) / peak, 5),
                "allowed_floor": round(allowed, 5),
            }
            if gap < MIN_GAP_SEC:
                return None, {**info, "reason": "short_gap"}
            if info["floor"] > allowed:
                return None, {**info, "reason": "no_silence"}
            if info["coda_sec"] > max_coda_sec:
                return None, {**info, "reason": "long_coda"}
            cut = int((start * HOP_SEC + min(KEEP_SEC, gap)) * rate)
            out = audio[:cut].copy()
            fade = min(out.size, int(rate * FADE_SEC))
            out[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
            return out, info
        k = j
        while k >= 0 and loud[k]:
            k -= 1
    return None, {"reason": "no_gap"}


def generate(
    generate_once: Callable[[str, int | None, int], tuple[np.ndarray, int]],
    text: str,
    seed: int | None,
) -> tuple[np.ndarray, int, dict]:
    """상한을 두고 만들고, 켜져 있으면 말끝을 보정한다. generate_once(text, seed, max_frames) → (소리, 표본율).

    여러 줄도 한 번에 만든다(줄바꿈에서 모델이 스스로 알맞은 쉼과 여운을 둔다). 꼬리말은 맨 끝에만 붙는다.
    seed 를 주면 seed, seed+1, … 순으로 시도한다(같은 입력이면 같은 결과).
    """
    tries: list[dict] = []
    runaways = 0  # 길이가 문장과 맞지 않은 시도(끝맺지 못함·덜 읽음)
    for attempt in range(MAX_TRIES):
        # 첫 시도는 띄어 붙이고(사용자 청취로 확인한 방식), 다시 만들 때는 한 번 줄바꿈으로 붙여 실패가 겹치지 않게 한다
        line = with_coda(text, newline=attempt == 1) if ENABLED else text
        audio, rate = generate_once(line, None if seed is None else seed + attempt, budget_frames(line))
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        bad = bad_length_reason(audio, rate, line)
        if bad:
            runaways += 1
            tries.append({"reason": bad[0], "detail": bad[1]})
            continue
        if not ENABLED:
            return audio, rate, {"ending": {"tries": len(tries) + 1, "coda": False, "runaways": runaways, "measures": tries}}
        cut, info = cut_before_coda(audio, rate, MAX_CODA_NEWLINE_SEC if attempt == 1 else MAX_CODA_SEC)
        tries.append(info)
        if cut is not None:
            return cut, rate, {"ending": {"tries": len(tries), "coda": True, "runaways": runaways, "measures": tries}}
    if ENABLED and runaways < MAX_TRIES:
        # 자르기만 못 했으면 꼬리말 없이(보정 전 방식) 한 번 더
        fallback_seed = None if seed is None else seed + MAX_TRIES
        audio, rate = generate_once(text, fallback_seed, budget_frames(text))
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        bad = bad_length_reason(audio, rate, text)
        if not bad:
            return audio, rate, {"ending": {"tries": len(tries) + 1, "coda": False, "runaways": runaways, "measures": tries}}
        runaways += 1
        tries.append({"reason": bad[0], "detail": bad[1]})
    if tries[-1].get("reason") == "short":
        raise RunawayError(
            f"모델이 문장을 제대로 읽지 못했습니다({len(tries)}번 시도: {tries[-1].get('detail', '')}). "
            "참조 녹음의 대본이 실제 녹음 내용과 다르면 생깁니다. 대본을 녹음과 똑같이 고쳐 다시 등록하세요."
        )
    raise RunawayError(
        f"모델이 문장을 끝맺지 못했습니다({len(tries)}번 시도: {tries[-1].get('detail', '')}). "
        "참조 녹음의 대본이 실제 녹음 내용과 다를 때(녹음이 문장 중간에서 끊긴 경우 포함) 가장 흔하고, 잡음이 심해도 생깁니다. "
        "대본을 녹음과 똑같이 고치거나 깨끗한 말 5–15초로 다시 등록하세요."
    )
