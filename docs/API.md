# HTTP API

서버는 `127.0.0.1:7860`(기본)에만 열립니다. 인증은 없습니다. 이 컴퓨터 밖에서는 접속할 수 없기 때문입니다.
자동 생성 문서는 서버의 `/docs`(Swagger)에서 볼 수 있습니다.

- 문자 인코딩은 UTF-8입니다. 결과는 16-bit PCM 모노 WAV, 24kHz입니다.
- `api_version`이 `"1"`인 동안에는 아래 필드를 없애거나 뜻을 바꾸지 않습니다. 필드는 더해질 수 있습니다.
- 생성은 한 번에 하나씩 순서대로 처리됩니다. 동시에 보내면 앞 요청이 끝날 때까지 기다립니다. 클라이언트 timeout은 넉넉히(일괄은 분 단위) 잡으세요.
- 첫 생성 때 모델을 불러오므로 수 초에서 수십 초가 더 걸립니다. 처음 실행이면 내려받는 시간도 더해집니다(약 3GB).

## 말투(style) 지정

`style`에는 아래 형식을 모두 쓸 수 있습니다.

| 쓰는 값 | 예 |
|---|---|
| id | `default`, `talk`, `guide`, `joy`, 직접 추가한 id |
| 화면 이름 | `기본`, `대화`, `안내`, `기쁨` |
| 이름(id) | `대화(talk)` |
| 예전 역할 이름 | `timbre`(=default), `question`(=talk) |

말투마다 참조 녹음이 등록되어 있어야 합니다(`ready: true`). 등록되지 않은 말투로 요청하면 400을 돌려줍니다.

## 모델(engine) 지정

`engine`에는 모델 계열(`qwen3`, `chatterbox`)이나 정확한 엔진 id(`qwen3-mlx`, `qwen3-torch`, `chatterbox-mlx`, `chatterbox-torch`)를 씁니다.
계열로 쓰면 이 컴퓨터에서 가장 빠른 실행 방식이 고르고(맥 MLX → PyTorch), 비우거나 `auto`면 기본 엔진을 씁니다. 목록과 이유는 `GET /api/engines`에서 봅니다. 자세한 내용은 [ENGINES.md](ENGINES.md)에 있습니다.
설치되지 않은 엔진을 요청하면 400과 함께 이유를 돌려줍니다.

## 오류 형식

```json
{"ok": false, "error": "사람이 읽을 수 있는 한국어 설명"}
```

입력 문제는 400, 모델·메모리 문제는 500입니다.

---

## `GET /api/health`

```json
{
  "ok": true,
  "api_version": "1",
  "service": "qwen3-voice-lab",
  "platform": "mac-arm64",
  "default_engine": "qwen3-mlx",
  "engines": [{"id": "qwen3-mlx", "family": "qwen3", "available": true}, {"id": "chatterbox-mlx", "family": "chatterbox", "available": true}],
  "loaded_engine": null,
  "model": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
  "model_loaded": false,
  "busy": false,
  "phase": "idle",
  "styles": [{"id": "default", "label": "기본", "ready": true}],
  "outputs_dir": "/…/outputs"
}
```

## `GET /api/styles`

```json
{"ok": true, "styles": [
  {"id": "talk", "label": "대화", "file": "2026….wav", "script": "녹음에서 읽은 문장",
   "prosody": "억양 안내", "description": "설명", "builtin": true, "ready": true, "duration_sec": 6.18}
]}
```

## `GET /api/engines`

```json
{"ok": true, "platform": "windows", "default_engine": "chatterbox-torch", "engines": [
  {"id": "chatterbox-torch", "family": "chatterbox", "runtime": "torch", "label": "Chatterbox 다국어 v3 · PyTorch",
   "model_id": "ResembleAI/chatterbox (t3 v3)", "developer": "Resemble AI", "origin": "미국", "license": "MIT",
   "commercial_use": true, "platforms": ["windows", "linux", "mac-arm64"], "needs_ref_text": false,
   "approx_download_gb": 3.2, "available": true, "reason": "사용 가능", "runs_in": "worker:C:\\…\\.venv-chatterbox\\Scripts\\python.exe"}
]}
```

