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
| `chatterbox-mlx` | 코드 연결 완료. 가중치(2.7GB) 내려받기와 한국어 생성·비교는 남음 |
| `chatterbox-torch` | 코드 연결 완료. Windows CPU 실검증은 GitHub Actions `windows-smoke`로 진행 |
| `qwen3-torch` | 코드 연결 완료. NVIDIA GPU 환경 검증 필요 |

비교는 `tools/benchmark.py`(생성·속도)와 `tools/evaluate.py`(받아쓰기 오독률 CER, ECAPA 화자 유사도)로 합니다. 결과는 이 문서에 덧붙입니다.

## 새 엔진 붙이기

1. `backends/<이름>.py`에 `Backend`를 상속한 클래스를 만듭니다. `info`, `check`, `load`, `generate`를 채웁니다. 모듈을 import할 때 무거운 패키지를 불러오지 않습니다.
2. `backends/__init__.py`의 `REGISTRY`에 `"<계열>-<실행 방식>": "backends.<모듈>:<클래스>"`를 더합니다. 같은 계열 안에서는 빠른 실행 방식을 위에 둡니다.
3. 의존성이 겹치면 `requirements/engine-<계열>.txt`를 만들어 `.venv-<계열>`에 설치합니다.
4. `tools/smoke_engine.py --engine <id>`와 `tools/benchmark.py`로 확인합니다.
