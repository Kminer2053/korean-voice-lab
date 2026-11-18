# 엔진(모델 × 실행 방식)

이 프로그램은 TTS 모델을 갈아 끼울 수 있습니다. **모델**마다 컴퓨터에 맞는 **가장 빠른 실행 방식**을 고릅니다.

| 엔진 id | 모델 | 실행 방식 | 돌아가는 곳 | 개발 주체(국가) | 가중치 라이선스 | 참조 대본 |
|---|---|---|---|---|---|---|
| `qwen3-mlx` | Qwen3-TTS 0.6B Base 8-bit | MLX | Apple Silicon Mac | Alibaba Qwen 팀(중국) | Apache-2.0 | 필요 |
| `qwen3-torch` | Qwen3-TTS 0.6B Base | PyTorch | Windows·Linux (CUDA, 없으면 CPU) | Alibaba Qwen 팀(중국) | Apache-2.0 | 필요 |
| `chatterbox-mlx` | Chatterbox Multilingual v3 | MLX | Apple Silicon Mac | Resemble AI(미국) | MIT | 불필요 |
| `chatterbox-torch` | Chatterbox Multilingual v3 | PyTorch | Windows·Linux (CUDA, 없으면 CPU), 맥 MPS | Resemble AI(미국) | MIT | 불필요 |

- **모델만 고르면 됩니다.** `engine: "chatterbox"`처럼 모델 계열로 요청하면 맥에서는 MLX, 윈도우·리눅스에서는 PyTorch(CUDA → CPU)가 자동으로 쓰입니다. 정확한 id(`chatterbox-torch`)로 실행 방식을 직접 고를 수도 있습니다.
- **기본 엔진**: 환경변수 `VOICELAB_ENGINE` → `settings.json`의 `default_engine`(화면·`PUT /api/engines/default`로 바꿈) → 쓸 수 있는 첫 엔진 순서입니다(`qwen3-mlx` → `chatterbox-mlx` → `chatterbox-torch` → `qwen3-torch`). 맥은 기존 결과와 같은 목소리를 위해 Qwen3-MLX가 기본이고, 윈도우는 Chatterbox가 기본입니다.
- **메모리**: 한 번에 엔진 하나만 메모리에 둡니다. 다른 엔진을 부르면 앞 엔진을 내리고 올립니다.
- **참조 녹음은 공통입니다.** 말투마다 등록한 녹음 하나를 모든 엔진이 씁니다. Qwen3 계열은 그 녹음에서 읽은 문장(대본)도 함께 씁니다.

## 왜 가상환경을 나누나

PyTorch 엔진 패키지들은 서로 다른 버전을 고정합니다.

| 패키지 | 고정 버전 |
|---|---|
| `chatterbox-tts==0.1.7` | `torch==2.6.0`, `transformers==5.2.0`, `gradio==6.8.0`, `numpy<2`(Python 3.13 미만) |
| `qwen-tts==0.1.1` | `transformers==4.57.3` |

그래서 서버(`.venv`)와 엔진(`.venv-chatterbox`, `.venv-qwen3`)을 나누고, 서버가 엔진 가상환경의 파이썬을 **작업 프로세스**로 띄워 씁니다(`backends/worker.py`). 엔진을 내리면 작업 프로세스가 끝나 메모리도 깨끗이 돌아옵니다.
맥의 MLX 엔진 두 개는 서버와 같은 `.venv`에서 그대로 돕니다.

찾는 순서: `settings.json`의 `engine_python.<엔진 id>` → `.venv-<모델 계열>` → `.venv-torch`.

**Chatterbox 설치가 두 단계인 이유**: PyPI의 `chatterbox-tts` 0.1.7은 다국어 v2 가중치만 읽습니다. v3를 고르는 코드는 GitHub에만 있고, 그 코드는 의존성 하나(`resemble-perth`)를 git으로 받게 되어 있습니다. git이 없는 윈도우에서도 설치되도록 의존성은 `requirements/engine-chatterbox.txt`(PyPI 판)로 먼저 깔고, 본체는 고정한 GitHub 커밋의 ZIP을 `--no-deps`로 깝니다(`requirements/engine-chatterbox-src.txt`). PyPI 0.1.7이 깔려 있으면 v2로 돌고 장치 이름에 `(v2)`가 붙습니다.

