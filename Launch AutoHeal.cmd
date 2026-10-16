@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 launcher.py
  goto :done
)
where python >nul 2>nul
if %errorlevel%==0 (
  python launcher.py
  goto :done
)
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" launcher.py
  goto :done
)
echo Python 3.10 or newer is required to launch AutoHeal.
pause
exit /b 1
:done
if errorlevel 1 pause
endlocal
