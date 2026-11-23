<div align="center">

# 🎙️ 내 목소리 생성기

## 대본만 주세요. 내 목소리로 읽어 드릴게요.

녹음 10초로 만드는 **로컬 한국어 TTS** — 녹음과 결과는 이 컴퓨터 밖으로 나가지 않습니다.

![macOS](https://img.shields.io/badge/macOS-Apple%20Silicon%20·%20MLX-000000?logo=apple&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-10%20|%2011%20·%20PyTorch-0078D4?logo=windows)
![Python](https://img.shields.io/badge/Python-3.11–3.13-3776AB?logo=python&logoColor=white)
![모델](https://img.shields.io/badge/모델-Qwen3--TTS%20·%20Chatterbox-5E35B1)
![에이전트](https://img.shields.io/badge/에이전트-MCP%20·%20명령줄%20·%20HTTP-EA580C)
![Local-first](https://img.shields.io/badge/Local--first-127.0.0.1%20전용-2E7D32)
![License](https://img.shields.io/badge/License-MIT-EAB308)
[![npm](https://img.shields.io/npm/v/korean-voice-lab?logo=npm&label=npx)](https://www.npmjs.com/package/korean-voice-lab)

<sub>한국어 · <a href="README.en.md">English</a></sub>

<br>

![홍보 영상 — 대본을 내 목소리로 읽고, 녹음을 검사하고, 문장마다 파일을 만드는 흐름](docs/assets/demo.gif)

<sub>☝️ 이 영상은 <a href="https://github.com/latent-spaces/brag">/brag</a>로 만들었습니다. 화면은 실제 앱이고, 들리는 목소리는 맥 내장 음성을 참조 녹음으로 써서 이 앱이 만든 <b>시험용 합성 목소리</b>입니다. &nbsp;·&nbsp; <a href="docs/assets/demo.mp4">▶ 소리 있는 MP4(21초)</a></sub>

### [💾 5분 설치](#-5분-설치) · [🤖 에이전트에서 쓰기](#-ai-에이전트에서-쓰기) · [📊 검증 결과](#-검증-결과)

</div>

<br>

## 이런 상황, 익숙하신가요?

> 🎬 **"영상마다 내레이션을 다시 녹음한다"** — 한 문장 틀리면 처음부터, 문장 사이 쉼과 음량은 편집 프로그램에서 하나씩.

> 🔒 **"내 목소리를 클라우드 서비스에 올리기는 꺼려진다"** — 목소리는 지문 같은 개인정보니까.

> 🤖 **"AI가 대본은 써 주는데, 읽는 건 결국 내가"** — 에이전트가 영상까지 만들 수 있는데 목소리만 사람 손을 탄다.

## 한눈에 보기

| | |
|---|---|
| **누&#8288;구&#8288;를 위&#8288;한 것** | 영상 내레이션·강의·안내 음성을 자기 목소리로 자주 만드는 사람, 그리고 그 일을 맡길 AI 에이전트 |
| **무&#8288;엇&#8288;을 하&#8288;나** | 말투별로 10초쯤 녹음해 두면, 대본을 내 목소리로 읽은 WAV를 만듦. 문장마다 파일·자막·편집 마커까지 |
| **어&#8288;디&#8288;서 도&#8288;나** | 맥(Apple Silicon, MLX) · 윈도우·리눅스(PyTorch, NVIDIA CUDA 또는 CPU). 서버는 `127.0.0.1`에만 열림 |
| **AI 모&#8288;델** | Qwen3-TTS 0.6B(Alibaba, Apache-2.0) · Chatterbox Multilingual v3(Resemble AI, MIT) 중 선택 |
| **데&#8288;이&#8288;터 저&#8288;장** | 전부 이 컴퓨터. 녹음(`references/`)·결과(`outputs/`)는 git에도 올라가지 않음 |
| **비&#8288;용** | 무료. 계정·결제·외부 API 없음(처음 한 번 패키지와 모델만 내려받음) |

## 이렇게 씁니다 (초간단 3단계)

1. 🎙️ **10초 녹음** — **목소리 등록** 탭에서 화면의 문장을 읽습니다. **고음질로 녹음**은 브라우저의 잡음 제거·자동 음량을 끄고 압축 없이 녹음하고, 올리자마자 녹음 검사(대본 맞춤·잡음·찢어짐·울림 등)가 끝납니다.
2. ✍️ **대본 붙여 넣기** — **만들기** 탭에 문장이나 대본을 넣고 **만들기**. 여러 줄이면 "줄마다·문장마다"를 고릅니다.
3. ⬇️ **받기** — 버튼 바로 아래에서 재생되고 WAV로 받습니다. 여러 파일이면 zip·이어 붙인 WAV·자막·편집 마커를 한 번에.

> 마음에 안 드는 결과는 **같은 문장 다른 버전**, 여러 파일이면 **그 번호만 다시 만들기**. 처음부터 다시 만들 필요가 없습니다.

## 결과물은 이렇게 생겼습니다

| 만들 때 | 나오는 것 |
|---|---|
| 한 문장 | WAV 하나 + seed(같은 seed면 같은 결과를 다시 얻음) |
| 대본 여러 줄 | 아래처럼 프로젝트 폴더. 대본 중간에 줄을 넣어도 **바뀐 줄만** 새로 만듦 |
| 영상용 옵션 | 음량 **−16 LUFS**(트루 피크 −1 dBTP) · **48kHz** · 말 빠르기 0.8–1.25배(음높이 그대로) · 문단 사이 1초 쉼 |

```
outputs/projects/내레이션/
├─ 001_첫-번째-장면입니다.wav
├─ 002_대본을-붙여-넣으면-문장마다.wav
├─ 003_자막과-편집-마커도-함께.wav
├─ narration.wav            ← 순서대로 이어 붙인 한 파일
├─ narration.srt            ← 자막(원문 그대로)
├─ narration_markers.csv    ← 편집 프로그램 마커(이름·시작·끝)
└─ manifest.json            ← 문장·seed·음량·길이 기록
```

## 왜 만들었나

| 보통의 방식 | 내 목소리 생성기 |
|---|---|
| 클라우드 음성 복제 서비스에 목소리를 올림 | 녹음·결과 모두 이 컴퓨터 안에서만 |
| 녹음이 나빠도 등록되고, 결과가 이상해야 알게 됨 | 등록 전에 대본 맞춤·잡음·찢어짐·울림·대역을 검사해 이유를 알려 줌 |
| 문장마다 파일 이름·순서·쉼·음량을 손으로 맞춤 | `001_문장.wav` 순서, 고른 음량, 자막·마커까지 한 번에 |
| 사람이 화면에서 눌러야 함 | MCP·명령줄·HTTP로 에이전트가 직접 만듦 |

<br>

<div align="center"><sub>여기부터는 기능 상세, 설치, 에이전트 연결, 검증 결과입니다. 쓰기만 할 분은 <a href="#-5분-설치">5분 설치</a>만 보시면 됩니다.</sub></div>

<br>

## 주요 기능

| 기능 | 할 수 있는 일 |
|---|---|
| 🎙️&nbsp;**목&#8288;소&#8288;리 등&#8288;록** | 말투(기본·대화·안내·기쁨, 직접 추가 가능)마다 참조 녹음. 녹음 검사 후 앞뒤 무음·음량을 다듬어 저장, 등록 뒤 **시험 문장**으로 바로 확인 |
| ✍️&nbsp;**만&#8288;들&#8288;기** | 한 덩어리·줄마다·문장마다, 진행·남은 시간·멈추기, 결과 바로 재생, 다른 버전, 이전 프로젝트 불러오기 |
| 🎬&nbsp;**영&#8288;상&#8288;용** | 프로젝트 폴더·zip·이어 붙인 WAV·SRT·편집 마커, −16 LUFS·48kHz·말 빠르기, 바뀐 줄만 다시 만들기 |
| 🔤&nbsp;**발&#8288;음 고&#8288;치&#8288;기** | `배지` → `뺏지` 같은 발음 사전(영문은 단어 단위), 읽을 문장 미리 보기, 숫자는 엔진에 맞게 한국어 소리로 |
| 🧠&nbsp;**모&#8288;델 고&#8288;르&#8288;기** | Qwen3-TTS·Chatterbox, 실행 방식은 자동(맥 MLX, 윈도우·리눅스 PyTorch) |
| 🛡️&nbsp;**생&#8288;성 감&#8288;독** | 문장 길이에 맞춘 생성 상한(끝없는 생성 막기), 덜 읽음 감지, Qwen3 말끝 보정 |
| 🤖&nbsp;**에&#8288;이&#8288;전&#8288;트** | MCP(`speak`·`speak_batch`·`list_engines`), 명령줄, HTTP API, 예전 Gradio `/synthesize` 호환 |

## 엔진

| 모델 | 맥(Apple Silicon) | 윈도우·리눅스 | 개발 주체 | 라이선스 |
|---|---|---|---|---|
| Qwen3-TTS 0.6B | `qwen3-mlx` (기본) | `qwen3-torch` (선택 설치) | Alibaba(중국) | Apache-2.0 |
| Chatterbox Multilingual v3 | `chatterbox-mlx` | `chatterbox-torch` (기본) | Resemble AI(미국) | MIT |

맥(M5 16GB)에서 같은 사람의 녹음 2개 × 문장 10개로 비교한 결과입니다(2026-11-19). 측정 방법은 [docs/ENGINES.md](docs/ENGINES.md#맥-비교-결과)에 있습니다.

| 엔진 | 받아쓰기 오독률 | 화자 유사도 (같은 사람 녹음끼리 0.737) | 생성 시간 ÷ 음성 길이 | 모델 적재 | 최대 메모리 |
|---|---|---|---|---|---|
| `qwen3-mlx` | 0.0% | 0.750 | 0.67 | 2.3초 | 6.2GB |
| `chatterbox-mlx` | 0.7% | 0.801 | 0.96 | 1.3초 | 4.4GB |

API·명령줄·MCP에서 `engine`에 `qwen3`이나 `chatterbox`만 적으면 실행 방식은 자동으로 골라집니다. 한 영상 안에서는 엔진을 섞지 마세요(목소리 느낌이 달라집니다).

## 💾 5분 설치

| | 맥 | 윈도우 |
|---|---|---|
| 컴퓨터 | Apple Silicon(M1 이상). 16GB에서 검증 | 64비트 Windows 10/11. NVIDIA GPU(VRAM 8GB 이상) 권장, 없으면 CPU(느림) |
| Python | 3.11–3.13 (`brew install python@3.12`) | 3.11–3.12 ([python.org](https://www.python.org/downloads/), py launcher 포함) |
| 디스크 | 약 6GB(가상환경과 모델 두 개) | 약 10GB(PyTorch와 모델) |

### 한 줄 설치 (npx, 맥·윈도우·리눅스)

Node.js 18 이상과 Python이 있으면 됩니다. 앱은 `~/.korean-voice-lab`에 펼쳐지고 그 안의 가상환경에만 설치됩니다.

```bash
npx korean-voice-lab install          # 윈도우·리눅스에서 Qwen3도 쓰려면 --with-qwen
npx korean-voice-lab start            # 화면 열기(127.0.0.1:7860)
claude mcp add voicelab -- npx -y korean-voice-lab mcp   # 에이전트에 연결
```

`npx korean-voice-lab doctor`로 상태를 보고, `update`로 새 버전 코드로 바꿉니다(녹음·결과는 그대로). 아래처럼 저장소를 직접 받아 써도 됩니다.

### 맥

1. 저장소를 내려받습니다. `git clone https://github.com/Kminer2053/korean-voice-lab.git` 또는 **Code → Download ZIP**.
2. **`setup.command`**를 더블클릭합니다. 이 폴더의 `.venv`에만 설치합니다.
3. **`start.command`**를 더블클릭하면 브라우저에 `http://127.0.0.1:7860`이 열립니다.

> 처음 열 때 "확인되지 않은 개발자" 경고가 뜨면 파일을 우클릭한 뒤 **열기**를 누르세요. 실행 권한 오류가 나면 `chmod +x setup.command start.command`.

```bash
# 터미널로 설치할 때
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt     # 검증된 고정 버전(서버 + MLX 엔진)
.venv/bin/python app.py --open
```

### 윈도우

1. 저장소를 내려받습니다.
2. **`setup.bat`**를 더블클릭합니다. 서버용 `.venv`와 Chatterbox용 `.venv-chatterbox`를 만들고, NVIDIA GPU가 있으면 CUDA 12.4, 없으면 CPU PyTorch를 설치합니다. Qwen3 엔진(`.venv-qwen3`)을 설치할지 묻습니다.
3. **`start.bat`**를 더블클릭하면 `http://127.0.0.1:7860`이 열립니다.

설치 과정은 GitHub Actions의 Windows 러너에서 자동으로 검증합니다([windows-smoke](.github/workflows/windows-smoke.yml)).

<details>
<summary>리눅스</summary>

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements/server.txt
python3.12 -m venv .venv-chatterbox
.venv-chatterbox/bin/pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124   # GPU 없으면 /whl/cpu
.venv-chatterbox/bin/pip install -r requirements/engine-chatterbox.txt
.venv-chatterbox/bin/pip install --no-deps -r requirements/engine-chatterbox-src.txt   # 다국어 v3 를 읽는 GitHub 판(git 불필요)
.venv/bin/python app.py
```
</details>

7860번을 다른 프로그램이 쓰고 있으면 다음 빈 포트를 쓰고 주소를 알려 줍니다(`--port`로 지정 가능).

> **녹음 팁:** 조용한 방에서 입과 한 뼘 떨어져, 녹음을 켜고 0.5초 쉰 뒤 읽기 시작해 끝까지 읽고 0.5초 쉰 뒤 멈춥니다. 블루투스 이어폰 마이크는 피하고, 아이폰 음성 메모는 '녹음 향상'을 끕니다. 말투마다 그 말투답게 읽은 녹음을 두면 결과도 그 말투를 따라갑니다.

## 🤖 AI 에이전트에서 쓰기

자세한 안내는 [AGENTS.md](AGENTS.md), 요청·응답 형식은 [docs/API.md](docs/API.md)에 있습니다. 서버 화면의 **고급 · 에이전트 연결** 탭에는 실제 경로가 채워진 설정 예시와 연결 확인 버튼이 있습니다.

```bash
# MCP (Claude Code 예시. Cursor·Codex 설정은 화면 탭 참고)
claude mcp add voicelab -- "$PWD/.venv/bin/python" "$PWD/mcp_server.py"

# 명령줄: 대사 목록 → WAV 여러 개 + manifest.json (모델 지정은 -e)
.venv/bin/python voicelab_cli.py batch examples/lines.json -o ~/Desktop/narration -s guide -e chatterbox
# 영상용: −16 LUFS, 48kHz, 이어 붙인 WAV·자막·마커(TXT의 빈 줄 = 문단, 1초 쉼)
.venv/bin/python voicelab_cli.py batch script.txt -o ~/Desktop/narration -s guide --loudness -16 --sample-rate 48000 --timeline
# 조금 빠르게(음높이는 그대로)
.venv/bin/python voicelab_cli.py say "화면 전환에 맞춰 조금 빠르게 읽습니다." -s guide --speed 1.1 -o fast.wav

# HTTP
curl -s -X POST http://127.0.0.1:7860/api/tts -H 'Content-Type: application/json' \
  -d '{"text":"안녕하세요","style":"talk","engine":"qwen3"}' -o hello.wav
```

에이전트에게는 이렇게 부탁하면 됩니다. *"`plan.json`의 대사를 voicelab MCP로 안내 말투로 만들어 `voice/` 폴더에 넣어 줘. 영상용으로 자막까지."*

윈도우에서는 `.venv/bin/python` 대신 `.venv\Scripts\python`을 씁니다. 명령줄과 MCP는 서버가 켜져 있으면 서버로 보내고(모델을 한 번만 올림), 꺼져 있으면 직접 모델을 올립니다.

## 📊 검증 결과

`tools/stress.py`(견딤 시험), `selftest.py --generate`(서버 점검), 예전 `/synthesize` 호출로 확인했습니다(2026-11-19).

| 환경 | 엔진 | 생성 시간 ÷ 음성 길이 | 견딤 시험 | 서버 점검 |
|---|---|---|---|---|
| 맥 M5 16GB (MLX) | `qwen3-mlx` | 0.67 | 204개 중 202개 성공(오류 2개는 일부러 대본을 틀리게 준 참조 — 이유를 담은 오류로 끝남). 0.9–5.7초 짧은 참조·작은 녹음·잡음·울림 참조 모두 성공 | 통과 |
| 맥 M5 16GB (MLX) | `chatterbox-mlx` | 0.96 | 192/192 | 통과 |
| 맥 M5 (PyTorch CPU) | `qwen3-torch` | 중앙값 4.1 | 24/24 | |
| 윈도우 10, 4코어 CPU, GPU 없음 | `qwen3-torch` · `chatterbox-torch` | 중앙값 16.5 · 16.5 | Qwen 24/24 + 문장 12종 12/12(끝없는 생성·시간 초과 없음), Chatterbox 24/24 | 통과 |
| GitHub Actions 윈도우 CPU | `chatterbox-torch` | 약 9.5 | | 통과(설치·녹음 검사·생성·일괄) |

- **찾아서 고친 것**
  - 참조 녹음의 대본이 실제 녹음과 어긋나면 Qwen3가 끝맺지 못하고 약 11분 분량까지 생성했습니다(맥에서 문장 하나에 9–14분, 메모리 14GB). 이제 문장 길이에 맞춘 상한에서 멈추고 다시 만들거나 이유를 담은 오류를 냅니다. 등록할 때는 녹음 검사가 같은 원인을 미리 막습니다.
  - 잡음 섞인 참조 녹음은 말끝 보정이 자주 실패해 같은 문장을 4번씩 만들었습니다. 쉼 기준을 결과의 잡음 바닥에 맞춰 실패 4/12 → 0/12, 평균 시도 2.4 → 1.5회.
  - 영어 문장·문장부호 없는 짧은 문장·여러 줄 문장의 말끝 보정 실패, 덜 읽은 결과(무음에 가까움)가 성공으로 나가던 문제, 위상이 반대인 스테레오 녹음이 무음이 되던 문제, 서버를 다시 켜면 포트를 잘못 비켜 가던 문제.
- **알아 둘 점**
  - GPU 없는 윈도우는 실시간보다 15–20배 느립니다(3초 문장에 약 1분). NVIDIA GPU에서는 아직 확인하지 못했습니다.
  - Chatterbox는 대본을 쓰지 않아 대본 불일치의 영향을 받지 않습니다. 찢어진 참조 녹음은 두 엔진 모두 결과도 찢어지므로 등록 단계에서 거절합니다.

<details>
<summary>점검·비교 도구</summary>

```bash
python3 selftest.py                                   # 켜진 서버: 상태·말투·오류 응답·127.0.0.1 바인딩
python3 selftest.py --generate                        # 실제 생성까지
.venv/bin/python tools/smoke_engine.py -e chatterbox  # 엔진 하나 단독 생성(서버 없이)
.venv/bin/python tools/benchmark.py --styles talk,guide -o outputs/bench   # 엔진 비교 생성·속도
.venv-eval/bin/python tools/evaluate.py outputs/bench  # 받아쓰기 오독률·화자 유사도(설치법은 파일 머리말)
.venv/bin/python tools/stress.py -e qwen3 --suite quick -o outputs/stress/q   # 견딤 시험(참조 녹음 상태 × 문장 종류)
```

`tools/stress.py`는 운영체제 내장 음성(맥 `say`, 윈도우 SAPI)으로 시험용 참조 녹음을 만들고, 짧게·길게·잡음·울림·작은 소리·찢어짐·전화 음질·대본 불일치로 바꿔 가며 문장 12종을 만들어 봅니다. 항목마다 끝맺지 못함·덜 읽음·무음·찢어짐·시간 초과·말끝 보정 실패를 판정합니다.
</details>

<details>
<summary>구조</summary>

```
app.py              서버 실행 + 화면(Gradio) + 예전 /synthesize 호환
api.py              HTTP API (FastAPI)
service.py          생성·일괄·발음 사전·참조 등록 (공용 로직)
engine.py           엔진 실행기: 엔진 하나만 메모리에, 생성은 한 번에 하나
backends/           엔진 구현(qwen3_mlx, qwen3_torch, chatterbox_mlx, chatterbox_torch)과 작업 프로세스
voices.py           말투 레지스트리 (references/voices.json)
audio_prep.py       녹음 변환(WAV 직접, 그 밖은 PyAV, 맥은 afconvert 대체)
audio_fx.py         녹음 검사(대본 맞춤·잡음·찢어짐 등)·녹음 다듬기, 결과 음량(LUFS)·표본율·앞 무음
textnorm.py         숫자를 한국어 소리로(숫자를 잘못 읽는 엔진용, 채점에도 사용)
ending.py           Qwen3 생성 감독: 생성 상한·덜 읽음 감지·말끝 보정(꼬리말을 붙여 만들고 그 앞 쉼에서 자름)
voicelab_cli.py     명령줄
mcp_server.py       MCP 서버(stdio)
selftest.py         서버 점검
tools/              엔진 단독 점검·비교 생성·채점·견딤 시험(stress.py)
requirements/       서버·맥 MLX·엔진별 의존성
```
</details>

<details>
<summary>문제 해결</summary>

- **첫 생성이 느림**: 모델을 내려받고(처음 한 번, 2.5–3GB) 메모리에 올리는 중입니다. 진행 막대는 실행 창에 나옵니다.
- **"모델이 문장을 끝맺지 못했습니다" 오류**: 참조 녹음의 대본이 실제 녹음과 다를 때(녹음이 문장 중간에서 끊긴 경우 포함) 가장 흔합니다. 목소리 등록 탭에서 대본을 읽은 그대로 고쳐 다시 등록하세요.
- **등록이 거절됨**: 녹음 검사 결과의 ❌ 항목(대본 맞춤·잡음·찢어짐·길이)을 고쳐 다시 녹음하세요.
- **모델 선택지가 안 보임**: 그 엔진이 설치되지 않았습니다. 고급 · 에이전트 연결 탭의 엔진 목록에서 이유를 확인하세요.
- **말투 버튼이 안 보임**: 그 말투에 녹음이 없습니다. 목소리 등록 탭에서 녹음하세요.
- **녹음 파일 변환 실패**: WAV로 저장해 올리거나 `.venv`에 PyAV를 설치하세요(`pip install av`).
- **특정 단어를 이상하게 읽음**: 만들기 탭의 "발음 고치기"에 "원문 → 소리"를 넣고 "읽을 문장 미리 보기"로 확인하세요.
- **메모리 부족**: 다른 큰 앱을 닫으세요. 생성 중 오류가 나면 모델을 내려놓고 다음 생성 때 다시 불러옵니다.
</details>

## 개인정보와 윤리

> [!IMPORTANT]
> **본인 목소리이거나, 본인의 명시적 동의를 받은 목소리만** 등록하세요. 화면은 동의 체크 없이 만들지 않습니다.

- 참조 녹음(`references/`), 결과(`outputs/`), 발음 사전(`lexicon.json`), 로컬 설정(`settings.json`)은 `.gitignore`로 막혀 있어 저장소에 올라가지 않습니다.
- 만든 음성을 공개할 때는 합성 음성임을 밝히기를 권합니다. Chatterbox PyTorch 판은 생성 음성에 워터마크를 넣습니다.

## 비슷한 프로젝트와 차이

| 프로젝트 | 겹치는 점 | 이 저장소의 차이 |
|---|---|---|
| [jamiepine/voicebox](https://github.com/jamiepine/voicebox) | 로컬 음성 복제, MLX, REST API, MCP | 한국어 우선. 말투별 참조 녹음과 녹음 검사, 영상용 일괄 생성(자막·마커·재사용 캐시), 모델·실행 방식 선택 |
| [Blaizzy/mlx-audio](https://github.com/Blaizzy/mlx-audio) | 맥 엔진 라이브러리 | 엔진 위에 화면·API·명령줄·MCP를 얹은 앱 |
| [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), [resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox) | 모델 원본 | 두 모델을 같은 작업 흐름(등록 → 생성 → 일괄)으로 묶음 |

## 라이선스

- 이 저장소의 코드: [MIT](LICENSE)
- 모델 가중치는 저장소에 들어 있지 않고 처음 쓸 때 Hugging Face에서 받습니다.
  - Qwen3-TTS([원본](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base), [MLX 8-bit](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit)): Apache-2.0
  - Chatterbox([원본](https://huggingface.co/ResembleAI/chatterbox), [MLX 다국어 v3](https://huggingface.co/mlx-community/chatterbox-multilingual-v3)): MIT
- 주요 의존성: mlx·mlx-audio(MIT), PyTorch(BSD-3), Gradio(Apache-2.0), FastAPI(MIT), PyAV(BSD-3), SciPy(BSD-3), MCP Python SDK(MIT)
- 홍보 영상: [/brag](https://github.com/latent-spaces/brag)(MIT)로 제작. 음악·효과음은 코드로 합성했습니다.

<details>
<summary>English</summary>

A local, Korean-first voice-cloning TTS for macOS (Apple Silicon, MLX) and Windows/Linux (PyTorch, CUDA or CPU). Record about 10 seconds per speaking style; recordings are checked before registration (script match, noise, clipping, reverb, bandwidth). Paste a script and get numbered WAVs per line, a joined narration WAV, SRT subtitles and editor markers, optionally loudness-normalized to −16 LUFS at 48 kHz. Pick a model (Qwen3-TTS or Chatterbox Multilingual); it runs on the fastest runtime available. Ships a web UI, an HTTP API, a batch CLI and an MCP server, so AI coding agents can produce narration in **your own** voice. Everything runs on 127.0.0.1.
</details>