## 공공 도입 검토 메모

- **Chatterbox Multilingual v3**: 미국 Resemble AI가 학습한 0.5B 모델이고, 코드와 가중치 모두 MIT입니다. 한국어는 공식 지원 23개 언어에 들어 있습니다.
  - 음성 생성부(S3Gen)는 README 감사 문구에 Alibaba CosyVoice와 S3Tokenizer가 적혀 있어, 그 아키텍처를 바탕으로 한 것으로 보입니다. 가중치는 Resemble이 직접 학습했습니다. 공공기관에 설명할 때 함께 적어 두기를 권합니다.
  - PyTorch 판(`chatterbox-tts`)은 생성 음성에 Perth 워터마크를 넣습니다. 합성 음성 표시가 필요한 공공 용도에는 오히려 장점입니다. MLX 변환판은 워터마크를 넣지 않습니다.
- **Qwen3-TTS**: 중국 Alibaba가 개발했고 Apache-2.0입니다. 라이선스상 상업·공공 이용이 가능하지만 개발 주체 국가를 따지는 기관이 있습니다. 맥에서 가장 빠르게 검증된 엔진이라 선택지로 남겨 둡니다.
- **함께 검토했지만 넣지 않은 것**(2026-11 기준)

  | 모델 | 넣지 않은 이유 |
  |---|---|
  | XTTS-v2 | CPML, 비상업 전용 |
  | OuteTTS 1B | CC-BY-NC-SA |
  | Voxtral TTS | CC-BY-NC, 한국어 없음 |
  | Supertonic(한국 Supertone) | 로컬 버전에 목소리 복제 없음 |
  | Higgs Audio | 비상업 |
  | VibeVoice, Dia, Sesame CSM, Kyutai | 한국어 없음 |
  | ZONOS3-Mini(미국 Zyphra, Apache-2.0, 한국어 지원) | 2026-11-14 공개라 pip 패키지가 없고 Windows는 직접 빌드해야 함. 다음 후보 |

## 검증 현황

| 엔진 | 상태 |
|---|---|
| `qwen3-mlx` | 맥(M5, 16GB)에서 화면·API·명령줄·MCP·예전 `/synthesize` 호출까지 실제 생성 확인 |
| `chatterbox-mlx` | 맥(M5, 16GB)에서 한국어 생성·비교 확인(아래 표). 첫 실행 때 가중치 약 2.7GB를 받습니다 |
| `chatterbox-torch` | 맥(M5, PyTorch MPS)에서 작업 프로세스로 v3 생성 확인. 다만 MPS로는 실시간보다 20배 이상 느려 맥에서는 MLX를 쓰세요. Windows(GitHub Actions `windows-smoke`, CPU)에서 `setup.bat` 설치 → v3 생성(4.2초 음성에 56초) → 서버·HTTP API·일괄 생성 자체 점검까지 통과(2026-11-18). GPU 없는 윈도우는 느리므로 NVIDIA GPU를 권합니다 |
| `qwen3-torch` | 맥 PyTorch CPU(`VOICELAB_TORCH_DEVICE=cpu`) 견딤 시험 24/24, RTF 중앙값 4.1. 윈도우 10(4코어 CPU, GPU 없음)에서 실제 생성·말끝 보정·서버 점검 통과(3초 문장에 약 1분). NVIDIA GPU 환경은 아직 검증하지 못함 |

### 맥 비교 결과

같은 사람의 참조 녹음 2개(대화·안내 말투) × 한국어 문장 10개(인사·안내·질문·감탄·외래어·숫자·긴 문장), seed 1. M5 16GB.

