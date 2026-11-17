# 내 목소리 생성기 (qwen3-voice-lab)

**내 녹음 몇 개로, 내 목소리가 한국어 문장을 읽게 하는 로컬 TTS.**
Apple Silicon Mac에서 [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) 0.6B Base(8-bit, MLX)로 돌아갑니다. 녹음과 결과 음성은 이 컴퓨터 밖으로 나가지 않습니다.

> English: A local, Korean-first voice-cloning TTS for Apple Silicon Macs (Qwen3-TTS 0.6B Base 8-bit via mlx-audio). It ships a web UI, an HTTP API, a batch CLI and an MCP server, so AI coding agents can produce video narration in **your own** voice. Everything runs on 127.0.0.1.

## 무엇을 하나요

- **화면 한 장으로 끝까지**: ① 내 목소리 → ② 문장 → ③ 말투 → ④ 만들기 → ⑤ 듣고 WAV 받기.
- **말투별 참조 녹음**: 기본·대화·안내·기쁨 네 가지(직접 추가 가능). 생성할 때는 고른 말투의 녹음 하나만 씁니다.
- **대사 일괄 생성**: 문장 목록(JSON·TXT)을 넣으면 대사마다 WAV 하나와 `manifest.json`이 나옵니다. 이미 만든 대사는 재사용하므로 영상 파이프라인에서 반복 실행해도 됩니다.
- **에이전트 연동**: MCP 서버(`speak`, `speak_batch`), 명령줄(`voicelab_cli.py`), HTTP API(`/api/tts`, `/api/batch`)를 제공합니다.
- **발음 사전**: 잘못 읽는 단어를 소리 나는 대로 바꿉니다(`배지` → `뺏지`).
- **로컬 전용**: 서버는 `127.0.0.1`에만 열립니다. 인터넷은 처음 모델을 내려받을 때만 씁니다(약 3GB).

## 요구 사항

| 항목 | 내용 |
|---|---|
| 컴퓨터 | Apple Silicon Mac(M1 이상). 16GB 통합 메모리에서 검증했습니다. 8GB에서도 0.6B는 돌지만 여유가 적습니다. |
| OS | macOS 14 이상 권장(녹음 변환에 기본 내장된 `afconvert` 사용) |
| Python | 3.11–3.13 (예: `brew install python@3.12`) |
| 디스크 | 약 5GB(가상환경 약 0.8GB와 모델 약 3GB) |

## 설치와 실행 (macOS)

### 더블클릭으로

1. 이 저장소를 내려받습니다(`git clone` 또는 ZIP).
2. Finder에서 **`setup.command`**를 더블클릭합니다. 이 폴더 안 `.venv`에만 패키지를 설치하고, 전역 설치는 하지 않습니다.
3. **`start.command`**를 더블클릭하면 브라우저에 `http://127.0.0.1:7860`이 열립니다.

> 처음 열 때 "확인되지 않은 개발자" 경고가 뜨면 파일을 우클릭한 뒤 **열기**를 누르세요. 실행 권한이 없다는 오류가 나면 터미널에서 `chmod +x setup.command start.command`를 실행하세요.

### 터미널로

```bash
git clone <this-repo> qwen3-voice-lab && cd qwen3-voice-lab
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py --open          # http://127.0.0.1:7860
```

7860번을 다른 프로그램이 쓰고 있으면 다음 빈 포트를 쓰고, 주소를 터미널에 알려 줍니다(`--port`로 직접 지정 가능).

## 처음 쓰는 순서

1. **목소리 등록** 탭에서 말투를 고르고, 화면의 문장을 5–15초 동안 읽어 녹음합니다(마이크 또는 아이폰 음성 메모 M4A 업로드). 다르게 읽었다면 "실제로 읽은 문장"을 고쳐 적습니다.
2. **만들기** 탭에서 문장을 적고, 말투를 고르고, 동의에 체크한 뒤 **이 목소리로 만들기**를 누릅니다. 첫 생성은 모델을 불러오느라 더 걸립니다.
3. 결과를 듣고 WAV로 받습니다. "줄마다 따로 만들기"를 켜면 여러 줄을 한 번에 만듭니다.

녹음 팁: 조용한 방, 입에서 한 뼘, 음악·울림·바람 소리 없이. 말투마다 그 말투답게 읽은 녹음을 두면 결과도 그 말투를 따라갑니다.

## AI 에이전트·자동화에서 쓰기

자세한 안내는 [AGENTS.md](AGENTS.md), 요청·응답 형식은 [docs/API.md](docs/API.md)에 있습니다. 서버 화면의 **에이전트 · MCP** 탭에는 실제 경로가 채워진 설정 예시와 연결 확인 버튼이 있습니다.

