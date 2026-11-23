<div align="center">

# 🎙️ korean-voice-lab

## Give it a script. It reads it in your voice.

A **local Korean TTS** you set up with ~10 seconds of your own recording. Recordings and results never leave your computer.

![macOS](https://img.shields.io/badge/macOS-Apple%20Silicon%20·%20MLX-000000?logo=apple&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-10%20|%2011%20·%20PyTorch-0078D4?logo=windows)
![Python](https://img.shields.io/badge/Python-3.11–3.13-3776AB?logo=python&logoColor=white)
![Models](https://img.shields.io/badge/models-Qwen3--TTS%20·%20Chatterbox-5E35B1)
![Agents](https://img.shields.io/badge/agents-MCP%20·%20CLI%20·%20HTTP-EA580C)
![Local-first](https://img.shields.io/badge/Local--first-127.0.0.1%20only-2E7D32)
![License](https://img.shields.io/badge/License-MIT-EAB308)
[![npm](https://img.shields.io/npm/v/korean-voice-lab?logo=npm&label=npx)](https://www.npmjs.com/package/korean-voice-lab)

<sub><a href="README.md">한국어</a> · English</sub>

<br>

![Launch video — reading a script in your voice, checking the recording, one file per sentence](docs/assets/demo.gif)

<sub>☝️ Made with <a href="https://github.com/latent-spaces/brag">/brag</a>. The screens are the real app; the voice you hear is a <b>synthetic demo voice</b> this app generated from a macOS built-in voice used as the reference. &nbsp;·&nbsp; <a href="docs/assets/demo.mp4">▶ MP4 with sound (21 s)</a></sub>

### [💾 Install](#-install) · [🤖 Use from agents](#-use-from-ai-agents) · [📊 Validation](#-validation)

</div>

<br>

> [!NOTE]
> **Korean-first.** The UI, docs and text pipeline (number reading, pronunciation dictionary, reference checks) are built for **Korean**. The underlying models speak other languages too, but this project is tuned and validated for Korean narration.

## Sound familiar?

> 🎬 **"I re-record the narration for every video"** — one slip and you start over, then fix pauses and levels clip by clip.

> 🔒 **"I don't want to upload my voice to a cloud service"** — a voice is personal data, like a fingerprint.

> 🤖 **"The AI writes the script, but I still have to read it"** — an agent can build the whole video except the voice.

## At a glance

| | |
|---|---|
| **Who it's for** | People who often make narration, lectures or announcements in their own voice — and the AI agents they hand that work to |
| **What it does** | Record ~10 s per speaking style, then turn any script into WAVs in your voice — one file per sentence, plus subtitles and editor markers |
| **Where it runs** | macOS (Apple Silicon, MLX) · Windows/Linux (PyTorch, NVIDIA CUDA or CPU). The server binds to `127.0.0.1` only |
| **Models** | Qwen3-TTS 0.6B (Alibaba, Apache-2.0) or Chatterbox Multilingual v3 (Resemble AI, MIT) |
| **Your data** | Stays on this computer. Recordings (`references/`) and results (`outputs/`) are git-ignored |
| **Cost** | Free. No account, payment or external API (packages and models are downloaded once) |

## How it works (3 steps)

1. 🎙️ **Record ~10 s** — In **Register voice**, read the sentence on screen. **Record in high quality** turns off the browser's noise suppression, echo cancellation and auto gain and records uncompressed; the recording is checked as soon as it lands (script match, noise, clipping, reverb, …).
2. ✍️ **Paste a script** — In **Make**, enter a sentence or a script and press **Make**. For multiple lines, choose "one file per line / per sentence".
3. ⬇️ **Download** — It plays right under the button; download the WAV. For multiple files, get a zip, a joined WAV, subtitles and editor markers in one go.

> Don't like a take? **Another version of the same sentence**, or **remake only that number** in a multi-file project. No need to start over.

## What you get

| When you make | You get |
|---|---|
| One sentence | One WAV + its seed (same seed → same result) |
| A multi-line script | A project folder like the one below. Insert a line mid-script and **only the changed lines** are regenerated |
| Video options | Loudness **−16 LUFS** (true peak −1 dBTP) · **48 kHz** · speaking rate 0.8–1.25× (pitch preserved) · 1 s pause between paragraphs |

```
outputs/projects/narration/
├─ 001_first-scene.wav
├─ 002_paste-a-script.wav
├─ 003_subtitles-and-markers.wav
├─ narration.wav            ← all lines joined, in order
├─ narration.srt            ← subtitles (original text)
├─ narration_markers.csv    ← editor markers (name, start, end)
└─ manifest.json            ← text, seed, loudness, duration per line
```

## Why it exists

| The usual way | korean-voice-lab |
|---|---|
| Upload your voice to a cloud cloning service | Recordings and results stay on this computer |
| A bad recording registers fine; you find out when the output sounds wrong | Before registering, it checks script match, noise, clipping, reverb and bandwidth, and tells you why |
| Name, order, pause and level every sentence by hand | `001_sentence.wav` order, even loudness, subtitles and markers in one pass |
| A human has to click through a UI | Agents produce it directly over MCP, CLI or HTTP |

<br>

<div align="center"><sub>Below: features, engines, install, agent integration and validation. If you only want to use it, <a href="#-install">Install</a> is all you need.</sub></div>

<br>

## Features

| Area | What you can do |
|---|---|
| 🎙️ **Register voice** | One reference recording per style (default, talk, guide, joy, or your own). Checked, trimmed and level-matched on save; a **test sentence** right after registering |
| ✍️ **Make** | Single block, per line or per sentence; progress, ETA and stop; instant playback; another version; reopen earlier projects |
| 🎬 **For video** | Project folder, zip, joined WAV, SRT, editor markers; −16 LUFS, 48 kHz, speaking rate; regenerate only changed lines |
| 🔤 **Pronunciation** | A dictionary like `배지` → `뺏지` (Latin keys match whole words), preview of the text the model will read, numbers spelled out in Korean for engines that need it |
| 🧠 **Models** | Qwen3-TTS or Chatterbox; runtime picked automatically (macOS MLX, Windows/Linux PyTorch) |
| 🛡️ **Generation guard** | A length-based generation cap (no endless generation), under-reading detection, Qwen3 sentence-ending fix |
| 🤖 **Agents** | MCP (`speak`, `speak_batch`, `list_engines`), CLI, HTTP API, legacy Gradio `/synthesize` compatibility |

## Engines

| Model | macOS (Apple Silicon) | Windows · Linux | Developer | License |
|---|---|---|---|---|
| Qwen3-TTS 0.6B | `qwen3-mlx` (default) | `qwen3-torch` (optional) | Alibaba (China) | Apache-2.0 |
| Chatterbox Multilingual v3 | `chatterbox-mlx` | `chatterbox-torch` (default) | Resemble AI (US) | MIT |

Measured on a Mac (M5, 16 GB) with two recordings of the same person × 10 Korean sentences (2026-11-19). Method: [docs/ENGINES.md](docs/ENGINES.md) (Korean).

| Engine | Transcription error (CER) | Speaker similarity (same person, different recordings: 0.737) | Generation time ÷ audio length | Model load | Peak memory |
|---|---|---|---|---|---|
| `qwen3-mlx` | 0.0% | 0.750 | 0.67 | 2.3 s | 6.2 GB |
| `chatterbox-mlx` | 0.7% | 0.801 | 0.96 | 1.3 s | 4.4 GB |

In the API, CLI and MCP, `engine` can be just `qwen3` or `chatterbox`; the runtime is chosen automatically. Don't mix engines within one video — the voice character changes.

## 💾 Install

| | macOS | Windows |
|---|---|---|
| Computer | Apple Silicon (M1+), validated on 16 GB | 64-bit Windows 10/11. NVIDIA GPU (8 GB+ VRAM) recommended; CPU works but is slow |
| Python | 3.11–3.13 (`brew install python@3.12`) | 3.11–3.12 ([python.org](https://www.python.org/downloads/), with py launcher) |
| Disk | ~6 GB (virtualenv + two models) | ~10 GB (PyTorch + models) |

### One line (npx — macOS, Windows, Linux)

Needs Node.js 18+ and Python. The app is unpacked to `~/.korean-voice-lab` and installed only into virtualenvs there.

```bash
npx korean-voice-lab install          # add --with-qwen on Windows/Linux to also install Qwen3
npx korean-voice-lab start            # open the UI (127.0.0.1:7860)
claude mcp add voicelab -- npx -y korean-voice-lab mcp   # connect your agent
```

`npx korean-voice-lab doctor` shows the install state; `update` switches to the new version's code (recordings and results are kept). You can also clone the repo and use it directly:

### macOS

1. `git clone https://github.com/Kminer2053/korean-voice-lab.git` (or **Code → Download ZIP**).
2. Double-click **`setup.command`** (installs into this folder's `.venv` only).
3. Double-click **`start.command`** — `http://127.0.0.1:7860` opens in your browser.

### Windows

1. Download the repository.
2. Double-click **`setup.bat`**. It creates `.venv` (server) and `.venv-chatterbox`, installs CUDA 12.4 PyTorch if an NVIDIA GPU is present (CPU otherwise), and asks whether to install the Qwen3 engine (`.venv-qwen3`).
3. Double-click **`start.bat`** — `http://127.0.0.1:7860` opens.

The Windows install is validated automatically on GitHub Actions ([windows-smoke](.github/workflows/windows-smoke.yml)).

> **Recording tips:** a quiet room, a hand's width from the mic; start recording, wait 0.5 s, read to the end, wait 0.5 s, stop. Avoid Bluetooth headset mics; on iPhone Voice Memos turn off "Enhance Recording". Record each style the way it should sound — the output follows the reference.

## 🤖 Use from AI agents

Agent guide: [AGENTS.md](AGENTS.md) · request/response format: [docs/API.md](docs/API.md) (both Korean). The **Advanced · Agent connection** tab in the UI shows ready-to-paste configs with real paths and a connection check.

```bash
# MCP (Claude Code; Cursor/Codex configs are in the UI tab)
claude mcp add voicelab -- npx -y korean-voice-lab mcp

# CLI: list of lines → one WAV each + manifest.json (-e picks the model)
npx korean-voice-lab cli batch lines.json -o ~/Desktop/narration -s guide -e chatterbox
# For video: −16 LUFS, 48 kHz, joined WAV + SRT + markers (blank line in TXT = paragraph, 1 s pause)
npx korean-voice-lab cli batch script.txt -o ~/Desktop/narration -s guide --loudness -16 --sample-rate 48000 --timeline

# HTTP
curl -s -X POST http://127.0.0.1:7860/api/tts -H 'Content-Type: application/json' \
  -d '{"text":"안녕하세요","style":"talk","engine":"qwen3"}' -o hello.wav
```

The CLI and MCP send work to the running server if there is one (the model is loaded once); otherwise they load the model themselves.

## 📊 Validation

Checked with `tools/stress.py` (stress test), `selftest.py --generate` (server check) and the legacy `/synthesize` call (2026-11-19).

| Environment | Engine | Generation ÷ audio | Stress test | Server check |
|---|---|---|---|---|
| Mac M5 16 GB (MLX) | `qwen3-mlx` | 0.67 | 202/204 (the 2 errors are a deliberately wrong reference transcript, ending in a clear error). Short (0.9–5.7 s), quiet, noisy and reverberant references all pass | pass |
| Mac M5 16 GB (MLX) | `chatterbox-mlx` | 0.96 | 192/192 | pass |
| Mac M5 (PyTorch CPU) | `qwen3-torch` | median 4.1 | 24/24 | |
| Windows 10, 4-core CPU, no GPU | `qwen3-torch` · `chatterbox-torch` | median 16.5 · 16.5 | Qwen 24/24 + 12 sentence types 12/12 (no endless generation, no timeouts), Chatterbox 24/24 | pass |
| GitHub Actions Windows CPU | `chatterbox-torch` | ~9.5 | | pass (install, reference check, generation, batch) |

- **Found and fixed**
  - If the reference transcript doesn't match the recording, Qwen3 never emitted its stop token and generated up to ~11 minutes of audio (9–14 min per sentence, 14 GB memory on a Mac). Generation now stops at a length-based cap, retries, or fails with a clear reason; the reference check blocks the cause at registration.
  - With noisy references the sentence-ending fix often failed and the same sentence was generated 4 times. Matching the pause threshold to the output's noise floor took failures from 4/12 to 0/12 and average tries from 2.4 to 1.5.
  - Ending-fix failures on English, unpunctuated and multi-line text; near-silent "under-read" results passing as success; phase-inverted stereo recordings becoming silent; picking the wrong port right after a restart.
- **Know this**
  - Windows without a GPU is 15–20× slower than real time (~1 minute for a 3 s sentence). NVIDIA GPUs have not been validated yet.
  - Chatterbox doesn't use the transcript, so transcript mismatch doesn't affect it. Clipped references produce clipped output on both engines, so they are rejected at registration.

<details>
<summary>Check and benchmark tools</summary>

```bash
python3 selftest.py                                   # running server: status, styles, error responses, 127.0.0.1 binding
python3 selftest.py --generate                        # including real generation
.venv/bin/python tools/smoke_engine.py -e chatterbox  # one engine, standalone (no server)
.venv/bin/python tools/benchmark.py --styles talk,guide -o outputs/bench   # engine comparison and speed
.venv-eval/bin/python tools/evaluate.py outputs/bench  # transcription error and speaker similarity (setup in the file header)
.venv/bin/python tools/stress.py -e qwen3 --suite quick -o outputs/stress/q   # stress test (reference condition × sentence type)
```
</details>

<details>
<summary>Layout</summary>

```
app.py              server + UI (Gradio) + legacy /synthesize compatibility
api.py              HTTP API (FastAPI)
service.py          generation, batch, pronunciation dictionary, reference registration (shared logic)
engine.py           engine runner: one engine in memory, one generation at a time
backends/           engine implementations (qwen3_mlx, qwen3_torch, chatterbox_mlx, chatterbox_torch) and worker process
voices.py           style registry (references/voices.json)
audio_prep.py       recording conversion (WAV directly, PyAV otherwise, afconvert fallback on macOS)
audio_fx.py         reference checks and cleanup; output loudness (LUFS), sample rate, leading silence
textnorm.py         numbers → Korean words (for engines that misread digits; also used in scoring)
ending.py           Qwen3 generation guard: length cap, under-read detection, sentence-ending fix
voicelab_cli.py     CLI
mcp_server.py       MCP server (stdio)
bin/                npx launcher
tools/              smoke test, benchmark, scoring, stress test
```
</details>

## Privacy and ethics

> [!IMPORTANT]
> Register **only your own voice, or a voice whose owner has explicitly consented**. The UI won't generate without the consent checkbox.

- Recordings (`references/`), results (`outputs/`), the pronunciation dictionary (`lexicon.json`) and local settings (`settings.json`) are git-ignored.
- When you publish generated audio, say it is synthetic. The Chatterbox PyTorch build watermarks its output.

## How it differs

| Project | Overlap | Where this repo differs |
|---|---|---|
| [jamiepine/voicebox](https://github.com/jamiepine/voicebox) | Local voice cloning, MLX, REST API, MCP, Qwen3-TTS and Chatterbox | Narrow and Korean-first: reference checks (script match, noise, reverb), Korean text handling, a narration pipeline (numbered files, SRT, markers, LUFS, changed-lines-only regeneration), Qwen3 runaway/ending fixes. Voicebox is the far broader studio (8 engines, 23 languages, desktop app, dictation, effects) |
| [Blaizzy/mlx-audio](https://github.com/Blaizzy/mlx-audio) | macOS engine library | An app (UI, API, CLI, MCP) on top of the engines |
| [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), [resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox) | Original models | Both models in one workflow (register → generate → batch) |

## License

- Code: [MIT](LICENSE)
- Model weights are not included; they are downloaded from Hugging Face on first use.
  - Qwen3-TTS ([original](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base), [MLX 8-bit](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit)): Apache-2.0
  - Chatterbox ([original](https://huggingface.co/ResembleAI/chatterbox), [MLX multilingual v3](https://huggingface.co/mlx-community/chatterbox-multilingual-v3)): MIT
- Main dependencies: mlx, mlx-audio (MIT), PyTorch (BSD-3), Gradio (Apache-2.0), FastAPI (MIT), PyAV (BSD-3), SciPy (BSD-3), MCP Python SDK (MIT)
- Launch video: made with [/brag](https://github.com/latent-spaces/brag) (MIT); music and sound effects synthesized in code.
