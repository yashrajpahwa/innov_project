@echo off
REM Creditly demo: one-time setup (if needed), then start backend + frontend.
cd /d "%~dp0"

if not exist backend\.venv\Scripts\python.exe (
  echo [setup] Creating Python virtualenv in backend\.venv ...
  py -3.11 -m venv backend\.venv || python -m venv backend\.venv
  backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
)
if not exist frontend\node_modules (
  echo [setup] Installing frontend packages ...
  pushd frontend && call npm install && popd
)

start "Creditly API" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn main:app --port 8000"
start "Creditly UI" cmd /k "cd /d %~dp0frontend && npm run dev"
echo.
echo API: http://localhost:8000/docs
echo App: http://localhost:5173
