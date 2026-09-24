@echo off
rem Daily job scan: fetches postings from the enabled sources, de-duplicates them and scores them.
rem Uses about 4 of your Jooble requests. Usage: scan-jobs.cmd you@example.com
cd /d "%~dp0"
set PYTHONPATH=backend;.
if "%~1"=="" (
  set /p EMAIL=Your login email:
) else (
  set EMAIL=%~1
)
.venv\Scripts\python.exe -m app.cli scan-jobs --email %EMAIL% > storage\last_scan.json
.venv\Scripts\python.exe -m app.cli match-jobs --email %EMAIL% --out storage\matches.json
echo.
echo Done. Open http://localhost:3000/matches to see the results.
pause
