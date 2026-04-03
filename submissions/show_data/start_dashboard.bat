@echo off
echo =========================================
echo    Starting Task Correlation Dashboard
echo =========================================
echo.

:: Change to the directory where this script (and dashboard.html) lives
pushd "%~dp0."

:: Open the default web browser to the local server address
echo Opening browser...
start "" http://localhost:8000/dashboard.html

:: Start the Python local server (serves from CWD)
echo Starting local server on port 8000...
echo (Press CTRL+C in this window to stop the server when you are done)
echo.
python -m http.server 8000

popd
pause