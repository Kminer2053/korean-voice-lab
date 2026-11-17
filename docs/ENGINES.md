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
| `qwen3-torch` | 코드 연결 완료. NVIDIA GPU 환경 검증 필요 |

### 맥 비교 결과(2026-11-17, M5 16GB)

같은 사람의 참조 녹음 2개(대화·안내 말투) × 한국어 문장 10개(인사·안내·질문·감탄·외래어·숫자·긴 문장), seed 1.

| 엔진 | 받아쓰기 오독률(CER) | 화자 유사도(SIM) | 속도(RTF) | 모델 적재 |
|---|---|---|---|---|
| `qwen3-mlx` | 0.0% | 0.759 | 0.47 | 2.5초 |
| `chatterbox-mlx` | 1.0% | 0.745 | 0.95 | 1.3초 |

- **기준선**: 같은 사람의 서로 다른 참조 녹음끼리 SIM이 0.753입니다. 두 엔진 모두 이 수준이라, 화자 유사도로는 원래 목소리와 구별이 어렵습니다.
- **오독**: Chatterbox는 "할 일"을 "할의"처럼 붙여 읽는 경우가 20문장 중 3번 있었습니다. Qwen3는 오독이 없었습니다.
- **숫자**: Chatterbox는 아라비아 숫자를 엉뚱하게 읽습니다(숫자 문장 CER 0.39~0.46). 그래서 Chatterbox 엔진에는 숫자를 한국어 소리로 바꿔 넘깁니다(`textnorm.py`: `2026년` → `이천이십육년`, `9시` → `아홉 시`, `12%` → `십이 퍼센트`). 바꾼 뒤에는 숫자 문장도 오독이 없습니다. 실제로 읽은 문장은 응답의 `spoken_text`에서 볼 수 있습니다.
- **문장 끝**: Qwen3는 마지막 음절 바로 뒤에서 끝나(끝 무음 0.01~0.07초) 브라우저·블루투스 재생에서 끝이 먹혀 서둘러 끊긴 것처럼 들렸습니다. 음성 자체는 온전합니다(끝 신호를 미뤄 더 생성해 봐도 원래 끝까지 파형이 같고 뒤는 무음). 그래서 모든 엔진 결과의 끝 무음을 **최소 0.3초**로 맞춥니다(`VOICELAB_TAIL_SILENCE`, 0이면 끔). 여러 줄 문장의 줄 사이에도 0.3초 쉼을 둡니다. Chatterbox는 원래 0.4~0.6초 여운이 있어 바뀌지 않습니다.
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
