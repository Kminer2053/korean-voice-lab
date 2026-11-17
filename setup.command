#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || {
  echo "프로젝트 폴더로 이동하지 못했습니다."
  read -r -p "엔터 키를 누르면 이 창을 닫습니다: "
  exit 1
}

fail() {
  echo ""
  echo "설치에 실패했습니다."
  echo "$1"
  echo ""
  echo "해결 방법: $2"
  read -r -p "엔터 키를 누르면 이 창을 닫습니다: "
  exit 1
}

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  fail "이 프로그램은 Apple Silicon Mac(M1 이상)에서만 돕니다. 지금: $(uname -s) $(uname -m)" "MLX는 Apple Silicon 전용입니다. 다른 OS는 README의 '다른 OS' 절을 보세요."
fi

# Python 3.11–3.13 중 먼저 찾은 것을 쓴다. PYTHON 환경변수로 직접 지정할 수도 있다.
PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for cand in python3.12 /opt/homebrew/bin/python3.12 python3.13 /opt/homebrew/bin/python3.13 python3.11 /opt/homebrew/bin/python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
  done
fi
if [[ -z "$PY" || ! -x "$PY" ]]; then
  fail "Python 3.11–3.13을 찾지 못했습니다." "터미널에서 brew install python@3.12 를 실행한 뒤 이 파일을 다시 더블클릭하세요. 전역 pip install 은 하지 마세요."
fi
echo "사용할 Python: $PY"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  "$PY" -m venv "$ROOT/.venv" || fail "가상환경을 만들지 못했습니다." "디스크 여유 공간을 확인한 뒤 setup.command를 다시 실행하세요. 패키지는 이 폴더의 .venv 안에만 설치됩니다."
fi

"$ROOT/.venv/bin/python" -m pip install --upgrade pip || fail "pip를 준비하지 못했습니다." "네트워크 연결을 확인하세요. 설치 위치는 이 프로젝트의 .venv 입니다."
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt" || fail "패키지 설치에 실패했습니다." "네트워크를 확인한 뒤 setup.command를 다시 더블클릭하세요. 전역 pip는 사용하지 않습니다."

echo ""
echo "설치가 끝났습니다."
echo "다음으로 이 파일을 더블클릭하세요:"
echo "$ROOT/start.command"
read -r -p "엔터 키를 누르면 이 창을 닫습니다: "
