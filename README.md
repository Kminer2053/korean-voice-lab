# 내 목소리 생성기 (voice-lab)

**내 녹음 몇 개로, 내 목소리가 한국어 문장을 읽게 하는 로컬 TTS.** 맥과 윈도우에서 돕니다.
TTS 모델을 골라 쓸 수 있고, 모델마다 그 컴퓨터에서 가장 빠른 방식으로 실행합니다. 맥은 MLX, 윈도우·리눅스는 NVIDIA CUDA를 쓰고, GPU가 없으면 CPU로 돕니다. 녹음과 결과 음성은 이 컴퓨터 밖으로 나가지 않습니다.

> English: A local, Korean-first voice-cloning TTS for macOS (Apple Silicon, MLX) and Windows/Linux (PyTorch, CUDA or CPU). Pick a model (Qwen3-TTS or Chatterbox Multilingual) and it runs on the fastest runtime available. Ships a web UI, an HTTP API, a batch CLI and an MCP server, so AI coding agents can produce narration in **your own** voice. Everything runs on 127.0.0.1.

## 무엇을 하나요

- **화면 한 장으로 끝까지**: ① 내 목소리 → ② 문장 → ③ 말투·모델 → ④ 만들기 → ⑤ 듣고 WAV 받기.
- **모델을 골라 쓰기**: Qwen3-TTS(중국 Alibaba, Apache-2.0)와 Chatterbox Multilingual v3(미국 Resemble AI, MIT) 중에서 고릅니다. 개발 주체 국가와 라이선스는 화면과 [docs/ENGINES.md](docs/ENGINES.md)에 있습니다.
- **말투별 참조 녹음**: 기본·대화·안내·기쁨 네 가지이고 직접 추가할 수 있습니다. 한 번 녹음하면 모든 모델이 같이 씁니다.
- **대사 일괄 생성**: 문장 목록(JSON·TXT)을 넣으면 대사마다 WAV 하나와 `manifest.json`이 나옵니다. 이미 만든 대사는 다시 만들지 않습니다.
- **에이전트 연동**: MCP 서버(`speak`, `speak_batch`, `list_engines`), 명령줄(`voicelab_cli.py`), HTTP API(`/api/tts`, `/api/batch`)를 제공합니다.
- **발음 사전**: 잘못 읽는 단어를 소리 나는 대로 바꿉니다(`배지` → `뺏지`).
- **로컬 전용**: 서버는 `127.0.0.1`에만 열립니다. 인터넷은 처음 패키지와 모델을 내려받을 때만 씁니다.

## 엔진

| 모델 | 맥(Apple Silicon) | 윈도우·리눅스 | 개발 주체 | 라이선스 |
|---|---|---|---|---|
| Qwen3-TTS 0.6B | `qwen3-mlx` (기본) | `qwen3-torch` (선택 설치) | Alibaba(중국) | Apache-2.0 |
| Chatterbox Multilingual v3 | `chatterbox-mlx` | `chatterbox-torch` (기본) | Resemble AI(미국) | MIT |

API·명령줄·MCP에서 `engine`에 `qwen3` 또는 `chatterbox`만 적으면 실행 방식은 자동으로 골라집니다. 자세한 내용은 [docs/ENGINES.md](docs/ENGINES.md)에 있습니다.

