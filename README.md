# 내 목소리 생성기 (voice-lab)

**내 녹음 몇 개로, 내 목소리가 한국어 문장을 읽게 하는 로컬 TTS.** 맥과 윈도우에서 돕니다.
TTS 모델을 골라 쓸 수 있고, 모델마다 그 컴퓨터에서 가장 빠른 방식으로 실행합니다. 맥은 MLX, 윈도우·리눅스는 NVIDIA CUDA를 쓰고, GPU가 없으면 CPU로 돕니다. 녹음과 결과 음성은 이 컴퓨터 밖으로 나가지 않습니다.

> English: A local, Korean-first voice-cloning TTS for macOS (Apple Silicon, MLX) and Windows/Linux (PyTorch, CUDA or CPU). Pick a model (Qwen3-TTS or Chatterbox Multilingual) and it runs on the fastest runtime available. Ships a web UI, an HTTP API, a batch CLI and an MCP server, so AI coding agents can produce narration in **your own** voice. Everything runs on 127.0.0.1.

## 무엇을 하나요

- **화면 한 장으로 끝까지**: 말투 고르기 → 문장 적기 → 만들기 → 바로 듣고 WAV 받기. 결과마다 seed가 남아 마음에 든 결과를 다시 얻을 수 있습니다.
- **영상 내레이션 작업용**: 대본을 붙여 넣고 "줄마다·문장마다"를 고르면 `001_문장.wav` 순서대로 파일이 생기고, 이어 붙인 WAV·자막(SRT)·편집 마커(CSV)·zip을 한 번에 받습니다. 빈 줄로 나눈 문단 사이는 더 길게 쉽니다. 바뀐 줄만 다시 만들고, 마음에 안 드는 번호만 다른 버전으로 다시 만들며, 이전 프로젝트를 다시 불러올 수 있습니다. 선택하면 음량을 영상 기준(-16 LUFS)으로, 표본율을 48kHz로, 말 빠르기를 0.8–1.25배로(음높이는 그대로) 맞춥니다.
- **녹음 검사와 고음질 녹음**: 등록 전에 대본과 녹음이 맞는지, 잡음·찢어짐·길이·끝 잘림·좁은 대역(블루투스 마이크)·방 울림·전원 웅 소리·스테레오 채널을 검사해 이유를 알려 줍니다. 대본과 녹음이 어긋나면 모델이 문장을 끝맺지 못하는 일이 생기기 때문입니다. 화면의 **고음질로 녹음**은 브라우저의 잡음 제거·에코 제거·자동 음량을 끄고 압축 없이 녹음하고, 등록한 뒤 **시험 문장**으로 바로 확인합니다.
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

