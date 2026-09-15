@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "LAUNCHER=%PROJECT_ROOT%Start-XUANSHU-LAB.cmd"

if not exist "%LAUNCHER%" (
  echo XUANSHU AI official launcher was not found:
  echo %LAUNCHER%
  pause
  exit /b 1
)

echo Start-Vision2Grasp.cmd is a compatibility alias.
echo Official entry: %LAUNCHER%
call "%LAUNCHER%" %*
if errorlevel 1 (
  echo.
  echo XUANSHU AI failed to start. See the message above.
  pause
  exit /b 1
)

endlocal
