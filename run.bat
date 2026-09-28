@echo off
REM Runs DeepLoyerFree from source. Uses uv if available, otherwise a local virtualenv.
cd /d "%~dp0"

where uv >nul 2>nul
if %errorlevel%==0 (
  uv run deeployerfree.py %*
  exit /b %errorlevel%
)

if not exist ".venv\Scripts\pythonw.exe" (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python 3.10+ is required ^(or install uv: winget install astral-sh.uv^).
    pause
    exit /b 1
  )
  echo First run: creating .venv and installing dependencies...
  py -3 -m venv .venv || exit /b 1
  ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q || exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" deeployerfree.py %*