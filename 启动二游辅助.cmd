@echo off
rem ===================================================================
rem  Eryou Assistant (portable) launcher
rem  IMPORTANT: cmd parses this file with the OEM code page, so this file
rem  must stay ASCII-only. The app exe name is Chinese, so we resolve it
rem  with a wildcard instead of hard-coding it here.
rem ===================================================================
setlocal
set "APPDIR=%~dp0app"
if not exist "%APPDIR%" (
  echo [ERROR] app directory not found: "%APPDIR%"
  echo         Re-extract the portable build with tools\extract_portable.py
  pause
  exit /b 1
)
set "EXE="
for %%F in ("%APPDIR%\*.exe") do (
  if /I not "%%~nxF"=="mabao-game-input-helper.exe" set "EXE=%%~fF"
)
if not defined EXE (
  echo [ERROR] no application exe found under "%APPDIR%"
  pause
  exit /b 1
)
pushd "%APPDIR%"
start "" "%EXE%"
popd
endlocal
