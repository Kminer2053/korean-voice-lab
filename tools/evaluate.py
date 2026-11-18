#!/usr/bin/env python3
"""benchmark.py 결과를 채점한다. 받아쓰기 오독률(CER)과 화자 유사도(SIM).

채점 도구는 엔진과 나눈 가상환경(.venv-eval)에 둔다:
  python3.12 -m venv .venv-eval
  .venv-eval/bin/pip install faster-whisper speechbrain torchaudio soundfile
  .venv-eval/bin/python tools/evaluate.py outputs/bench

- CER: faster-whisper(large-v3, CPU int8)로 받아 적어 원문과 글자 단위 편집 거리를 잰다.
  띄어쓰기·문장부호는 빼고, 숫자는 양쪽 모두 textnorm 규칙으로 한글 소리로 바꿔 비교한다.
- SIM: SpeechBrain ECAPA(spkrec-ecapa-voxceleb) 임베딩 코사인 유사도(참조 녹음 대 생성 음성).
  어느 엔진의 내부 인코더도 아닌 독립 모델이다. 1에 가까울수록 참조 목소리와 비슷하다.
결과: <bench>/eval.json, <bench>/report.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 채점 모델도 저장소 안 캐시(.cache/, 커밋 안 됨)에 받는다
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))


def normalize(text: str) -> str:
    # 숫자 표기 차이(9시 ↔ 아홉 시)가 오독으로 잡히지 않게 양쪽 모두 같은 규칙으로 한글 소리로 바꾼 뒤 비교한다
    from textnorm import spell_numbers

    return re.sub(r"[^0-9A-Za-z가-힣]", "", spell_numbers(text)).lower()


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    r, h = normalize(ref), normalize(hyp)
    return edit_distance(r, h) / max(len(r), 1)


def load_16k(path: str):
    """WAV 를 16kHz 모노 float32 numpy 로(faster-whisper·ECAPA 공용, PyAV·torchcodec 버전과 무관)."""
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio

    data, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = torch.from_numpy(np.ascontiguousarray(data.mean(axis=1)))
    if rate != 16000:
        mono = torchaudio.functional.resample(mono, rate, 16000)
    return mono.numpy()


def trim_silence(x):
    """앞뒤 무음을 걷어 낸다. 화자 임베딩은 무음 길이에 흔들려(끝 무음 0.2초에 SIM 0.05~0.08 하락) 채점 전에 맞춘다."""
    import numpy as np

    loud = np.flatnonzero(np.abs(x) > max(float(np.abs(x).max()) * 0.01, 1e-4))
    return x[loud[0] : loud[-1] + 1] if loud.size else x


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bench", help="benchmark.py 결과 폴더")
    parser.add_argument("--whisper", default="large-v3")
    parser.add_argument("--no-sim", action="store_true")
    args = parser.parse_args()
    folder = Path(args.bench).resolve()
    rows = [r for r in json.loads((folder / "bench.json").read_text(encoding="utf-8")) if r.get("ok")]

    from faster_whisper import WhisperModel

    stt = WhisperModel(args.whisper, device="cpu", compute_type="int8")
    for row in rows:
        segments, _info = stt.transcribe(load_16k(row["path"]), language="ko", beam_size=5, vad_filter=False)
        row["hyp"] = "".join(segment.text for segment in segments).strip()
        row["cer"] = cer(row["text"], row["hyp"])
        print(f"[CER] {row['engine']} {row['style']} {row['index']:02d}: {row['cer']:.3f} | {row['hyp']}", file=sys.stderr)

    ref_pairs: list[float] = []
    if not args.no_sim:
        import torch
        from speechbrain.inference.speaker import EncoderClassifier

        enc = EncoderClassifier.from_hparams(
            "speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(ROOT / ".cache" / "speechbrain" / "spkrec-ecapa-voxceleb"),
            run_opts={"device": "cpu"},
        )
        cache: dict[str, torch.Tensor] = {}

        def embed(path: str) -> torch.Tensor:
            if path not in cache:
                wav = torch.from_numpy(trim_silence(load_16k(path)).copy()).unsqueeze(0)
                cache[path] = enc.encode_batch(wav).squeeze()
            return cache[path]

        def sim(a: str, b: str) -> float:
            return float(torch.nn.functional.cosine_similarity(embed(a), embed(b), dim=0))

        for row in rows:
            row["sim"] = sim(row["ref"], row["path"])
        # 기준선: 같은 사람의 서로 다른 참조 녹음끼리 유사도(엔진이 넘기기 어려운 상한에 가깝다)
        refs = sorted({r["ref"] for r in rows})
        ref_pairs += [sim(a, b) for i, a in enumerate(refs) for b in refs[i + 1:]]

    (folder / "eval.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["engine"], []).append(row)
    lines = [
        "# 엔진 비교 결과",
        "",
        f"문장 {len({r['index'] for r in rows})}개 × 말투 {len({r['style'] for r in rows})}개. "
        "CER은 낮을수록, SIM은 높을수록, RTF는 낮을수록 좋습니다(RTF 1 미만 = 실시간보다 빠름).",
        "",
        "| 엔진 | 장치 | CER 평균 | CER 중앙값 | SIM 평균 | RTF 평균 | 모델 적재(초) |",
        "|---|---|---|---|---|---|---|",
    ]
    for engine_id, items in groups.items():
        cers = [r["cer"] for r in items]
        sims = [r["sim"] for r in items if "sim" in r]
        rtfs = [r["rtf"] for r in items]
        lines.append(
            f"| `{engine_id}` | {items[0].get('device', '')} | {statistics.mean(cers):.3f} | {statistics.median(cers):.3f} | "
            f"{(statistics.mean(sims) if sims else float('nan')):.3f} | {statistics.mean(rtfs):.2f} | "
            f"{max(r['load_sec'] for r in items):.1f} |"
        )
    if ref_pairs:
        lines += ["", f"기준선: 같은 사람의 서로 다른 참조 녹음끼리 SIM {statistics.mean(ref_pairs):.3f}"
                  f"({len(ref_pairs)}쌍). 생성 음성의 SIM이 이 값에 가까울수록 원래 목소리와 구별하기 어렵습니다."]
    lines += ["", "## 말투별", "", "| 엔진 | 말투 | CER 평균 | SIM 평균 | RTF 평균 |", "|---|---|---|---|---|"]
    for engine_id, items in groups.items():
        for style in sorted({r["style"] for r in items}):
            sub = [r for r in items if r["style"] == style]
            sims = [r["sim"] for r in sub if "sim" in r]
            lines.append(
                f"| `{engine_id}` | {style} | {statistics.mean(r['cer'] for r in sub):.3f} | "
                f"{(statistics.mean(sims) if sims else float('nan')):.3f} | {statistics.mean(r['rtf'] for r in sub):.2f} |"
            )
    lines += ["", "## 문장별", "", "| 엔진 | 말투 | # | CER | SIM | 받아쓰기 |", "|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(
            f"| `{row['engine']}` | {row['style']} | {row['index']:02d} | {row['cer']:.3f} | "
            f"{row.get('sim', float('nan')):.3f} | {row['hyp']} |"
        )
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
