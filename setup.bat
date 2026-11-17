@echo off
rem 내 목소리 생성기 - Windows 설치. 이 폴더 안의 가상환경에만 설치하고 전역 설치는 하지 않는다.
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem ---- Python 3.11-3.12 찾기 (chatterbox-tts 의 torch 2.6 은 3.13 미만 권장)
rem PYTHON 환경변수로 직접 지정할 수 있다(예: set PYTHON=C:\Python312\python.exe).
set "PY="
if defined PYTHON set "PY="%PYTHON%""
for %%V in (3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  echo [오류] Python 3.11 또는 3.12 를 찾지 못했습니다.
  echo        https://www.python.org/downloads/ 에서 3.12 를 설치하고 "Add python.exe to PATH" 와 "py launcher" 를 켜 주세요.
  if not defined CI pause
  exit /b 1
)
echo 사용할 Python: %PY%

rem ---- 1. 서버 가상환경(.venv): 화면, HTTP API, 명령줄, MCP
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv || goto :fail
)
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements\server.txt || goto :fail

rem ---- 2. PyTorch 종류 고르기: NVIDIA GPU 가 있으면 CUDA 12.4, 없으면 CPU
set "TORCH_INDEX=https://download.pytorch.org/whl/cpu"
set "TORCH_KIND=CPU"
where nvidia-smi >nul 2>&1 && (
  nvidia-smi >nul 2>&1 && (
    set "TORCH_INDEX=https://download.pytorch.org/whl/cu124"
    set "TORCH_KIND=CUDA 12.4"
  )
)
echo PyTorch: %TORCH_KIND%

rem ---- 3. Chatterbox 엔진(.venv-chatterbox) - 미국 Resemble AI, MIT
call :engine chatterbox requirements\engine-chatterbox.txt requirements\engine-chatterbox-src.txt || goto :fail

rem ---- 4. Qwen3 엔진(.venv-qwen3) - 선택
rem 자동 설치(CI 등)에서는 VOICELAB_WITH_QWEN=y 또는 n 으로 묻지 않고 정한다.
if defined VOICELAB_WITH_QWEN (
  set "WANT_QWEN=%VOICELAB_WITH_QWEN%"
) else (
  set "WANT_QWEN=N"
  set /p WANT_QWEN="Qwen3-TTS(중국 Alibaba, Apache-2.0) 엔진도 설치할까요? 약 3GB 더 받습니다 [y/N]: "
)
if /i "%WANT_QWEN%"=="y" (
  call :engine qwen3 requirements\engine-qwen3.txt || goto :fail
)

echo.
echo 설치가 끝났습니다. start.bat 을 더블클릭하면 http://127.0.0.1:7860 이 열립니다.
echo 모델 가중치는 첫 생성 때 내려받습니다(Chatterbox 약 3GB).
if not defined CI if not defined VOICELAB_WITH_QWEN pause
exit /b 0

:engine
rem %1 = 모델 계열, %2 = requirements 파일, %3 = (선택) 의존성 없이 설치할 본체 파일
set "EV=.venv-%~1"
echo.
echo === %~1 엔진 가상환경: %EV%
if not exist "%EV%\Scripts\python.exe" (
  %PY% -m venv "%EV%" || exit /b 1
)
"%EV%\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
"%EV%\Scripts\python.exe" -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url %TORCH_INDEX% || exit /b 1
"%EV%\Scripts\python.exe" -m pip install -r "%~2" || exit /b 1
if not "%~3"=="" (
  "%EV%\Scripts\python.exe" -m pip install --no-deps -r "%~3" || exit /b 1
)
exit /b 0

:fail
echo.
echo [오류] 설치에 실패했습니다. 위쪽 메시지를 확인한 뒤 setup.bat 을 다시 실행하세요.
echo        네트워크, 디스크 여유(10GB 이상), Python 버전(3.11-3.12)을 확인하세요.
if not defined CI pause
exit /b 1
