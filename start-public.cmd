@echo off
rem Starts Career Agent in production mode and puts it on the internet through a free Cloudflare quick tunnel,
rem so people you invite can sign up and use it. Nothing is open on your router: cloudflared connects outwards.
rem The public address changes every time this starts, and it only works while this PC is on.
rem Close the windows it opens to stop it. Use start-career-agent.cmd instead for private use on this PC.
cd /d "%~dp0"
set PYTHONPATH=backend;.
set API_PORT=8010
set WEB_PORT=3000
set LOG_FORMAT=text
rem production: secure cookies, no /docs, and the API refuses to start with a weak configuration
set APP_ENV=production
set COOKIE_SECURE=true
set NEXT_TELEMETRY_DISABLED=1

where cloudflared >nul 2>nul
if errorlevel 1 (
  echo cloudflared is not installed. Install it once with:
  echo     winget install --id Cloudflare.cloudflared
  echo then open a new window and run this file again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found. Run "uv sync" in this folder first.
  pause
  exit /b 1
)
netstat -ano | findstr /r /c:":%WEB_PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo Port %WEB_PORT% is in use - close the normal Career Agent windows first, then run this again.
  pause
  exit /b 1
)

echo Updating the database (safe to repeat)...
.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
  echo Database update failed - see the message above.
  pause
  exit /b 1
)

echo Building the dashboard for production (about a minute)...
pushd frontend
if not exist "node_modules" call npm install
set "BACKEND_URL=http://127.0.0.1:%API_PORT%"
call npm run build
if errorlevel 1 (
  popd
  echo Dashboard build failed - see the message above.
  pause
  exit /b 1
)
xcopy /e /i /y /q ".next\static" ".next\standalone\.next\static" >nul
if exist "public" xcopy /e /i /y /q "public" ".next\standalone\public" >nul
popd

start "Career Agent API" .venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %API_PORT%
start "Career Agent Scheduler" /min .venv\Scripts\python.exe -m scheduler
start "Career Agent Dashboard" /d frontend\.next\standalone cmd /k "set PORT=%WEB_PORT%&& set HOSTNAME=127.0.0.1&& set NODE_ENV=production&& node server.js"

if not exist "storage\logs" mkdir "storage\logs"
if exist "storage\logs\tunnel.log" del "storage\logs\tunnel.log"
start "Career Agent Public Link (keep open)" /min cloudflared tunnel --no-autoupdate --url http://127.0.0.1:%WEB_PORT% --logfile storage\logs\tunnel.log

echo Waiting for the public address...
powershell -NoProfile -Command ^
  "$u=$null; for($i=0;$i -lt 45 -and -not $u;$i++){ Start-Sleep 1; if(Test-Path 'storage\logs\tunnel.log'){ $m=Select-String -Path 'storage\logs\tunnel.log' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1; if($m){ $u=$m.Matches[0].Value } } };" ^
  "if($u){ Set-Content -Path 'storage\public-url.txt' -Value $u; Set-Clipboard $u; Write-Host ''; Write-Host ('  Public address: ' + $u) -ForegroundColor Green; Write-Host '  (copied to the clipboard; also saved in storage\public-url.txt)'; Write-Host '  Create invitations in Users while signed in at this address, so the links use it.'; Start-Sleep 6; Start-Process $u } else { Write-Host 'No address yet - look in the Career Agent Public Link window.' -ForegroundColor Yellow }"
echo.
pause
