@echo off
title Zaria Court Ordering System
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Python was not found on this computer.
  echo   Install it from https://www.python.org/downloads/ and tick
  echo   "Add python.exe to PATH" during setup, then run this file again.
  echo.
  pause
  exit /b 1
)

echo.
echo   Starting the Zaria Court ordering system...
echo   Phones on the same Wi-Fi can reach it at the address shown below.
echo.

python server.py --host 0.0.0.0 --port 8080

echo.
echo   The server has stopped.
pause