`?refresh=true`면 설치 상태를 다시 확인합니다. `PUT /api/engines/default`에 `{"engine": "chatterbox"}`를 보내면 기본 엔진을 바꿉니다(`settings.json`에 저장).

## `POST /api/tts`: 문장 하나를 WAV 하나로

요청(JSON):

| 필드 | 형식 | 기본값 | 설명 |
|---|---|---|---|
| `text` | string | 필수 | 읽을 문장. 2000자 이하. 줄바꿈이 있으면 모델이 나눠 읽고 하나로 이어 붙입니다. |
| `style` | string | `default` | 말투. `style_id`, `voice`도 같은 뜻으로 받습니다. |
| `engine` | string | 기본 엔진 | 모델 계열 또는 엔진 id(위 참고) |
| `format` | `wav` \| `json` \| `base64` | `wav` | 응답 형식 |
| `seed` | int | 없음 | 같은 seed, 같은 입력이면 같은 결과를 기대할 수 있습니다. |
| `replace` | object | 없음 | 이 요청에만 쓰는 발음 치환 `{"배지": "뺏지"}` |
| `use_lexicon` | bool | `true` | `lexicon.json` 발음 사전을 적용할지 |
| `ref_text` | string | 없음 | 참조 녹음 대본을 이번에만 바꿀 때 |
| `output_path` | string | 없음 | 결과를 쓸 절대 경로(서버와 같은 컴퓨터). 없으면 `outputs/` |
| `speed` | number | 없음 | 받기만 하고 쓰지 않습니다. 모델이 아직 지원하지 않습니다. |

응답:

- `format: "wav"`: 본문이 WAV(`audio/wav`)입니다. 헤더는 `X-Duration-Sec`, `X-Sample-Rate`, `X-Style`, `X-Engine`, 그리고 퍼센트 인코딩된 `X-Output-Path`·`X-Output-File`입니다.
- `format: "json"`:

```json
{
  "ok": true, "id": null,
  "path": "/abs/path/대화_20261117T160815877112.wav", "file": "대화_20261117T160815877112.wav",
  "url": "/api/files/대화_20261117T160815877112.wav",
  "style": "talk", "style_label": "대화",
  "text": "원문", "spoken_text": "발음 사전(과 Chatterbox면 숫자 읽기) 적용 뒤 실제로 읽힌 문장",
  "duration_sec": 3.04, "sample_rate": 24000, "generate_sec": 1.6, "load_sec": 0.0,
  "model": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit", "engine": "qwen3-mlx", "device": "mlx-metal",
  "seed": null, "cached": false
}
```

- `format: "base64"`: 위 JSON에 `audio_base64`가 더해집니다.

`url`은 결과가 `outputs/` 안에 있을 때만 있습니다. 그 밖의 경로면 `null`입니다.

## `POST /tts`: 간단 호출용 별칭

`/api/tts`와 같습니다. JSON 대신 form이나 쿼리(`?text=…&style=talk`)도 받고, 기본 응답은 WAV 본문입니다.
`{"text": "...", "speed": 1.0}` 같은 일반적인 TTS HTTP 설정을 그대로 쓸 수 있습니다.

## `POST /api/batch`: 여러 문장을 WAV 여러 개로

요청(JSON):

| 필드 | 형식 | 기본값 | 설명 |
|---|---|---|---|
| `items` | array | 필수 | `["문장", …]` 또는 `[{"id", "text", "style", "engine", "seed", "replace"}, …]`. 섞어 써도 됩니다. |
| `style` | string | `default` | 항목에 `style`이 없을 때 쓸 말투 |
| `engine` | string | 기본 엔진 | 항목에 `engine`이 없을 때 쓸 모델·엔진 |
| `replace` | object | 없음 | 모든 항목에 쓰는 발음 치환 |
| `out_dir` | string | `outputs/batch-시각` | 결과 폴더(절대 경로, 서버와 같은 컴퓨터) |
| `skip_existing` | bool | `true` | 같은 문장·말투·참조 녹음·seed로 이미 만든 파일은 다시 만들지 않습니다. |
| `format` | `json` \| `zip` | `json` | `zip`이면 WAV와 manifest를 묶어 본문으로 돌려줍니다. |

