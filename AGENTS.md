# AGENTS.md: 코딩 에이전트용 안내

이 저장소는 **사용자 본인의 목소리**로 한국어 문장을 읽어 WAV를 만드는 로컬 TTS 서버입니다.
모델은 Qwen3-TTS(중국 Alibaba)와 Chatterbox Multilingual v3(미국 Resemble AI) 중에서 고르고, 실행 방식은 맥이면 MLX, 윈도우·리눅스면 PyTorch(CUDA, 없으면 CPU)가 자동으로 골라집니다([docs/ENGINES.md](docs/ENGINES.md)).
에이전트가 할 일은 대개 하나입니다. 대사(문장)를 받아 사용자 목소리 WAV로 만드는 것입니다. 영상 내레이션 대사를 한꺼번에 뽑는 경우가 많습니다.

## 먼저 확인할 것

1. 서버가 켜져 있는지 봅니다: `curl -s http://127.0.0.1:7860/api/health`
   - 켜져 있으면 HTTP·명령줄·MCP 모두 이 서버를 씁니다. 모델은 서버 프로세스 하나에만 올라갑니다.
   - 꺼져 있으면 사용자에게 `start.command`(또는 `.venv/bin/python app.py`)로 켜 달라고 하거나, 명령줄·MCP가 직접 모델을 올리게 둡니다. 16GB Mac이라면 **서버와 직접 실행을 동시에 돌리지 마세요**. 모델이 두 번 올라갑니다.
2. 쓸 수 있는 말투를 봅니다: `GET /api/styles`에서 `ready: true`인 것만 씁니다. 기본 말투는 `default`(기본), `talk`(대화), `guide`(안내), `joy`(기쁨)입니다.
3. 쓸 수 있는 엔진을 봅니다: `GET /api/engines`(또는 MCP `list_engines`, 명령줄 `engines`). 사용자가 모델을 정하지 않았다면 기본 엔진을 그대로 씁니다. 한 작업 안에서는 엔진을 섞지 마세요. 엔진을 바꾸면 목소리 느낌이 달라집니다.
4. 녹음이 없는 말투는 에이전트가 만들 수 없습니다. 사용자가 화면의 **목소리 등록** 탭에서 직접 녹음해야 합니다. 다른 사람의 목소리를 등록하게 돕지 마세요.

## 세 가지 연결 방법

| 방법 | 언제 | 진입점 |
|---|---|---|
| MCP | 에이전트가 도구로 바로 부를 때 | `mcp_server.py`: `list_styles`, `list_engines`, `speak`, `speak_batch`, `health` |
| 명령줄 | 셸·스크립트·빌드 파이프라인 | `voicelab_cli.py say|batch|styles|engines|register|health` (`-e`로 모델 지정) |
| HTTP | 다른 언어나 다른 프로젝트 | `POST /api/tts`, `POST /api/batch` (형식: `docs/API.md`) |

### MCP 등록

```bash
claude mcp add voicelab -- "<repo>/.venv/bin/python" "<repo>/mcp_server.py"
```

Cursor·Claude Desktop(`mcpServers`)이나 Codex(`~/.codex/config.toml`)의 설정 예시는 서버 화면의 **에이전트 · MCP** 탭에 실제 경로가 채워진 채로 나옵니다.

### 대사 일괄 생성(가장 흔한 작업)

```bash
.venv/bin/python voicelab_cli.py -q batch examples/lines.json -o /abs/out/voice -s guide
```

- 입력은 `["문장", …]`, `{"style": "...", "items": [{"id", "text", "style"}]}`, `.txt`(줄마다 한 문장), `.jsonl` 중 하나입니다.
- 결과는 `out/voice/<id>.wav`와 `out/voice/manifest.json`입니다. 표준 출력 JSON의 `items[].duration_sec`로 영상 타이밍을 잡으면 됩니다.
- 같은 문장·말투로 이미 만든 파일은 재사용합니다(`cached: true`). 다시 만들려면 `--force`를 붙입니다.
- 한 항목이 실패해도 나머지는 계속 만듭니다. 종료 코드 1과 `items[].error`를 확인하세요.
- 영상용이면 `--loudness -16 --sample-rate 48000 --timeline`을 붙입니다. 문장마다 음량이 고르고(-16 LUFS), 48kHz로 저장되며, 이어 붙인 `narration.wav`, 자막 `narration.srt`, 편집 마커 `narration_markers.csv`가 함께 나옵니다(항목마다 `start_sec`·`end_sec`). TXT의 빈 줄(JSON은 항목의 `paragraph` 번호)은 문단으로 보고 1초 쉽니다(`--paragraph-gap`).
- 화면 전환에 맞춰 빠르기를 바꿔야 하면 `--speed 0.8–1.25`(음높이는 그대로)를 씁니다.
- 대본 중간에 줄을 넣어 번호가 밀려도 바뀐 줄만 새로 만듭니다(`<out>/.voicelab-cache`). 지운 줄의 옛 파일까지 치우려면 `--prune`(지우지 않고 `_stale/`로 옮김).
- 결과마다 `seed`가 남습니다. 마음에 안 드는 줄은 그 항목에 다른 `seed`를 주어 다시 만듭니다. `warning`이 있는 항목은 사람이 들어 보게 알려 주세요.

