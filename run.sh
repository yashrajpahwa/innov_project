#!/usr/bin/env bash
# Creditly demo: one-time setup (if needed), then start backend + frontend.
set -e
cd "$(dirname "$0")"

if [ -x backend/.venv/bin/python ]; then PY=backend/.venv/bin/python
elif [ -x backend/.venv/Scripts/python.exe ]; then PY=backend/.venv/Scripts/python.exe
else
  echo "[setup] Creating Python virtualenv in backend/.venv ..."
  (command -v python3.11 >/dev/null && python3.11 -m venv backend/.venv) || python3 -m venv backend/.venv
  PY=backend/.venv/bin/python; [ -x "$PY" ] || PY=backend/.venv/Scripts/python.exe
  "$PY" -m pip install -r backend/requirements.txt
fi
[ -d frontend/node_modules ] || (echo "[setup] Installing frontend packages ..." && cd frontend && npm install)

PY="$(pwd)/$PY"
(cd backend && "$PY" -m uvicorn main:app --port 8000) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT INT TERM
echo "API: http://localhost:8000/docs   App: http://localhost:5173"
cd frontend && npm run dev