| 측정일 | 엔진 | 받아쓰기 오독률(CER) | 화자 유사도(SIM) | 속도(RTF) | 모델 적재 |
|---|---|---|---|---|---|
| 2026-11-19 (말끝 보정·녹음 검사 반영) | `qwen3-mlx` | 0.0% | 0.750 | 0.67 | 2.3초 |
| 2026-11-19 | `chatterbox-mlx` | 0.7% | 0.801 | 0.96 | 1.3초 |
| 2026-11-17 (말끝 보정 전) | `qwen3-mlx` | 0.0% | 0.759 | 0.47 | 2.5초 |
| 2026-11-17 | `chatterbox-mlx` | 1.0% | 0.745 | 0.95 | 1.3초 |

Qwen3가 느려진 것은 말끝 보정 때문입니다(꼬리말을 붙여 조금 더 길게 만들고, 깨끗이 못 자르면 다시 만듦). 기준선(같은 사람의 서로 다른 녹음끼리 SIM)은 앞뒤 무음을 걷어 내고 재면 0.737입니다.

- **기준선**: 같은 사람의 서로 다른 참조 녹음끼리 SIM이 0.753입니다. 두 엔진 모두 이 수준이라, 화자 유사도로는 원래 목소리와 구별이 어렵습니다.
- **오독**: Chatterbox는 "할 일"을 "할의"처럼 붙여 읽는 경우가 20문장 중 3번 있었습니다. Qwen3는 오독이 없었습니다.
- **숫자**: Chatterbox는 아라비아 숫자를 엉뚱하게 읽습니다(숫자 문장 CER 0.39~0.46). 그래서 Chatterbox 엔진에는 숫자를 한국어 소리로 바꿔 넘깁니다(`textnorm.py`: `2026년` → `이천이십육년`, `9시` → `아홉 시`, `12%` → `십이 퍼센트`). 바꾼 뒤에는 숫자 문장도 오독이 없습니다. 실제로 읽은 문장은 응답의 `spoken_text`에서 볼 수 있습니다.
- **문장 끝(Qwen3)**: Qwen3(녹음+대본 복제)는 마지막 음절을 서둘러 닫고 곧바로 끝냅니다(끝 무음 0.01~0.07초). 끝에 무음을 더하거나 끝내기 신호를 미뤄도 말소리 자체는 그대로였습니다. 대본 없이 목소리 특징만 쓰는 방식은 말끝은 자연스럽지만 오독이 늘어 쓰지 않습니다.
  - 그래서 문장 뒤에 꼬리말 ` 네.`를 붙여 만들고, 문장과 꼬리말 사이의 쉼에서 잘라 냅니다(`ending.py`). 모델이 문장 끝을 '중간'처럼 온전히 읽습니다. 마지막 음절의 여운 0.12초를 남기고 0.02초 동안 줄입니다.
  - 쉼이 0.2초보다 짧거나, 쉼 안 소리가 최대 음량의 0.1%(잡음이 섞인 결과는 그 결과 잡음 바닥의 2배, 최대 1%) 아래로 한 번도 내려가지 않으면 꼬리말 첫소리가 섞여 끝에 '쿵' 소리가 납니다. 이때는 seed를 바꿔 최대 세 번 다시 만들고, 그래도 안 되면 꼬리말 없이 만듭니다. 여러 줄도 한 번에 만들고 꼬리말은 맨 끝에만 붙입니다(줄바꿈에서는 모델이 스스로 알맞은 쉼과 여운을 둡니다).
  - 10문장 측정: 오독 0%, 꼬리말 흔적 없음, 목소리 유사도 0.728(보정 전 0.733). 두 문장이 다시 만들어졌습니다(두 번째·세 번째 시도에서 통과). 다시 만드는 만큼 그 문장은 생성 시간이 늘어납니다.
  - `VOICELAB_QWEN_CODA=0`이면 끕니다.