```bash
# MCP (Claude Code 예시. Cursor·Codex 설정은 화면 탭 참고)
claude mcp add voicelab -- "$PWD/.venv/bin/python" "$PWD/mcp_server.py"

# 명령줄: 대사 목록 → WAV 여러 개 + manifest.json
.venv/bin/python voicelab_cli.py batch examples/lines.json -o ~/Desktop/narration -s guide

# HTTP
curl -s -X POST http://127.0.0.1:7860/api/tts -H 'Content-Type: application/json' \
  -d '{"text":"안녕하세요","style":"talk"}' -o hello.wav
```

명령줄과 MCP는 서버가 켜져 있으면 서버로 보내고(모델을 한 번만 올림), 꺼져 있으면 직접 모델을 올립니다.

## 점검

```bash
python3 selftest.py             # 생성 없이: 상태·말투·오류 응답·127.0.0.1 바인딩
python3 selftest.py --generate  # 문장 하나와 일괄 2개를 실제로 생성
```

## 다른 OS

지금은 **Apple Silicon macOS 전용**입니다. MLX가 Apple Silicon에서만 돌고, 녹음 변환에 macOS `afconvert`를 쓰기 때문입니다.

- **Windows·Linux(NVIDIA GPU)**: 원본 [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)(PyTorch)를 쓰세요. 이 저장소에서 MLX에 묶인 곳은 `engine.py`의 모델 적재·합성 부분과 `audio_prep.py`의 변환 부분뿐이어서, 이 두 곳을 바꾸면 화면·API·명령줄·MCP는 그대로 쓸 수 있습니다(기여 환영).
- **Intel Mac**: MLX를 지원하지 않습니다.

## 개인정보와 윤리

- **본인 목소리이거나 본인의 명시적 동의를 받은 목소리만** 등록하세요. 화면은 동의 체크 없이 만들지 않습니다.
- 참조 녹음(`references/`), 결과(`outputs/`), 발음 사전(`lexicon.json`)은 `.gitignore`로 막혀 있어 저장소에 올라가지 않습니다.
- 만든 음성을 공개할 때는 합성 음성이라는 사실을 밝히기를 권합니다.

## 비슷한 프로젝트와 차이

| 프로젝트 | 겹치는 점 | 이 저장소의 차이 |
|---|---|---|
| [jamiepine/voicebox](https://github.com/jamiepine/voicebox) | 로컬 음성 복제, MLX, REST API, MCP | 한국어 우선. 말투별 참조 녹음, 대사 일괄 생성과 재사용 캐시, 가벼운 0.6B 8-bit 단일 모델 |
| [Blaizzy/mlx-audio](https://github.com/Blaizzy/mlx-audio) | 같은 엔진 라이브러리 | 엔진 위에 화면·API·명령줄·MCP를 얹은 앱 |
| [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | 같은 모델의 원본 | Mac 로컬 실행과 작업 흐름(등록 → 생성 → 일괄) |
| GPT-SoVITS, CosyVoice, F5-TTS, OpenVoice | 음성 복제 엔진 | 주로 CUDA·PyTorch 기반 엔진·데모. 에이전트 연동과 Mac 전용 흐름은 없음 |

## 구조

```
app.py            서버 실행 + 화면(Gradio) + 예전 /synthesize 호환
api.py            HTTP API (FastAPI)
service.py        생성·일괄·발음 사전·참조 등록 (공용 로직)
voices.py         말투 레지스트리 (references/voices.json)
engine.py         MLX 모델 적재·합성 (한 번에 하나씩)
audio_prep.py     녹음 변환(afconvert)·무음 검사
records.py        생성 기록(outputs/results.csv·json)
system_probe.py   디스크·메모리 확인
voicelab_cli.py   명령줄
mcp_server.py     MCP 서버(stdio)
selftest.py       서버 점검
```

## 문제 해결

- **첫 생성이 느림**: 모델을 내려받고(처음 한 번, 약 3GB) 메모리에 올리는 중입니다. 진행 막대는 `start.command` 창에 나옵니다.
- **말투 버튼이 안 보임**: 그 말투에 녹음이 없습니다. 목소리 등록 탭에서 녹음하세요.
- **M4A 변환 실패**: 확장자가 `.m4a`·`.wav`·`.mp3`인지, 터미널의 `afconvert` 오류 문구를 확인하세요.
- **특정 단어를 이상하게 읽음**: 목소리 등록 탭의 발음 사전에 "원문 → 소리"를 넣으세요.
- **메모리 부족**: 다른 큰 앱을 닫으세요. 생성 중 오류가 나면 모델을 내려놓고 다음 생성 때 다시 불러옵니다.

## 라이선스

- 이 저장소의 코드: [MIT](LICENSE)
- 모델 [Qwen3-TTS-12Hz-0.6B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base)와 MLX 8-bit 변환본 [mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit): Apache-2.0. 모델 가중치는 이 저장소에 들어 있지 않고 처음 실행할 때 Hugging Face에서 받습니다.
- 주요 의존성: mlx·mlx-audio(MIT), Gradio·FastAPI(Apache-2.0·MIT), MCP Python SDK(MIT)
