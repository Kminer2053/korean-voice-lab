"""Qwen3 말끝 보정: 문장 뒤에 짧은 꼬리말을 붙여 만들고, 꼬리말 앞의 쉼에서 잘라 낸다.

Qwen3(녹음+대본 복제)는 마지막 음절을 서둘러 닫고 곧바로 끝낸다. 끝에 무음을 더하거나 끝내기 토큰을
늦춰도 말소리 자체는 그대로다. 그래서 문장 뒤에 " 네."를 붙여 모델이 문장 끝을 '중간'처럼 온전히
읽게 한 뒤, 문장과 꼬리말 사이의 쉼에서 자른다.

자른 결과는 아래를 모두 지켜야 쓴다. 아니면 seed 를 바꿔 다시 만들고, 끝내 안 되면 꼬리말 없이 만든다.
- 꼬리말 앞 쉼이 MIN_GAP_SEC 이상
- 쉼 안 소리가 한 번은 최대 음량의 MAX_FLOOR 아래로 떨어짐(아니면 꼬리말 첫소리가 섞여 끝에 '쿵' 소리가 남)
- 잘라 낸 꼬리말이 MAX_CODA_SEC 이하(더 길면 문장 중간의 쉼을 잘못 잡은 것)

VOICELAB_QWEN_CODA=0 이면 쓰지 않는다.
"""

from __future__ import annotations

import os
from typing import Callable

import numpy as np

VERSION = 1  # 자르는 규칙이 바뀌면 올린다(일괄 생성 캐시 키)
ENABLED = os.environ.get("VOICELAB_QWEN_CODA", "1") != "0"
CODA = " 네."
MAX_TRIES = 3

HOP_SEC = 0.01
LOUD_RATIO = 0.05  # 최대 음량의 5% 이상이면 소리로 본다
SCAN_GAP_SEC = 0.10  # 꼬리말 안의 짧은 틈은 건너뛰고 이보다 긴 쉼을 찾는다
MIN_GAP_SEC = 0.20
MAX_FLOOR = 0.001  # 0.1%
MAX_CODA_SEC = 0.45
KEEP_SEC = 0.12  # 문장 마지막 음절의 여운으로 남기는 길이
FADE_SEC = 0.02


def with_coda(text: str) -> str:
    return text.rstrip() + CODA


def cut_before_coda(audio: np.ndarray, rate: int) -> tuple[np.ndarray | None, dict]:
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
            info = {
                "gap_sec": round(gap, 3),
                "coda_sec": round((last - k) * HOP_SEC, 3),
                "floor": round(float(env[start : k + 1].min()) / peak, 5),
            }
            if gap < MIN_GAP_SEC:
                return None, {**info, "reason": "short_gap"}
            if info["floor"] > MAX_FLOOR:
                return None, {**info, "reason": "no_silence"}
            if info["coda_sec"] > MAX_CODA_SEC:
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
    generate_once: Callable[[str, int | None], tuple[np.ndarray, int]],
    text: str,
    seed: int | None,
) -> tuple[np.ndarray, int, dict]:
    """꼬리말 방식으로 만든다. generate_once(text, seed) → (소리, 표본율).

    여러 줄도 한 번에 만든다(줄바꿈에서 모델이 스스로 알맞은 쉼과 여운을 둔다). 꼬리말은 맨 끝에만 붙는다.
    seed 를 주면 seed, seed+1, … 순으로 시도한다(같은 입력이면 같은 결과).
    """
    tries: list[dict] = []
    for attempt in range(MAX_TRIES):
        audio, rate = generate_once(with_coda(text), None if seed is None else seed + attempt)
        cut, info = cut_before_coda(audio, rate)
        tries.append(info)
        if cut is not None:
            return cut, rate, {"ending": {"tries": len(tries), "coda": True, "measures": tries}}
    audio, rate = generate_once(text, seed)  # 끝내 못 자르면 꼬리말 없이(보정 전 방식)
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    return audio, rate, {"ending": {"tries": len(tries), "coda": False, "measures": tries}}
