#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || {
  echo "프로젝트 폴더로 이동하지 못했습니다."
  read -r -p "엔터 키를 누르면 이 창을 닫습니다: "
  exit 1
}

fail() {
  echo ""
  echo "실행에 실패했습니다."
  echo "$1"
  echo ""
  echo "해결 방법: $2"
  read -r -p "엔터 키를 누르면 이 창을 닫습니다: "
  exit 1
}

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "가상환경이 없어 설치를 먼저 진행합니다."
  bash "$ROOT/setup.command" || fail "설치가 끝나지 않았습니다." "setup.command 창의 안내를 확인하세요."
fi

export PYTHONUNBUFFERED=1
export HF_HOME="$ROOT/.cache/huggingface"
export HF_HUB_CACHE="$ROOT/.cache/huggingface/hub"
export HUGGINGFACE_HUB_CACHE="$ROOT/.cache/huggingface/hub"
export HF_HUB_DISABLE_TELEMETRY=1
export GRADIO_ANALYTICS_ENABLED=False
export GRADIO_SHARE=False
export DO_NOT_TRACK=1

echo "목소리 실험 화면을 엽니다. 주소는 127.0.0.1 입니다."
echo "모델 다운로드 진행 막대는 이 창에 표시됩니다."
"$ROOT/.venv/bin/python" "$ROOT/app.py" --open
status=$?
if [[ $status -ne 0 ]]; then
  fail "화면 서버가 종료되었습니다. 코드: $status" "위쪽의 오류를 확인하세요. 7860번 포트를 다른 프로그램이 쓰고 있으면 그 프로그램을 끈 뒤 start.command를 다시 실행하세요."
fi
