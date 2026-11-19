@echo off
REM ============================================================
REM  GlobalBLOCS Quant - build the Windows installation wizard
REM  Double-click this file on a Windows PC. Requires Node.js 20+
REM  (https://nodejs.org). Output: desktop\dist\GlobalBLOCS-Quant-Setup-1.0.0.exe
REM ============================================================
setlocal
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js was not found. Install Node.js 20 LTS from https://nodejs.org and run this file again.
  start https://nodejs.org/en/download
  pause
  exit /b 1
)

echo [1/3] Building the dashboard...
pushd frontend
call npm ci || goto :fail
call npm run build || goto :fail
popd

echo [2/3] Installing desktop build tools...
pushd desktop
call npm install || goto :fail

echo [3/3] Creating the installer wizard...
call npx electron-builder --win nsis --x64 --publish never || goto :fail
popd

echo.
echo Done. Your installer is in: %~dp0desktop\dist
explorer "%~dp0desktop\dist"
pause
exit /b 0

:fail
echo.
echo Build failed. Scroll up for the error message.
pause
exit /b 1
