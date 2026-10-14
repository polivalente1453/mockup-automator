@echo off
rem Windows: double-click to start the Mockup Automator. Extra arguments are passed through.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 launcher.py %*
) else (
  python launcher.py %*
)
if errorlevel 1 pause