- **폭주 막기(Qwen3)**: 참조 녹음의 대본이 실제 녹음과 어긋나면(녹음이 문장 중간에서 끊김, 대본을 다르게 적음) Qwen3가 끝내기 신호를 내지 못하고 모델 기본 상한(8192프레임, 약 11분)까지 말 같지 않은 소리를 만듭니다. 맥에서 한 문장에 9–14분, 메모리 14GB까지 갔고, 윈도우 CPU에서는 2시간 가까이 끝나지 않았습니다.
  - 그래서 문장 길이로 어림한 길이의 2.5배 + 5초를 생성 상한으로 넘깁니다. 상한에 닿거나 말소리가 어림보다 지나치게 길면(폭주), 또는 어림의 35%보다 짧거나 무음이면(덜 읽음) seed를 바꿔 다시 만들고, 끝내 안 되면 긴 엉터리 소리 대신 이유를 담은 오류를 냅니다(`ending.py`).
  - 같은 원인을 등록 단계에서 막으려고 녹음 검사(`audio_fx.py`)가 대본 음절 수 ÷ 말소리 길이로 대본·녹음 맞춤을 봅니다(초당 1.5–10음절 밖이면 등록 거절).
  - 견딤 시험(`tools/stress.py`)에서 대본만 맞으면 0.9초짜리 참조 녹음도 정상으로 끝났습니다. 폭주의 원인은 길이가 아니라 대본 불일치였습니다.
- **끝 무음**: 모든 엔진 결과의 끝 무음을 **최소 0.3초**로 맞춥니다(`VOICELAB_TAIL_SILENCE`, 0이면 끔). Chatterbox는 원래 0.4~0.6초 여운이 있어 바뀌지 않습니다.
- **채점 주의**: 화자 유사도(ECAPA)는 끝 무음 길이에 흔들립니다(같은 소리에 무음 0.2초만 더해도 0.05~0.08 하락). `tools/evaluate.py`는 앞뒤 무음을 걷어 내고 비교합니다.
- **속도**: RTF는 생성 시간 ÷ 음성 길이입니다. Qwen3는 실시간의 약 2배, Chatterbox는 실시간 정도입니다.
- **정리**: 맥에서는 Qwen3-MLX가 정확도·속도 모두 조금 낫습니다. 개발 주체 국가를 따지는 기관이라면 Chatterbox-MLX도 품질 차이가 작아 실사용에 충분합니다.

CER은 faster-whisper large-v3로 받아 적어, 띄어쓰기·문장부호를 빼고 숫자는 양쪽 모두 같은 규칙으로 한글로 바꾼 뒤 글자 단위로 비교했습니다. SIM은 어느 엔진과도 무관한 SpeechBrain ECAPA 화자 임베딩의 코사인 유사도입니다.

다시 재려면:

```bash
.venv/bin/python tools/benchmark.py --engines qwen3-mlx,chatterbox-mlx --styles talk,guide -o outputs/bench
python3.12 -m venv .venv-eval && .venv-eval/bin/pip install faster-whisper speechbrain torch torchaudio soundfile
.venv-eval/bin/python tools/evaluate.py outputs/bench   # → outputs/bench/report.md
```

## 새 엔진 붙이기

1. `backends/<이름>.py`에 `Backend`를 상속한 클래스를 만듭니다. `info`, `check`, `load`, `generate`를 채웁니다. 모듈을 import할 때 무거운 패키지를 불러오지 않습니다.
2. `backends/__init__.py`의 `REGISTRY`에 `"<계열>-<실행 방식>": "backends.<모듈>:<클래스>"`를 더합니다. 같은 계열 안에서는 빠른 실행 방식을 위에 둡니다.
3. 의존성이 겹치면 `requirements/engine-<계열>.txt`를 만들어 `.venv-<계열>`에 설치합니다.
4. 숫자를 잘못 읽는 모델이면 `BackendInfo(reads_digits=False)`로 둡니다. 숫자를 한국어 소리로 바꿔 넘깁니다.
5. `tools/smoke_engine.py --engine <id>`와 `tools/benchmark.py`로 확인합니다.
