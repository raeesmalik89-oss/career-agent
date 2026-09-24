@echo off
rem Starts the Career Agent on Windows: the API (port 8010) and the dashboard (port 3000), then opens the browser.
rem Close the two windows it opens to stop it.
cd /d "%~dp0"
set PYTHONPATH=backend;.
set API_PORT=8010

if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found. Run "uv sync" in this folder first.
  pause
  exit /b 1
)
if not exist "frontend\node_modules" (
  echo Installing dashboard packages - first run only...
  pushd frontend
  call npm install
  popd
)

start "Career Agent API" .venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %API_PORT%
set "BACKEND_URL=http://127.0.0.1:%API_PORT%"
start "Career Agent Dashboard" /d frontend cmd /k npm run dev

echo Waiting for the dashboard to start...
timeout /t 12 /nobreak >nul
start "" http://localhost:3000
