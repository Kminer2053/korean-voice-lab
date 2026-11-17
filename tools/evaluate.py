#!/usr/bin/env python3
"""benchmark.py 결과를 채점한다. 받아쓰기 오독률(CER)과 화자 유사도(SIM).

채점 도구는 엔진과 나눈 가상환경(.venv-eval)에 둔다:
  python3.12 -m venv .venv-eval
  .venv-eval/bin/pip install faster-whisper speechbrain torchaudio soundfile
  .venv-eval/bin/python tools/evaluate.py outputs/bench

- CER: faster-whisper(large-v3, CPU int8)로 받아 적어 원문과 글자 단위 편집 거리를 잰다.
  띄어쓰기·문장부호는 빼고 비교한다. 숫자 문장은 받아쓰기 표기 차이로 높게 나올 수 있다.
- SIM: SpeechBrain ECAPA(spkrec-ecapa-voxceleb) 임베딩 코사인 유사도(참조 녹음 대 생성 음성).
  어느 엔진의 내부 인코더도 아닌 독립 모델이다. 1에 가까울수록 참조 목소리와 비슷하다.
결과: <bench>/eval.json, <bench>/report.md
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path


def normalize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


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
        segments, _info = stt.transcribe(row["path"], language="ko", beam_size=5, vad_filter=False)
        row["hyp"] = "".join(segment.text for segment in segments).strip()
        row["cer"] = cer(row["text"], row["hyp"])
        print(f"[CER] {row['engine']} {row['style']} {row['index']:02d}: {row['cer']:.3f} | {row['hyp']}", file=sys.stderr)

    if not args.no_sim:
        import torch
        import torchaudio
        from speechbrain.inference.speaker import EncoderClassifier

        enc = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": "cpu"})
        cache: dict[str, torch.Tensor] = {}

        def embed(path: str) -> torch.Tensor:
            if path not in cache:
                wav, sr = torchaudio.load(path)
                wav = torchaudio.functional.resample(wav.mean(0, keepdim=True), sr, 16000)
                cache[path] = enc.encode_batch(wav).squeeze()
            return cache[path]

        for row in rows:
            row["sim"] = float(torch.nn.functional.cosine_similarity(embed(row["ref"]), embed(row["path"]), dim=0))

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
    lines += ["", "## 문장별", "", "| 엔진 | 말투 | # | CER | SIM | 받아쓰기 |", "|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(
            f"| `{row['engine']}` | {row['style']} | {row['index']:02d} | {row['cer']:.3f} | "
            f"{row.get('sim', float('nan')):.3f} | {row['hyp']} |"
        )
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:6 + len(groups)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
