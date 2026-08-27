@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "LAUNCHER=%PROJECT_ROOT%scripts\start_xuanshu_lab.ps1"

if not exist "%LAUNCHER%" (
  echo XUANSHU LAB launcher was not found:
  echo %LAUNCHER%
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" %*
if errorlevel 1 (
  echo.
  echo XUANSHU LAB failed to start. See the message above.
  pause
  exit /b 1
)

endlocal
