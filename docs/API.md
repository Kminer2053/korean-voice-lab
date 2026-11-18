# HTTP API

서버는 `127.0.0.1:7860`(기본)에만 열립니다. 인증은 없습니다. 이 컴퓨터 밖에서는 접속할 수 없기 때문입니다.
자동 생성 문서는 서버의 `/docs`(Swagger)에서 볼 수 있습니다.

- 문자 인코딩은 UTF-8입니다. 결과는 16-bit PCM 모노 WAV, 24kHz입니다.
- 결과 앞 무음이 0.15초보다 길면 0.1초로 줄입니다(문장 클립을 이어 붙일 때 간격이 고르게). 결과가 1.0을 넘으면 잘라 내지 않고 전체를 조금 줄입니다.
- 서버 환경변수 `VOICELAB_TARGET_LUFS`(예: `-16`)·`VOICELAB_SAMPLE_RATE`(예: `48000`)로 모든 결과의 음량·표본율 기본값을 정할 수 있습니다(기본은 끔).
- 결과 끝에는 최소 0.3초 무음을 남깁니다. 서버 환경변수 `VOICELAB_TAIL_SILENCE`(초, 0이면 끔)로 바꿉니다. `duration_sec`에는 이 무음이 포함됩니다.
- Qwen3 엔진은 말끝을 온전히 읽히려고 문장 뒤에 꼬리말을 붙여 만든 뒤 잘라 냅니다(`docs/ENGINES.md`). 깨끗이 못 자르면 seed를 바꿔 다시 만들므로 그 문장은 시간이 더 걸립니다. 같은 `seed`면 결과는 같습니다. `VOICELAB_QWEN_CODA=0`이면 끕니다.
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
| `loudness` | number | 없음 | 통합 음량(LUFS, ITU-R BS.1770)으로 맞춥니다. 영상은 보통 `-16`, 유튜브 `-14`. 트루 피크는 -1 dBTP 아래로 둡니다. 없으면 모델 출력 그대로 |
| `sample_rate` | number | 없음 | 저장 표본율(16000·22050·24000·44100·48000). 영상 편집은 `48000`. 없으면 모델 그대로(24000) |

`seed`를 주지 않으면 서버가 무작위로 정하고 응답의 `seed`에 남깁니다. 같은 `seed`로 다시 부르면 같은 결과가 나옵니다(마음에 든 결과를 다시 얻을 때).

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
  "seed": 1834527711, "cached": false,
  "quality": {"ending": {"tries": 1, "coda": true, "runaways": 0}, "audio": {"lufs": -21.3, "peak_dbfs": -4.2}},
  "warning": ""
}
```

- `quality.ending`(Qwen3만): 말끝 보정 시도 수, 꼬리말 보정 성공 여부, 길이가 맞지 않아 다시 만든 횟수.
- `quality.audio`: 결과의 통합 음량·피크. `loudness`를 주면 `gain_db`·`true_peak_dbtp`도 들어갑니다.
- `warning`: 사람이 들어 볼 만한 결과면 이유(예: 말끝 보정 실패로 끝이 짧을 수 있음). 비어 있으면 문제없음.
- Qwen3가 끝내 문장을 끝맺지 못하거나(대본·녹음 불일치가 흔한 원인) 덜 읽으면 긴 엉터리 소리 대신 500 오류와 이유를 돌려줍니다.

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
| `loudness` | number | 없음 | 모든 문장을 같은 통합 음량(LUFS)으로. 예: `-16` |
| `sample_rate` | number | 없음 | 저장 표본율. 예: `48000` |
| `timeline` | bool | `false` | 순서대로 이어 붙인 `narration.wav`와 자막 `narration.srt`도 만들고, 항목마다 `start_sec`·`end_sec`를 넣습니다. |
| `gap_sec` | number | `0.4` | `timeline`의 문장 사이 쉼(초) |
| `prune` | bool | `false` | 이번 목록에 없는 예전 결과 파일을 `_stale/`로 옮기고 manifest에서 뺍니다(지우지 않음). |

파일 이름은 `id`가 있으면 `<id>.wav`(안전한 글자만 남김), 없으면 `001.wav`, `002.wav`처럼 순번입니다.
`out_dir/manifest.json`에 항목별 결과와 입력 해시(`sha`), 이번 순서(`order`)를 남깁니다. 재사용 판단은 이 해시로 하고, 해시에는 엔진 id와 지정한 `loudness`·`sample_rate`도 들어갑니다(바꾸면 다시 만듦).
만든 결과는 `out_dir/.voicelab-cache/<sha>.wav`에도 둡니다. 그래서 대본 중간에 줄을 넣어 번호가 밀려도 바뀐 줄만 새로 만들고, 항목에 다른 `seed`를 주어 다시 만들어도 이전 버전이 그 폴더에 남습니다.
일괄 생성 중에는 `GET /api/health`의 `batch`에 `{"done", "total", "id"}`가 나옵니다(명령줄은 이것으로 진행을 보여 줍니다).

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

등록 전에 녹음을 검사합니다(다듬기 전 원본 기준). 실패 항목이 있으면 등록하지 않고 400과 항목별 이유를 돌려줍니다.

| 검사 | 실패(등록 안 함) | 경고 |
|---|---|---|
| 길이(말소리 구간) | 3초 미만, 30초 초과 | 5–15초 밖 |
| 대본 맞춤(대본 음절 ÷ 말소리 초) | 초당 1.5음절 미만·10음절 초과(대본과 녹음이 다름, 녹음이 중간에 끊김) | 4–8.5 밖 |
| 대본 | 비었거나 5음절 미만 | |
| 찢어짐(클리핑) | 표본 0.1% 초과 또는 평평한 꼭대기가 초당 0.5번 초과 | 조금이라도 있으면 |
| 잡음(말소리와 잡음 바닥 차이) | 15dB 미만 | 25dB 미만 |
| 음질 | 표본율 16kHz 미만 | 4–8kHz 대역이 거의 없음(블루투스·전화) |
| 끝 잘림·첫소리 잘림 | | 말소리가 파일 끝·처음에 붙어 있음 |

통과하면 직류 성분 제거, 70Hz 아래 웅웅거림 줄이기, 앞뒤 무음을 0.2/0.3초로 정리, 말소리 크기를 -20dBFS 근처로 맞춘 뒤 16-bit 모노 WAV로 `references/`에 저장합니다.
응답의 `qc`에 측정값(`metrics`)과 항목별 판정(`checks`)이 들어갑니다. 이 기록은 말투 정보(`GET /api/styles`)에도 남습니다.

### `POST /api/references/check`

같은 검사를 등록 없이 합니다(multipart `file`, 선택 `script`). `{"ok": 통과 여부, "qc": {...}}`를 돌려줍니다.

```bash
curl -s -X POST http://127.0.0.1:7860/api/references \
  -F style=news -F label=뉴스 -F script="오늘의 주요 소식을 전해 드립니다." -F file=@news.m4a
```

## `GET /api/references/{style}/audio`, `GET /api/files/{name}`

등록된 참조 녹음 또는 `outputs/` 안의 결과 WAV를 내려받습니다.

## `GET /api/lexicon`, `PUT /api/lexicon`

발음 사전 `{"원문": "읽을 소리"}`를 읽고 통째로 바꿉니다. 영문·숫자로 시작하거나 끝나는 원문은 단어 단위로만 바꿉니다(`AI`를 넣어도 `OpenAI`는 그대로).
문장 안에 `[뺏지]`처럼 대괄호로 소리를 직접 적으면 대괄호만 벗겨 읽습니다(`[/]`는 그대로 둡니다).

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
