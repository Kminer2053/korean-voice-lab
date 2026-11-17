"""숫자를 한국어 읽는 소리로 바꾼다(표준 라이브러리만).

숫자를 잘 못 읽는 엔진(Chatterbox 등) 앞에서 자동으로 쓰고, 채점(tools/evaluate.py)에서도 같은 규칙으로 맞춘다.

  spell_numbers("2026년 예산은 12% 늘어난 3억 5천만 원, 오전 9시")
  → "이천이십육년 예산은 십이 퍼센트 늘어난 삼억 오천만 원, 오전 아홉 시"

규칙
- 기본은 한자어 수(일, 이, 삼 …). 만·억·조 단위로 끊어 읽고, 십·백·천·만 앞의 '일'은 뺀다(10 → 십, 10000 → 만).
- 1~99 뒤에 고유어 단위(시, 시간, 개, 명, 살, 마리 …)가 오면 고유어로 읽는다(9시 → 아홉 시, 2개 → 두 개).
- 전화번호(010-1234-5678)와 0으로 시작하는 여러 자리는 한 자리씩 읽는다(010 → 공일공).
- 소수는 '점', 쉼표 자릿수(1,000)는 무시, % 는 퍼센트.
"""

from __future__ import annotations

import re

_DIGITS = "영일이삼사오육칠팔구"
_SMALL_UNITS = ("", "십", "백", "천")
_BIG_UNITS = ("", "만", "억", "조", "경")

_NATIVE_ONES = ("", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉")
_NATIVE_TENS = ("", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔")

# 1~99 를 고유어로 읽는 단위(뒤따르는 말). 긴 것부터 맞춘다.
NATIVE_COUNTERS = (
    "시간", "시", "개", "명", "살", "마리", "사람", "잔", "병", "권", "장", "대", "곳", "가지", "군데",
    "번째", "그릇", "켤레", "벌", "통", "척", "송이", "봉지", "달",
)

_PHONE = re.compile(r"(?<!\d)0\d{1,2}-\d{3,4}-\d{4}(?!\d)")
_NUMBER = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")


def sino(n: int) -> str:
    """한자어 수. 0 → 영."""
    if n == 0:
        return "영"
    groups: list[str] = []
    big = 0
    while n > 0:
        chunk = n % 10000
        n //= 10000
        if chunk:
            words = ""
            for place in range(3, -1, -1):
                digit = chunk // (10**place) % 10
                if not digit:
                    continue
                head = "" if (digit == 1 and place > 0) else _DIGITS[digit]
                words += head + _SMALL_UNITS[place]
            unit = _BIG_UNITS[big] if big < len(_BIG_UNITS) else ""
            if words == "일" and big == 1:  # 10000 → 만(일만이 아님)
                words = ""
            groups.append(words + unit)
        big += 1
    return "".join(reversed(groups))


def native(n: int) -> str:
    """1~99 고유어 관형형(한, 두, 세, 스무 …)."""
    tens, ones = divmod(n, 10)
    if tens == 2 and ones == 0:
        return "스무"
    return _NATIVE_TENS[tens] + _NATIVE_ONES[ones]


def _digit_by_digit(digits: str) -> str:
    return "".join("공" if d == "0" else _DIGITS[int(d)] for d in digits)


def spell_numbers(text: str) -> str:
    """문장 속 아라비아 숫자를 한국어 소리로 바꾼다. 숫자가 없으면 그대로 돌려준다."""
    if not re.search(r"\d", text):
        return text
    text = _PHONE.sub(lambda m: " ".join(_digit_by_digit(g) for g in m.group(0).split("-")), text)
    out: list[str] = []
    pos = 0
    for match in _NUMBER.finditer(text):
        whole, frac = match.group(1), match.group(2)
        out.append(text[pos:match.start()])
        rest = text[match.end():]
        after = rest.lstrip(" ")
        plain = whole.replace(",", "")
        if frac is None and len(plain) > 1 and plain.startswith("0"):
            spoken = _digit_by_digit(plain)
        else:
            value = int(plain)
            counter = next((c for c in NATIVE_COUNTERS if after.startswith(c)), None)
            if frac is None and counter and 1 <= value <= 99:
                spoken = native(value) + " "
                # 바로 붙은 공백은 하나로
                pos = match.end() + (len(rest) - len(after))
                out.append(spoken)
                continue
            spoken = sino(value)
            if frac is not None:
                spoken += "점" + _digit_by_digit(frac).replace("공", "영")
        pos = match.end()
        if rest.startswith("%"):
            spoken += " 퍼센트"
            pos += 1
        out.append(spoken)
    out.append(text[pos:])
    return "".join(out)


if __name__ == "__main__":
    import sys

    for line in sys.argv[1:] or ["2026년 예산은 전년보다 12% 늘어난 3억 5천만 원입니다. 오전 9시, 20개, 1,500원, 3.14, 010-1234-5678"]:
        print(spell_numbers(line))