맥(M5 16GB)에서 같은 목소리·같은 문장 20개로 비교한 결과입니다. 측정 방법은 [docs/ENGINES.md](docs/ENGINES.md#맥-비교-결과2026-11-17-m5-16gb)에 있습니다.

| 엔진 | 받아쓰기 오독률 | 화자 유사도 (같은 사람 녹음끼리 0.753) | 생성 시간 ÷ 음성 길이 |
|---|---|---|---|
| `qwen3-mlx` | 0.0% | 0.759 | 0.47 |
| `chatterbox-mlx` | 1.0% | 0.745 | 0.95 |

## 요구 사항

| | 맥 | 윈도우 |
|---|---|---|
| 컴퓨터 | Apple Silicon(M1 이상). 16GB에서 검증 | 64비트 Windows 10/11. NVIDIA GPU(VRAM 8GB 이상) 권장, 없으면 CPU(느림) |
| Python | 3.11–3.13 (`brew install python@3.12`) | 3.11–3.12 ([python.org](https://www.python.org/downloads/), py launcher 포함) |
| 디스크 | 약 6GB(가상환경과 모델 두 개) | 약 10GB(PyTorch와 모델) |

Intel Mac은 MLX를 지원하지 않습니다. 윈도우와 같은 PyTorch 방식(CPU)으로 쓸 수 있지만 검증하지 않았습니다.

## 설치와 실행

### 맥

1. 저장소를 내려받습니다(`git clone` 또는 ZIP).
2. **`setup.command`**를 더블클릭합니다. 이 폴더의 `.venv`에만 설치합니다.
3. **`start.command`**를 더블클릭하면 브라우저에 `http://127.0.0.1:7860`이 열립니다.

> 처음 열 때 "확인되지 않은 개발자" 경고가 뜨면 파일을 우클릭한 뒤 **열기**를 누르세요. 실행 권한이 없다는 오류가 나면 터미널에서 `chmod +x setup.command start.command`를 실행하세요.

터미널로 설치하려면 다음과 같이 합니다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt     # 검증된 고정 버전(서버 + MLX 엔진)
.venv/bin/python app.py --open
```

### 윈도우

1. 저장소를 내려받습니다.
2. **`setup.bat`**를 더블클릭합니다.
   - 서버용 `.venv`와 Chatterbox 엔진용 `.venv-chatterbox`를 만듭니다.
   - NVIDIA GPU가 있으면 CUDA 12.4 PyTorch를, 없으면 CPU PyTorch를 설치합니다.
   - Qwen3 엔진(`.venv-qwen3`)을 설치할지 묻습니다.
3. **`start.bat`**를 더블클릭하면 `http://127.0.0.1:7860`이 열립니다.

설치 과정은 GitHub Actions의 Windows 러너에서 자동으로 검증합니다([windows-smoke](.github/workflows/windows-smoke.yml)).

### 리눅스

윈도우와 같은 구성을 직접 만듭니다.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements/server.txt
python3.12 -m venv .venv-chatterbox
.venv-chatterbox/bin/pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124   # GPU 없으면 /whl/cpu
.venv-chatterbox/bin/pip install -r requirements/engine-chatterbox.txt
.venv/bin/python app.py
```

7860번을 다른 프로그램이 쓰고 있으면 다음 빈 포트를 쓰고 주소를 알려 줍니다(`--port`로 지정 가능).

## 처음 쓰는 순서

1. **목소리 등록** 탭에서 말투를 고르고, 화면의 문장을 5–15초 동안 읽어 녹음합니다. 마이크로 녹음하거나 아이폰 음성 메모(M4A)를 올립니다. 다르게 읽었다면 "실제로 읽은 문장"을 고쳐 적습니다.
2. **만들기** 탭에서 문장을 적고, 말투와 모델을 고르고, 동의에 체크한 뒤 **이 목소리로 만들기**를 누릅니다. 모델별 첫 생성은 내려받고 불러오느라 더 걸립니다.
3. 결과를 듣고 WAV로 받습니다. "줄마다 따로 만들기"를 켜면 여러 줄을 한 번에 만듭니다.

녹음 팁: 조용한 방에서 입과 한 뼘 정도 떨어져 읽으세요. 음악·울림·바람 소리는 피합니다. 말투마다 그 말투답게 읽은 녹음을 두면 결과도 그 말투를 따라갑니다.

## AI 에이전트·자동화에서 쓰기

자세한 안내는 [AGENTS.md](AGENTS.md), 요청·응답 형식은 [docs/API.md](docs/API.md)에 있습니다. 서버 화면의 **에이전트 · MCP** 탭에는 실제 경로가 채워진 설정 예시, 엔진 목록, 연결 확인 버튼이 있습니다.

```bash
# MCP (Claude Code 예시. Cursor·Codex 설정은 화면 탭 참고)
claude mcp add voicelab -- "$PWD/.venv/bin/python" "$PWD/mcp_server.py"

# 명령줄: 대사 목록 → WAV 여러 개 + manifest.json (모델 지정은 -e)
.venv/bin/python voicelab_cli.py batch examples/lines.json -o ~/Desktop/narration -s guide -e chatterbox

# HTTP
curl -s -X POST http://127.0.0.1:7860/api/tts -H 'Content-Type: application/json' \
  -d '{"text":"안녕하세요","style":"talk","engine":"qwen3"}' -o hello.wav
```

윈도우에서는 `.venv/bin/python` 대신 `.venv\Scripts\python`을 씁니다. 명령줄과 MCP는 서버가 켜져 있으면 서버로 보내고(모델을 한 번만 올림), 꺼져 있으면 직접 모델을 올립니다.

## 점검과 비교

```bash
python3 selftest.py                                   # 켜진 서버: 상태·말투·오류 응답·127.0.0.1 바인딩
python3 selftest.py --generate                        # 실제 생성까지
.venv/bin/python tools/smoke_engine.py -e chatterbox  # 엔진 하나 단독 생성(서버 없이)
.venv/bin/python tools/benchmark.py --styles talk,guide -o outputs/bench   # 엔진 비교 생성·속도
.venv-eval/bin/python tools/evaluate.py outputs/bench  # 받아쓰기 오독률·화자 유사도(설치법은 파일 머리말)
```

## 개인정보와 윤리

- **본인 목소리이거나, 본인의 명시적 동의를 받은 목소리만** 등록하세요. 화면은 동의 체크 없이 만들지 않습니다.
- 참조 녹음(`references/`), 결과(`outputs/`), 발음 사전(`lexicon.json`), 로컬 설정(`settings.json`)은 `.gitignore`로 막혀 있어 저장소에 올라가지 않습니다.
- 만든 음성을 공개할 때는 합성 음성임을 밝히기를 권합니다. Chatterbox PyTorch 판은 생성 음성에 워터마크를 넣습니다.

## 비슷한 프로젝트와 차이

| 프로젝트 | 겹치는 점 | 이 저장소의 차이 |
|---|---|---|
| [jamiepine/voicebox](https://github.com/jamiepine/voicebox) | 로컬 음성 복제, MLX, REST API, MCP | 한국어 우선. 말투별 참조 녹음, 대사 일괄 생성과 재사용 캐시, 모델·실행 방식 선택 |
| [Blaizzy/mlx-audio](https://github.com/Blaizzy/mlx-audio) | 맥 엔진 라이브러리 | 엔진 위에 화면·API·명령줄·MCP를 얹은 앱 |
| [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), [resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox) | 모델 원본 | 두 모델을 같은 작업 흐름(등록 → 생성 → 일괄)으로 묶음 |

## 구조

```
app.py              서버 실행 + 화면(Gradio) + 예전 /synthesize 호환
api.py              HTTP API (FastAPI)
service.py          생성·일괄·발음 사전·참조 등록 (공용 로직)
engine.py           엔진 실행기: 엔진 하나만 메모리에, 생성은 한 번에 하나
backends/           엔진 구현(qwen3_mlx, qwen3_torch, chatterbox_mlx, chatterbox_torch)과 작업 프로세스
voices.py           말투 레지스트리 (references/voices.json)
audio_prep.py       녹음 변환(WAV 직접, 그 밖은 PyAV, 맥은 afconvert 대체)·무음 검사
textnorm.py         숫자를 한국어 소리로(숫자를 잘못 읽는 엔진용, 채점에도 사용)
voicelab_cli.py     명령줄
mcp_server.py       MCP 서버(stdio)
selftest.py         서버 점검
tools/              엔진 단독 점검·비교 생성·채점
requirements/       서버·맥 MLX·엔진별 의존성
```

## 문제 해결

- **첫 생성이 느림**: 모델을 내려받고(처음 한 번, 2.5–3GB) 메모리에 올리는 중입니다. 진행 막대는 실행 창에 나옵니다.
- **모델 선택지가 안 보임**: 그 엔진이 이 컴퓨터에 설치되지 않았습니다. 에이전트·MCP 탭의 엔진 목록에서 이유를 확인하세요.
- **말투 버튼이 안 보임**: 그 말투에 녹음이 없습니다. 목소리 등록 탭에서 녹음하세요.
- **녹음 파일 변환 실패**: WAV로 저장해 올리거나 `.venv`에 PyAV를 설치하세요(`pip install av`).
- **특정 단어를 이상하게 읽음**: 목소리 등록 탭의 발음 사전에 "원문 → 소리"를 넣으세요.
- **메모리 부족**: 다른 큰 앱을 닫으세요. 생성 중 오류가 나면 모델을 내려놓고 다음 생성 때 다시 불러옵니다.

## 라이선스

- 이 저장소의 코드: [MIT](LICENSE)
- 모델 가중치는 저장소에 들어 있지 않고 처음 쓸 때 Hugging Face에서 받습니다.
  - Qwen3-TTS([원본](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base), [MLX 8-bit](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit)): Apache-2.0
  - Chatterbox([원본](https://huggingface.co/ResembleAI/chatterbox), [MLX 다국어 v3](https://huggingface.co/mlx-community/chatterbox-multilingual-v3)): MIT
- 주요 의존성: mlx·mlx-audio(MIT), PyTorch(BSD-3), Gradio(Apache-2.0), FastAPI(MIT), PyAV(BSD-3), MCP Python SDK(MIT)
