@echo off
rem Starts the Career Agent on Windows: the API (port 8010), the scheduler and the dashboard (port 3000),
rem then opens the browser. Close the three windows it opens to stop it.
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

echo Updating the database (safe to repeat)...
.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
  echo Database update failed - see the message above.
  pause
  exit /b 1
)

start "Career Agent API" .venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %API_PORT%
rem Runs the daily scan, skill-gap analysis, evening prep and weekly GitHub sync on schedule (Settings - Automation).
start "Career Agent Scheduler" /min .venv\Scripts\python.exe -m scheduler
set "BACKEND_URL=http://127.0.0.1:%API_PORT%"
start "Career Agent Dashboard" /d frontend cmd /k npm run dev

echo Waiting for the dashboard to start...
timeout /t 12 /nobreak >nul
start "" http://localhost:3000
