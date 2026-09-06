@echo off
title Zaria Court Ordering System - public
cd /d "%~dp0"

REM Runs the system so BOTH kinds of guest can order: those on Zaria Wi-Fi and
REM those on their own data bundle. The tunnel gives it an https address on the
REM internet; no router changes, no port forwarding, no fixed IP.

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

set "CFT=%~dp0cloudflared.exe"
if not exist "%CFT%" (
  echo.
  echo   cloudflared.exe is not in this folder.
  echo.
  echo   Download it once from:
  echo     https://github.com/cloudflare/cloudflared/releases/latest
  echo   Pick   cloudflared-windows-amd64.exe
  echo   Rename it to   cloudflared.exe   and put it beside this file.
  echo.
  echo   It is free and needs no account for a temporary address.
  echo.
  pause
  exit /b 1
)

echo.
echo   Starting the ordering system...
echo.
start "Zaria ordering server" /min cmd /c "python server.py --host 0.0.0.0 --port 8080 --public & pause"

REM Give the server a moment to bind the port before the tunnel reaches for it.
timeout /t 4 /nobreak >nul

echo   Opening the public address. Watch for a line ending in
echo   trycloudflare.com - that is the address guests use.
echo.
echo   IMPORTANT: paste that address into Admin ^> Settings ^> Public address,
echo   or the QR codes will point at the wrong place.
echo.

REM --protocol http2 is not optional here. Zaria's Wi-Fi blocks the UDP protocol
REM cloudflared prefers, and without this flag it sits in a retry loop and no
REM public address ever comes up.
"%CFT%" tunnel --url http://localhost:8080 --protocol http2 --no-autoupdate

echo.
echo   The tunnel has stopped. Guests on mobile data can no longer reach it;
echo   guests on Zaria Wi-Fi still can, at the venue address.
pause