## 품질 팁

- 대사는 문장 단위로 나눠 보내세요. 한 덩어리가 길면 앞뒤 문장에 끌려 발음이 무너질 수 있습니다. 2000자를 넘으면 거절됩니다.
- 잘못 읽는 단어는 `lexicon.json`(예: `{"배지": "뺏지"}`)이나 요청의 `replace`로 고칩니다. 문장 안에 `[뺏지]`처럼 소리를 직접 적어도 됩니다.
- 영문 약어는 소리 나는 대로 한글로 적으면 안정적입니다(`MLX` → `엠엘엑스`). 숫자는 Qwen3가 그대로 잘 읽고, Chatterbox에는 서버가 자동으로 한국어 소리로 바꿔 넘깁니다(`2026년` → `이천이십육년`). 연도를 `이공이육`처럼 다르게 읽히고 싶으면 직접 한글로 적으세요.
- 결과를 다시 만들어 고르고 싶으면 `seed`를 바꿔 봅니다.
- "모델이 문장을 끝맺지 못했습니다" 오류는 대개 참조 녹음의 대본이 녹음과 다를 때 납니다. 사용자에게 목소리 등록 탭에서 대본을 읽은 그대로 고쳐 다시 등록하라고 안내하세요(에이전트가 대신 녹음·등록하지 않습니다).

## 지켜야 할 것

- `references/`(참조 녹음), `outputs/`(결과), `lexicon.json`은 사용자 개인 자료입니다. 읽거나 옮기거나 커밋하지 마세요(`.gitignore`로 막혀 있음).
- 서버는 `127.0.0.1`에만 엽니다. `0.0.0.0` 바인딩이나 공유 링크를 켜지 마세요.
- 예전 Gradio 엔드포인트 `/synthesize`의 인자 이름·순서·기본값은 외부 도구가 의존합니다. 바꾸지 마세요(`docs/API.md` 맨 아래).
- 생성은 무겁습니다. 테스트할 때는 한 번에 하나씩, 짧은 문장으로 하세요. `selftest.py`는 기본적으로 생성 없이 점검합니다.

## 코드 지도

| 파일 | 역할 |
|---|---|
| `app.py` | 서버 실행, 화면(Gradio), 예전 `/synthesize` 호환 |
| `api.py` | HTTP API(FastAPI 라우터) |
| `service.py` | 생성·일괄 생성·발음 사전·참조 등록(화면·API·명령줄·MCP 공용) |
| `voices.py` | 말투 레지스트리(`references/voices.json`) |
| `engine.py` | 엔진 실행기. 엔진 하나만 메모리에, 생성 잠금(한 번에 하나) |
| `backends/` | 엔진 구현(모델 × 실행 방식)과 다른 가상환경용 작업 프로세스 |
| `audio_prep.py` | 녹음 변환(WAV 직접, 그 밖은 PyAV, 맥 afconvert 대체)과 등록용 저장 |
| `audio_fx.py` | 녹음 검사(대본 맞춤·잡음·찢어짐·길이·대역)·다듬기, 결과 음량(LUFS·리미터)·표본율·앞 무음 |
| `ending.py` | Qwen3 생성 감독: 생성 상한(폭주 막기)·덜 읽음 감지·말끝 보정(꼬리말 붙여 만들고 잘라 냄, 실패하면 seed 바꿔 다시) |
| `voicelab_cli.py`, `mcp_server.py` | 명령줄, MCP |
| `selftest.py` | 켜진 서버 점검(표준 라이브러리만) |
| `tools/` | `smoke_engine.py` 엔진 단독 점검, `benchmark.py`·`evaluate.py` 엔진 비교, `stress.py` 견딤 시험(참조 녹음 상태 × 문장 종류) |
