@echo off
rem 내 목소리 생성기 - Windows 실행. 127.0.0.1 에만 열린다.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 가상환경이 없어 설치를 먼저 진행합니다.
  call setup.bat || exit /b 1
)
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
echo 내 목소리 생성기를 엽니다. 모델 다운로드 진행 막대는 이 창에 표시됩니다.
".venv\Scripts\python.exe" app.py --open
if errorlevel 1 (
  echo.
  echo [오류] 서버가 종료되었습니다. 위쪽 오류를 확인하세요.
  pause
)