파일 이름은 `id`가 있으면 `<id>.wav`(안전한 글자만 남김), 없으면 `001.wav`, `002.wav`처럼 순번입니다.
`out_dir/manifest.json`에 항목별 결과와 입력 해시(`sha`)를 남깁니다. 재사용 판단은 이 해시로 하고, 해시에는 엔진 id도 들어갑니다(엔진을 바꾸면 다시 만듦).

응답(`format: "json"`):

```json
{
  "ok": true, "count": 3, "succeeded": 3, "failed": 0,
  "out_dir": "/abs/narration", "manifest": "/abs/narration/manifest.json", "elapsed_sec": 3.9,
  "items": [
    {"ok": true, "id": "s01", "path": "/abs/narration/s01.wav", "duration_sec": 1.36, "style": "guide", "cached": false, "sha": "…", "…": "…"},
    {"ok": false, "id": "s02", "text": "…", "error": "이유"}
  ]
}
```

항목 하나가 실패해도 나머지는 계속 만듭니다. 전체 `ok`는 모두 성공했을 때만 `true`입니다.

## `POST /api/references`: 참조 녹음 등록(multipart)

필드는 `style`(id), `script`(녹음에서 실제로 읽은 문장), `file`(WAV·M4A·MP3·AIFF·CAF·FLAC)이고, 새 말투면 `label`·`description`도 받습니다.
녹음은 16-bit 모노 WAV로 바꿔 `references/`에 저장합니다. 무음에 가까우면 400을 돌려줍니다.

```bash
curl -s -X POST http://127.0.0.1:7860/api/references \
  -F style=news -F label=뉴스 -F script="오늘의 주요 소식을 전해 드립니다." -F file=@news.m4a
```

## `GET /api/references/{style}/audio`, `GET /api/files/{name}`

등록된 참조 녹음 또는 `outputs/` 안의 결과 WAV를 내려받습니다.

## `GET /api/lexicon`, `PUT /api/lexicon`

발음 사전 `{"원문": "읽을 소리"}`를 읽고 통째로 바꿉니다. 문장 안에 `[뺏지]`처럼 대괄호로 소리를 직접 적으면 대괄호만 벗겨 읽습니다(`[/]`는 그대로 둡니다).

---

## 예전 Gradio 호출 `/synthesize` (호환용)

예전 화면을 `gradio_client`로 부르던 도구가 그대로 동작하도록 이름·순서·기본값이 같은 엔드포인트를 둡니다.

```python
from gradio_client import Client
client = Client("http://127.0.0.1:7860/")
audio_path, info, file_path, status = client.predict(
    consent=True, style_id="talk", gen_text="읽을 문장",
    edit_timbre="", edit_question="", edit_guide="", edit_joy="",
    api_name="/synthesize",
)
```

| 인자 | 기본값 | 뜻 |
|---|---|---|
| `consent` | `False` | `True`여야 만듭니다. |
| `style_id` | `default` | `default`/`talk`/`guide`/`joy` |
| `gen_text` | 필수 | 읽을 문장. 발음 사전을 적용하지 않고 그대로 읽습니다. 엔진은 기본 엔진입니다. |
| `differed_<역할>`, `edit_<역할>` | `False`, 필수 | 역할은 `timbre`(=default), `question`(=talk), `guide`, `joy`. `differed`가 `True`이면 그 역할의 참조 대본을 `edit` 값으로 바꿉니다. |

반환은 `(결과 WAV 경로, 정보 문자열, 결과 WAV 경로, 상태 문자열)`입니다. 새 코드에서는 `/api/tts`를 쓰세요.
