@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (python .avx1\portable_build.py %*) else (py -3 .avx1\portable_build.py %*)
exit /b %errorlevel%