맥(M5 16GB)에서 같은 사람의 녹음 2개(대화·안내 말투) × 문장 10개로 비교한 결과입니다(2026-11-19, 말끝 보정·녹음 검사 반영 뒤). 측정 방법은 [docs/ENGINES.md](docs/ENGINES.md#맥-비교-결과)에 있습니다.

| 엔진 | 받아쓰기 오독률 | 화자 유사도 (같은 사람 녹음끼리 0.737) | 생성 시간 ÷ 음성 길이 | 모델 적재 | 최대 메모리 |
|---|---|---|---|---|---|
| `qwen3-mlx` | 0.0% | 0.750 | 0.67 | 2.3초 | 6.2GB |
| `chatterbox-mlx` | 0.7% | 0.801 | 0.96 | 1.3초 | 4.4GB |

## 요구 사항

| | 맥 | 윈도우 |
|---|---|---|
| 컴퓨터 | Apple Silicon(M1 이상). 16GB에서 검증 | 64비트 Windows 10/11. NVIDIA GPU(VRAM 8GB 이상) 권장, 없으면 CPU(느림) |
| Python | 3.11–3.13 (`brew install python@3.12`) | 3.11–3.12 ([python.org](https://www.python.org/downloads/), py launcher 포함) |
| 디스크 | 약 6GB(가상환경과 모델 두 개) | 약 10GB(PyTorch와 모델) |

Intel Mac은 MLX를 지원하지 않습니다. 윈도우와 같은 PyTorch 방식(CPU)으로 쓸 수 있지만 검증하지 않았습니다.

## 설치와 실행

### 맥

1. 저장소를 내려받습니다. `git clone https://github.com/Kminer2053/korean-voice-lab.git` 또는 GitHub의 **Code → Download ZIP**.
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
.venv-chatterbox/bin/pip install --no-deps -r requirements/engine-chatterbox-src.txt   # 다국어 v3 를 읽는 GitHub 판(git 불필요)
.venv/bin/python app.py
```

7860번을 다른 프로그램이 쓰고 있으면 다음 빈 포트를 쓰고 주소를 알려 줍니다(`--port`로 지정 가능).

## 처음 쓰는 순서

1. **목소리 등록** 탭에서 말투를 고르고, 화면의 문장을 5–15초 동안 읽어 녹음합니다. 아이폰 음성 메모(M4A)나 QuickTime으로 녹음해 올리는 것이 가장 좋고, 브라우저 마이크도 됩니다. 올리자마자 녹음 검사 결과가 나옵니다. 다르게 읽었다면 "실제로 읽은 문장"을 읽은 그대로 고쳐 적습니다.
2. **만들기** 탭에서 말투를 고르고 문장을 적은 뒤, 동의에 체크하고 **만들기**를 누릅니다. 동의는 브라우저가 기억합니다. 모델별 첫 생성은 내려받고 불러오느라 더 걸립니다.
3. 결과가 버튼 바로 아래에서 재생됩니다. 마음에 안 들면 **같은 문장 다른 버전**을 누릅니다. 대본 여러 줄은 "나누기"에서 줄마다·문장마다를 고르면 파일이 여러 개 생깁니다.

녹음 팁: 조용한 방에서 입과 한 뼘 정도 떨어져, 녹음을 켜고 0.5초 쉰 뒤 읽기 시작해 끝까지 읽고 0.5초 쉰 뒤 멈춥니다. 블루투스 이어폰 마이크는 피하고, 아이폰 음성 메모는 '녹음 향상'을 끕니다. 말투마다 그 말투답게 읽은 녹음을 두면 결과도 그 말투를 따라갑니다.

## AI 에이전트·자동화에서 쓰기

자세한 안내는 [AGENTS.md](AGENTS.md), 요청·응답 형식은 [docs/API.md](docs/API.md)에 있습니다. 서버 화면의 **고급 · 에이전트 연결** 탭에는 실제 경로가 채워진 설정 예시, 엔진 목록, 연결 확인 버튼이 있습니다.

```bash
# MCP (Claude Code 예시. Cursor·Codex 설정은 화면 탭 참고)
claude mcp add voicelab -- "$PWD/.venv/bin/python" "$PWD/mcp_server.py"

# 명령줄: 대사 목록 → WAV 여러 개 + manifest.json (모델 지정은 -e)
.venv/bin/python voicelab_cli.py batch examples/lines.json -o ~/Desktop/narration -s guide -e chatterbox
# 영상용: 음량 -16 LUFS, 48kHz, 이어 붙인 WAV·자막 SRT·마커 CSV까지(TXT의 빈 줄 = 문단, 1초 쉼)
.venv/bin/python voicelab_cli.py batch script.txt -o ~/Desktop/narration -s guide --loudness -16 --sample-rate 48000 --timeline
# 조금 빠르게(음높이는 그대로)
.venv/bin/python voicelab_cli.py say "화면 전환에 맞춰 조금 빠르게 읽습니다." -s guide --speed 1.1 -o fast.wav

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
.venv/bin/python tools/stress.py -e qwen3 --suite quick -o outputs/stress/q   # 견딤 시험(참조 녹음 상태 × 문장 종류)
```

`tools/stress.py`는 운영체제 내장 음성(맥 `say`, 윈도우 SAPI)으로 시험용 참조 녹음을 만들고, 짧게·길게·잡음·작은 소리·찢어짐·전화 음질·대본 불일치로 바꿔 가며 문장 12종을 만들어 봅니다. 항목마다 끝맺지 못함(폭주)·덜 읽음·무음·찢어짐·시간 초과·말끝 보정 실패를 판정합니다. 결과는 아래 [검증 결과](#검증-결과)에 있습니다.

## 검증 결과

`tools/stress.py`(견딤 시험), `selftest.py --generate`(서버 점검), 예전 `/synthesize` 호출로 확인했습니다(2026-11-19).

**환경별 속도와 결과** (생성 시간 ÷ 음성 길이, 1보다 작으면 실시간보다 빠름)

| 환경 | 엔진 | 속도 | 견딤 시험 | 서버 점검 |
|---|---|---|---|---|
| 맥 M5 16GB (MLX) | `qwen3-mlx` | 0.67 | 최종 코드로 204개 중 202개 성공. 오류 2개는 일부러 대본을 틀리게 준 참조(이유를 담은 오류로 끝남). 짧은 참조(0.9–5.7초)·작은 녹음·잡음·울림 참조 모두 성공 | 통과 |
| 맥 M5 16GB (MLX) | `chatterbox-mlx` | 0.96 | 192/192, 최종 코드 25/25 | 통과 |
| 맥 M5 (PyTorch CPU) | `qwen3-torch` | 중앙값 4.1 | 24/24 | |
| 윈도우 10, 4코어 CPU, GPU 없음 | `qwen3-torch` · `chatterbox-torch` | 약 19 · 중앙값 16.5 | Chatterbox 24/24. Qwen 정상 참조 12/12, 대본 불일치 참조는 오류로 끝남 | 통과 |
| GitHub Actions 윈도우 CPU | `chatterbox-torch` | 약 9.5 | | 통과(설치·녹음 검사·생성·일괄) |

- **찾아서 고친 것**
  - 참조 녹음의 대본이 실제 녹음과 어긋나면 Qwen3가 끝맺지 못하고 약 11분 분량까지 생성했습니다(맥에서 문장 하나에 9–14분, 메모리 14GB). 이제 문장 길이에 맞춘 상한에서 멈추고 다시 만들거나 이유를 담은 오류를 냅니다. 등록할 때는 녹음 검사가 같은 원인을 미리 막습니다.
  - 잡음 섞인 참조 녹음은 말끝 보정이 자주 실패해 문장마다 4번씩 다시 만들었습니다(12개 중 4개 실패). 쉼 기준을 결과의 잡음 바닥에 맞춰 실패 0개, 평균 시도 2.4 → 1.5회로 줄였습니다(꼬리말 소리 섞임 없음).
  - 영어 문장은 한국어 꼬리말(` 네.`)과 이어 읽히지 않아 말끝 보정이 늘 실패했습니다. 마지막 문장이 영어면 ` Yes.`를 붙입니다(받아쓰기로 꼬리말이 남지 않음을 확인).
  - 스테레오 녹음의 두 채널 위상이 반대면 평균을 내다 무음이 될 수 있었습니다. 이제 강한 채널 하나만 씁니다.
  - 그 밖에 덜 읽은 결과(무음에 가까움)가 성공으로 나가던 문제, 문장부호 없는 짧은 문장의 말끝 보정이 늘 실패하던 문제, 작은 녹음 결과에 잡음이 섞이던 문제, 서버를 다시 켜면 포트를 잘못 비켜 가던 문제를 고쳤습니다.
- **알아 둘 점**
  - GPU 없는 윈도우는 실시간보다 20배쯤 느립니다(3초 문장에 약 1분). NVIDIA GPU에서는 아직 확인하지 못했습니다.
  - Chatterbox는 대본을 쓰지 않아 대본 불일치의 영향을 받지 않습니다. 찢어진 참조 녹음은 두 엔진 모두 결과도 찢어지므로 등록 단계에서 거절합니다.

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
audio_prep.py       녹음 변환(WAV 직접, 그 밖은 PyAV, 맥은 afconvert 대체)
audio_fx.py         녹음 검사(대본 맞춤·잡음·찢어짐 등)·녹음 다듬기, 결과 음량(LUFS)·표본율·앞 무음
textnorm.py         숫자를 한국어 소리로(숫자를 잘못 읽는 엔진용, 채점에도 사용)
ending.py           Qwen3 생성 감독: 생성 상한(폭주 막기)·덜 읽음 감지·말끝 보정(꼬리말을 붙여 만들고 그 앞 쉼에서 자름)
voicelab_cli.py     명령줄
mcp_server.py       MCP 서버(stdio)
selftest.py         서버 점검
tools/              엔진 단독 점검·비교 생성·채점·견딤 시험(stress.py)
requirements/       서버·맥 MLX·엔진별 의존성
```

## 문제 해결

- **첫 생성이 느림**: 모델을 내려받고(처음 한 번, 2.5–3GB) 메모리에 올리는 중입니다. 진행 막대는 실행 창에 나옵니다.
- **모델 선택지가 안 보임**: 그 엔진이 이 컴퓨터에 설치되지 않았습니다. 고급 · 에이전트 연결 탭의 엔진 목록에서 이유를 확인하세요.
- **"모델이 문장을 끝맺지 못했습니다" 오류**: 참조 녹음의 대본이 실제 녹음과 다를 때(녹음이 문장 중간에서 끊긴 경우 포함) 가장 흔합니다. 목소리 등록 탭에서 대본을 읽은 그대로 고쳐 다시 등록하세요. 생성은 문장 길이에 맞춘 상한에서 멈추므로 오래 붙잡히지 않습니다.
- **등록이 거절됨**: 녹음 검사 결과의 ❌ 항목(대본 맞춤·잡음·찢어짐·길이)을 고쳐 다시 녹음하세요.
- **말투 버튼이 안 보임**: 그 말투에 녹음이 없습니다. 목소리 등록 탭에서 녹음하세요.
- **녹음 파일 변환 실패**: WAV로 저장해 올리거나 `.venv`에 PyAV를 설치하세요(`pip install av`).
- **특정 단어를 이상하게 읽음**: 만들기 탭의 "발음 고치기"에 "원문 → 소리"를 넣으세요. "읽을 문장 미리 보기"로 바뀐 문장을 먼저 확인할 수 있습니다.
- **메모리 부족**: 다른 큰 앱을 닫으세요. 생성 중 오류가 나면 모델을 내려놓고 다음 생성 때 다시 불러옵니다.

## 라이선스

- 이 저장소의 코드: [MIT](LICENSE)
- 모델 가중치는 저장소에 들어 있지 않고 처음 쓸 때 Hugging Face에서 받습니다.
  - Qwen3-TTS([원본](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base), [MLX 8-bit](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit)): Apache-2.0
  - Chatterbox([원본](https://huggingface.co/ResembleAI/chatterbox), [MLX 다국어 v3](https://huggingface.co/mlx-community/chatterbox-multilingual-v3)): MIT
- 주요 의존성: mlx·mlx-audio(MIT), PyTorch(BSD-3), Gradio(Apache-2.0), FastAPI(MIT), PyAV(BSD-3), MCP Python SDK(MIT)
