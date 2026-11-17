#!/usr/bin/env python3
"""엔진 비교용 생성. 같은 참조 녹음·같은 문장으로 엔진마다 WAV 를 만들고 시간을 잰다.

  .venv/bin/python tools/benchmark.py --engines qwen3-mlx,chatterbox-mlx --styles talk,guide -o bench/
  (채점은 tools/evaluate.py — 받아쓰기 오독률·화자 유사도)

결과: <out>/<engine>/<style>/<nn>.wav, <out>/bench.json (문장·시간·길이·RTF).
엔진은 하나씩 순서대로 올리고 내린다(16GB 기기 기준).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import local_env  # noqa: E402,F401
import backends  # noqa: E402
import engine  # noqa: E402
import voices  # noqa: E402

# 낭독·안내·대화·숫자·외래어·긴 문장을 섞은 기본 문장(받아쓰기 비교가 쉽도록 숫자는 한글로 적은 것과 섞음)
SENTENCES = [
    "안녕하세요, 오늘 발표를 맡은 사람입니다.",
    "먼저 우리가 왜 이 일을 시작했는지 보겠습니다.",
    "민원 접수는 평일 오전 아홉 시부터 오후 여섯 시까지입니다.",
    "저녁은 뭐 먹을까요? 시장에 잠깐 같이 나가 볼까요?",
    "와, 이게 진짜 되네요? 정말 다행이에요!",
    "인공지능 비서가 회의록을 정리하고, 담당자에게 할 일을 나눠 줍니다.",
    "2026년 예산은 전년보다 12% 늘어난 3억 5천만 원입니다.",
    "클라우드 서버와 데이터베이스를 점검한 뒤에 서비스를 다시 엽니다.",
    "이번 사업의 핵심은 현장 공무원이 직접 쓰고, 직접 고치고, 직접 퍼뜨리는 도구를 만드는 것입니다.",
    "궁금한 점은 언제든 물어봐 주세요. 감사합니다.",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engines", help="쉼표로 구분한 엔진 id. 없으면 이 컴퓨터에서 쓸 수 있는 전부")
    parser.add_argument("--styles", default="talk,guide")
    parser.add_argument("--sentences", help="문장 파일(.txt 줄마다 하나 또는 .json 목록). 없으면 기본 10문장")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("-o", "--out", default=str(ROOT / "outputs" / "bench"))
    args = parser.parse_args()

    engine_ids = args.engines.split(",") if args.engines else backends.available_ids()
    styles = [voices.resolve(name) for name in args.styles.split(",")]
    if args.sentences:
        raw = Path(args.sentences).read_text(encoding="utf-8")
        sentences = json.loads(raw) if args.sentences.endswith(".json") else [
            line.strip() for line in raw.splitlines() if line.strip() and not line.startswith("#")
        ]
    else:
        sentences = SENTENCES
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for engine_id in engine_ids:
        meta = backends.info(engine_id)
        for style in styles:
            if style.path is None:
                print(f"건너뜀: {style.id} 녹음 없음", file=sys.stderr)
                continue
            for index, text in enumerate(sentences, start=1):
                target = out / engine_id / style.id / f"{index:02d}.wav"
                started = time.perf_counter()
                try:
                    report = engine.synthesize(
                        ref_wav=style.path, ref_text=style.script, text=text, engine=engine_id,
                        output_path=target, seed=args.seed,
                    )
                    row = {
                        "ok": True, "engine": engine_id, "family": meta.family, "runtime": meta.runtime,
                        "device": report.device, "style": style.id, "index": index, "text": text,
                        "path": str(target), "ref": str(style.path), "duration_sec": report.output_duration_sec,
                        "generate_sec": report.generate_sec, "load_sec": report.load_sec,
                        "rtf": report.generate_sec / max(report.output_duration_sec, 1e-6),
                        "peak_memory_bytes": report.peak_memory_bytes,
                    }
                except Exception as exc:
                    row = {"ok": False, "engine": engine_id, "style": style.id, "index": index, "text": text,
                           "error": f"{type(exc).__name__}: {exc}", "wall_sec": time.perf_counter() - started}
                rows.append(row)
                mark = f"{row['duration_sec']:.1f}s 음성 / {row['generate_sec']:.1f}s" if row["ok"] else row["error"]
                print(f"[{engine_id} · {style.id} · {index:02d}] {mark}", file=sys.stderr, flush=True)
        engine.unload_model()
        (out / "bench.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    summary: dict[str, dict] = {}
    for row in rows:
        if not row["ok"]:
            continue
        item = summary.setdefault(row["engine"], {"n": 0, "audio": 0.0, "gen": 0.0, "load": 0.0})
        item["n"] += 1
        item["audio"] += row["duration_sec"]
        item["gen"] += row["generate_sec"]
        item["load"] = max(item["load"], row["load_sec"])
    for engine_id, item in summary.items():
        print(f"{engine_id}: {item['n']}개 · 평균 RTF {item['gen'] / max(item['audio'], 1e-6):.2f} "
              f"(1보다 작으면 실시간보다 빠름) · 모델 적재 {item['load']:.1f}초")
    print(f"결과: {out / 'bench.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
