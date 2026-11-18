#!/usr/bin/env python3
"""엔진 견딤 시험: 참조 녹음 상태 × 문장 종류 × seed 를 돌려 잠재 오류를 찾고 속도를 잰다.

  .venv/bin/python tools/stress.py -e qwen3 --suite quick -o outputs/stress/qwen3
  .venv/bin/python tools/stress.py -e chatterbox --suite full --styles talk -o outputs/stress/cb
  (받아쓰기 확인은 tools/evaluate.py <out> --no-sim — 결과 폴더에 bench.json 도 쓴다)

참조 녹음은 사람 목소리가 아니라 운영체제 내장 음성(맥 say, 윈도우 SAPI)으로 만들고, 그것을 줄이고·늘리고·
잡음을 섞어 상태별 변형을 만든다. --styles 로 등록된 말투를 더할 수 있다(결과는 outputs/ 아래 개인 자료).

항목마다 판정하는 것
- error: 예외. timeout: --timeout 초 안에 안 끝남(작업 프로세스를 죽이고 다음 항목부터 다시 시작)
- runaway: 문장 길이로 어림한 길이보다 훨씬 김(모델이 끝내기를 못 하고 상한까지 생성)
- short: 어림 길이보다 훨씬 짧음(문장 일부만 읽음)
- silent / clipped / nan: 소리 이상
- coda_fail: Qwen3 말끝 보정이 끝내 꼬리말 없이 만듦(stats.ending.coda=false)

결과: <out>/rows.jsonl(항목별), <out>/report.md(요약), <out>/bench.json(evaluate.py 용), <out>/wav/*.wav
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KO_SCRIPT = "이 녹음은 자동 점검에만 쓰는 시험용 목소리입니다. 실제 사람의 목소리가 아닙니다."
EN_SCRIPT = "This is a short reference recording made only for automated testing. It is not a real person."
WRONG_SCRIPT = "오늘 점심은 김치찌개와 계란말이를 먹었습니다."
# 짧은 참조 녹음: 녹음을 중간에서 자르면 대본과 어긋나므로, 온전한 짧은 문장을 따로 만든다
SHORT_SCRIPTS = {
    "short1": "안녕하세요.",
    "short2": "오늘 날씨가 참 좋네요.",
    "short3": "이 녹음은 시험용 목소리입니다.",
    "short4": "이 녹음은 자동 점검에만 쓰는 시험용 목소리입니다.",
    "short5": "이 녹음은 자동 점검에만 쓰는 시험용 목소리이고, 실제 사람의 목소리는 아닙니다.",
}

TEXTS = {
    "normal": "안녕하세요, 오늘 발표를 맡은 사람입니다.",
    "tiny": "네.",
    "nopunct": "안녕",
    "long": (
        "이번 사업의 핵심은 현장 공무원이 직접 쓰고 직접 고치고 직접 퍼뜨리는 도구를 만드는 것이며, "
        "이를 위해 우리는 지난 반년 동안 여러 부서와 함께 작은 시험을 거듭했고 그 결과를 오늘 이 자리에서 "
        "처음으로 자세히 말씀드리려고 합니다."
    ),
    "lines": "먼저 배경을 보겠습니다.\n다음으로 지금 상황을 짚겠습니다.\n마지막으로 할 일을 정리하겠습니다.",
    "english": "Thank you for joining us today. Let's get started.",
    "mixed": "AI 비서가 MLX와 CUDA에서 3.5배 빨라졌고, 자세한 내용은 github.com 에 있습니다.",
    "numbers": "2026년 예산은 12% 늘어난 3억 5천만 원이고, 문의는 010-1234-5678로 주세요.",
    "repeat": "하하하하하하하하하하하하.",
    "punct": "정말요?! ... 네... 그렇군요!!!",
    "symbols": "좋아요 👍 (참고: ※ 표시는 필수입니다) ~ 끝.",
    "ellipsis": "그래서 말인데요...",
}

CORE_TEXTS = ["normal", "tiny", "long", "lines", "english", "mixed"]
REF_VARIANTS = ["ko", "en", "short1", "short2", "short3", "short4", "short5", "long", "pad", "noisy", "reverb", "quiet", "clipped", "lowrate", "wrongtext"]


# ---------------------------------------------------------------- 참조 녹음 만들기

def _read_any(path: Path) -> tuple[np.ndarray, int]:
    from audio_prep import decode_audio

    data, rate, _how = decode_audio(path)
    return np.asarray(data, dtype=np.float32).reshape(-1), int(rate)


def _write(path: Path, data: np.ndarray, rate: int) -> None:
    from audio_prep import write_pcm16

    write_pcm16(Path(path), np.asarray(data, dtype=np.float32), rate)


def _resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x
    n = int(round(x.size * dst / src))
    return np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x).astype(np.float32)


def _os_tts(text: str, lang: str, out_wav: Path) -> None:
    """운영체제 내장 음성으로 참조 녹음을 만든다(사람 목소리 아님)."""
    system = platform.system()
    if system == "Darwin":
        voice = {"ko": "Yuna", "en": "Samantha"}[lang]
        with tempfile.TemporaryDirectory() as tmp:
            aiff = Path(tmp) / "x.aiff"
            subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
            data, rate = _read_any(aiff)
    elif system == "Windows":
        culture = {"ko": "ko-KR", "en": "en-US"}[lang]
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "x.wav"
            txt = Path(tmp) / "x.txt"
            txt.write_text(text, encoding="utf-8")
            script = (
                "Add-Type -AssemblyName System.Speech;"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                f"$v = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -eq '{culture}' }} | Select-Object -First 1;"
                f"if (-not $v) {{ Write-Error 'no {culture} voice'; exit 3 }};"
                "$s.SelectVoice($v.VoiceInfo.Name);"
                f"$s.SetOutputToWaveFile('{raw}');"
                f"$s.Speak([IO.File]::ReadAllText('{txt}', [Text.Encoding]::UTF8));"
                "$s.Dispose()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
            data, rate = _read_any(raw)
    else:
        raise SystemExit("이 운영체제에는 내장 음성이 없습니다. --ref-dir 에 ko.wav·en.wav 를 두세요.")
    _write(out_wav, _resample(data, rate, 24000), 24000)


def _reverb(x: np.ndarray, rate: int, t60: float, rng) -> np.ndarray:
    """울리는 방(잔향 t60 초)을 흉내 낸 녹음."""
    n = int(rate * t60 * 1.2)
    ir = rng.normal(0, 1, n) * np.exp(-6.9 * np.arange(n) / (rate * t60))
    ir[0] = 3.0
    y = np.convolve(x, ir)[: x.size + n]
    return (y / np.abs(y).max() * 0.7).astype(np.float32)


def build_refs(folder: Path, ref_dir: Path | None) -> dict[str, tuple[Path, str]]:
    """참조 변형들: id → (wav, 대본)."""
    folder.mkdir(parents=True, exist_ok=True)
    ko, en = folder / "ko.wav", folder / "en.wav"
    if ref_dir:
        shutil.copyfile(ref_dir / "ko.wav", ko)
        shutil.copyfile(ref_dir / "en.wav", en)
    else:
        if not ko.exists():
            _os_tts(KO_SCRIPT, "ko", ko)
        if not en.exists():
            _os_tts(EN_SCRIPT, "en", en)
    x, rate = _read_any(ko)
    rng = np.random.default_rng(7)
    peak = float(np.abs(x).max()) or 1.0
    variants = {
        "long": (np.concatenate([x, np.zeros(int(rate * 0.5), np.float32)] * 3), " ".join([KO_SCRIPT] * 3)),
        "pad": (np.concatenate([np.zeros(rate * 2, np.float32), x, np.zeros(rate * 2, np.float32)]), KO_SCRIPT),
        "noisy": (x + rng.normal(0, np.sqrt(np.mean(x**2) / 10), x.size).astype(np.float32), KO_SCRIPT),
        "reverb": (_reverb(x, rate, 0.9, rng), KO_SCRIPT),
        "quiet": (x * (0.01 / peak), KO_SCRIPT),
        "clipped": (np.clip(x * (8.0 / peak), -1, 1), KO_SCRIPT),
        "lowrate": (_resample(_resample(x, rate, 8000), 8000, rate), KO_SCRIPT),
        "wrongtext": (x, WRONG_SCRIPT),
    }
    refs = {"ko": (ko, KO_SCRIPT), "en": (en, EN_SCRIPT)}
    for name, script in SHORT_SCRIPTS.items():
        path = folder / f"{name}.wav"
        if not path.exists():
            if ref_dir and (ref_dir / f"{name}.wav").exists():
                shutil.copyfile(ref_dir / f"{name}.wav", path)
            elif not ref_dir:
                _os_tts(script, "ko", path)
            else:
                continue
        refs[name] = (path, script)
    for name, (data, script) in variants.items():
        path = folder / f"{name}.wav"
        if not path.exists():
            _write(path, data, rate)
        refs[name] = (path, script)
    return refs


# ---------------------------------------------------------------- 항목 · 판정

def expected_sec(text: str) -> float:
    """문장을 보통 빠르기로 읽을 때 길이 어림(초)."""
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    digits = len(re.findall(r"\d", text))
    breaks = len(re.findall(r"[.!?\n,]", text))
    return hangul / 6.5 + latin / 12 + digits * 0.3 + breaks * 0.15 + 0.3


def plan(suite: str, refs: list[str], seeds: list[int]) -> list[dict]:
    items: list[dict] = []
    if suite == "quick":
        grid = [(r, t) for r in ["ko", "en", "short2", "noisy"] for t in ["normal", "tiny", "long", "lines", "english", "mixed"]]
        grid = [(r, t) for r, t in grid if r in refs or r.startswith("style:")] + [(r, "normal") for r in refs if r.startswith("style:")]
        seed_list = seeds[:1]
    else:
        base = "ko"
        grid = [(base, t) for t in TEXTS] + [(r, t) for r in refs if r != base for t in CORE_TEXTS]
        seed_list = seeds
    for ref_id, text_id in grid:
        for seed in seed_list:
            items.append({"ref": ref_id, "text_id": text_id, "seed": seed})
    for index, item in enumerate(items):
        item["index"] = index
    return items


def analyse(path: Path, text: str) -> dict:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    duration = pcm.size / rate
    hop = max(1, rate // 100)
    n = pcm.size // hop
    env = np.sqrt(np.mean(pcm[: n * hop].reshape(n, hop) ** 2, axis=1)) if n else np.zeros(1)
    peak_env = float(env.max()) if env.size else 0.0
    voiced = np.flatnonzero(env > max(peak_env * 0.05, 1e-4))
    speech_sec = ((voiced[-1] - voiced[0] + 1) / 100) if voiced.size else 0.0
    expect = expected_sec(text)
    flags = []
    if not np.isfinite(pcm).all():
        flags.append("nan")
    if peak_env < 0.003:
        flags.append("silent")
    if np.mean(np.abs(pcm) >= 0.999) > 0.001:
        flags.append("clipped")
    if speech_sec > 3 * expect + 4:
        flags.append("runaway")
    if expect > 1.5 and speech_sec < 0.4 * expect:
        flags.append("short")
    return {"duration_sec": round(duration, 2), "speech_sec": round(speech_sec, 2), "expected_sec": round(expect, 2),
            "peak": round(float(np.abs(pcm).max()), 3), "flags": flags}


# ---------------------------------------------------------------- 실행(자식 프로세스)

def child(args: argparse.Namespace) -> int:
    import local_env  # noqa: F401
    import engine

    out = Path(args.out)
    refs = {k: (Path(p), s) for k, (p, s) in json.loads((out / "refs.json").read_text(encoding="utf-8")).items()}
    items = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    done = {json.loads(line)["index"] for line in (out / "rows.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()} \
        if (out / "rows.jsonl").exists() else set()
    for item in items:
        if item["index"] in done:
            continue
        (out / "current.json").write_text(json.dumps({**item, "started": time.time()}), encoding="utf-8")
        ref_wav, ref_text = refs[item["ref"]]
        text = TEXTS[item["text_id"]]
        target = out / "wav" / f"{item['index']:03d}_{item['ref'].replace(':', '-')}_{item['text_id']}_s{item['seed']}.wav"
        row = {**item, "engine": args.engine, "text": text}
        started = time.perf_counter()
        try:
            report = engine.synthesize(ref_wav=ref_wav, ref_text=ref_text, text=text, engine=args.engine,
                                       output_path=target, seed=item["seed"])
            row.update(ok=True, engine=report.engine_id, device=report.device, path=str(target), ref_path=str(ref_wav),
                       generate_sec=round(report.generate_sec, 2), load_sec=round(report.load_sec, 2),
                       peak_memory_bytes=report.peak_memory_bytes, stats=report.stats)
            row.update(analyse(target, text))
            row["rtf"] = round(report.generate_sec / max(row["duration_sec"], 1e-6), 3)
            ending = (report.stats or {}).get("ending")
            if ending and not ending.get("coda"):
                row["flags"].append("coda_fail")
        except Exception as exc:  # 한 항목이 실패해도 계속
            row.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:500], flags=["error"],
                       wall_sec=round(time.perf_counter() - started, 1))
        with (out / "rows.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        mark = ",".join(row["flags"]) or "ok"
        detail = f"{row.get('duration_sec', 0):.1f}s/{row.get('generate_sec', 0):.1f}s" if row["ok"] else row["error"][:120]
        print(f"[{item['index'] + 1}/{len(items)}] {item['ref']} · {item['text_id']} · s{item['seed']}: {mark} {detail}",
              file=sys.stderr, flush=True)
    (out / "current.json").unlink(missing_ok=True)
    return 0


# ---------------------------------------------------------------- 실행(감독)

def supervise(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    refs = build_refs(out / "refs", Path(args.ref_dir) if args.ref_dir else None)
    if args.styles:
        import local_env  # noqa: F401
        import voices

        for name in args.styles.split(","):
            style = voices.resolve(name)
            if style.path is None:
                raise SystemExit(f"말투 {name} 에 녹음이 없습니다.")
            refs[f"style:{style.id}"] = (style.path, style.script)
    (out / "refs.json").write_text(json.dumps({k: (str(p), s) for k, (p, s) in refs.items()}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    if args.refs:
        keep = set(args.refs.split(","))
        refs = {k: v for k, v in refs.items() if k in keep or k == "ko"}
    seeds = [int(s) for s in args.seeds.split(",")]
    items = plan(args.suite, list(refs), seeds)
    if args.refs:
        items = [i for i in items if i["ref"] in keep]
        for index, item in enumerate(items):
            item["index"] = index
    plan_path = out / "plan.json"
    if plan_path.exists() and not args.fresh:
        old = json.loads(plan_path.read_text(encoding="utf-8"))
        if old != items:
            raise SystemExit("이전 계획과 다릅니다. 이어 하려면 같은 옵션을, 새로 하려면 --fresh 를 주세요.")
    if args.fresh:
        for name in ("rows.jsonl", "current.json"):
            (out / name).unlink(missing_ok=True)
    plan_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    cmd = [sys.executable, str(Path(__file__).resolve()), "--child", "-e", args.engine, "-o", str(out)]
    while True:
        done = _done(out)
        if len(done) >= len(items):
            break
        proc = subprocess.Popen(cmd, cwd=str(ROOT))
        timed_out = False
        while proc.poll() is None:
            time.sleep(1)
            cur = _current(out)
            if cur and time.time() - cur["started"] > args.timeout:
                _kill_tree(proc)
                _append(out, {**{k: cur[k] for k in ("index", "ref", "text_id", "seed")}, "engine": args.engine,
                              "text": TEXTS[cur["text_id"]], "ok": False, "flags": ["timeout"],
                              "error": f"{args.timeout}초 안에 끝나지 않아 멈춤", "wall_sec": args.timeout})
                print(f"[timeout] #{cur['index']} {cur['ref']} · {cur['text_id']}", file=sys.stderr, flush=True)
                timed_out = True
                break
        if not timed_out and proc.poll() is not None and proc.returncode != 0:  # 시간 초과로 끊은 것은 정상 진행
            cur = _current(out)
            if cur and cur["index"] not in _done(out):
                _append(out, {**{k: cur[k] for k in ("index", "ref", "text_id", "seed")}, "engine": args.engine,
                              "text": TEXTS[cur["text_id"]], "ok": False, "flags": ["crash"],
                              "error": f"프로세스가 코드 {proc.returncode}로 끝남"})
            elif not cur:
                raise SystemExit(f"시험 프로세스가 시작하지 못했습니다(코드 {proc.returncode}).")
    return summarise(out, args)


def _done(out: Path) -> set[int]:
    path = out / "rows.jsonl"
    if not path.exists():
        return set()
    return {json.loads(line)["index"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _current(out: Path) -> dict | None:
    try:
        return json.loads((out / "current.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _append(out: Path, row: dict) -> None:
    with (out / "rows.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out / "current.json").unlink(missing_ok=True)


def _kill_tree(proc: subprocess.Popen) -> None:
    """시험 프로세스와 그 작업 프로세스(다른 가상환경 엔진)까지 끝낸다."""
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            import signal

            for line in subprocess.run(["pgrep", "-P", str(proc.pid)], capture_output=True, text=True).stdout.split():
                os.kill(int(line), signal.SIGKILL)
        except Exception:
            pass
        proc.kill()
    proc.wait()


def _ref_lengths(out: Path) -> str:
    refs = json.loads((out / "refs.json").read_text(encoding="utf-8"))
    parts = []
    for name, (path, _script) in refs.items():
        if name.startswith("style:"):
            parts.append(name)
            continue
        with wave.open(path, "rb") as handle:
            parts.append(f"{name} {handle.getnframes() / handle.getframerate():.1f}")
    return ", ".join(parts)


def summarise(out: Path, args: argparse.Namespace) -> int:
    rows = sorted((json.loads(line) for line in (out / "rows.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()),
                  key=lambda r: r["index"])
    ok = [r for r in rows if r.get("ok")]
    flagged = [r for r in rows if r.get("flags")]
    counts: dict[str, int] = {}
    for row in rows:
        for flag in row.get("flags", []):
            counts[flag] = counts.get(flag, 0) + 1
    rtfs = [r["rtf"] for r in ok]
    gens = [r["generate_sec"] for r in ok]
    tries = [r["stats"]["ending"]["tries"] for r in ok if (r.get("stats") or {}).get("ending")]
    env = f"{platform.system()} {platform.release()} · {platform.machine()} · {os.cpu_count()} cores"
    device = ok[0]["device"] if ok else "?"
    lines = [
        f"# 견딤 시험: {args.engine} ({args.suite})",
        "",
        f"- 환경: {env} · 장치 {device}",
        f"- 항목 {len(rows)}개 · 성공 {len(ok)}개 · 문제 표시 {len(flagged)}개 {counts or ''}",
        f"- 참조 녹음 길이(초): {_ref_lengths(out)}",
    ]
    if ok:
        lines += [
            f"- RTF(생성 시간 ÷ 음성 길이) 평균 {statistics.mean(rtfs):.2f} · 중앙값 {statistics.median(rtfs):.2f} · 최대 {max(rtfs):.2f}",
            f"- 항목 생성 시간 중앙값 {statistics.median(gens):.1f}초 · 최대 {max(gens):.1f}초 · 모델 적재 {max(r['load_sec'] for r in ok):.1f}초",
        ]
        peaks = [r["peak_memory_bytes"] for r in ok if r.get("peak_memory_bytes")]
        if peaks:
            lines.append(f"- 최대 메모리 {max(peaks) / 2**30:.2f} GB")
        if tries:
            lines.append(f"- 말끝 보정 시도 수: 1회 {tries.count(1)} · 2회 {tries.count(2)} · 3회 {tries.count(3)} · "
                         f"실패(꼬리말 없이) {counts.get('coda_fail', 0)}")
    lines += ["", "| # | 참조 | 문장 | seed | 판정 | 길이(어림) | 생성 | RTF | 비고 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        note = r.get("error", "") if not r.get("ok") else ""
        ending = (r.get("stats") or {}).get("ending")
        if ending:
            note = f"말끝 {ending['tries']}회" + ("" if ending.get("coda") else "·실패")
        lines.append(
            f"| {r['index']} | {r['ref']} | {r['text_id']} | {r['seed']} | {','.join(r.get('flags', [])) or 'ok'} | "
            f"{r.get('duration_sec', '-')}({r.get('expected_sec', '-')}) | {r.get('generate_sec', r.get('wall_sec', '-'))} | "
            f"{r.get('rtf', '-')} | {note[:80]} |"
        )
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    bench = [{"ok": True, "engine": r["engine"], "style": r["ref"], "index": r["index"], "text": r["text"], "path": r["path"],
              "ref": r["ref_path"], "rtf": r["rtf"], "load_sec": r["load_sec"], "device": r.get("device", "")} for r in ok]
    (out / "bench.json").write_text(json.dumps(bench, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines[:8]))
    print(f"결과: {out / 'report.md'}")
    return 1 if any(f in counts for f in ("error", "timeout", "crash", "runaway", "nan")) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("-e", "--engine", required=True, help="모델(qwen3, chatterbox) 또는 엔진 id")
    parser.add_argument("--suite", choices=["quick", "full"], default="quick")
    parser.add_argument("--seeds", default="0,10", help="full 에서 쓸 seed 목록(quick 은 첫 값만)")
    parser.add_argument("--styles", help="더할 등록 말투(쉼표 구분). 사용자 녹음이므로 결과는 개인 자료")
    parser.add_argument("--refs", help="이 참조 변형만(쉼표 구분, 예: short1,short2,quiet)")
    parser.add_argument("--ref-dir", help="내장 음성 대신 쓸 ko.wav·en.wav 폴더(대본은 이 파일의 KO_SCRIPT·EN_SCRIPT)")
    parser.add_argument("--timeout", type=float, default=900, help="항목 하나의 최대 시간(초)")
    parser.add_argument("--fresh", action="store_true", help="이전 결과를 지우고 새로 시작")
    parser.add_argument("-o", "--out", default=str(ROOT / "outputs" / "stress"))
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child(args)
    return supervise(args)


if __name__ == "__main__":
    sys.exit(main())
