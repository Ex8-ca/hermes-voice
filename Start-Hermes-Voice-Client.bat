@echo off
REM Start-Hermes-Voice-Client.bat — launch the hermes-voice Python client on Windows.
REM
REM This is the .bat equivalent of start-voice-client.ps1, for users who
REM prefer double-click launchers or can't run PowerShell scripts.
REM
REM Requirements: Git Bash installed (the launcher shells out to bash to
REM call the venv python, since venv activation under cmd is awkward).
REM
REM Before first use: run bootstrap-client.ps1 once to install the venv + deps.
REM
REM Usage:
REM   Double-click Start-Hermes-Voice-Client.bat, OR
REM   From a terminal: Start-Hermes-Voice-Client.bat [list-devices]

setlocal

set "PROJECT_DIR=%~dp0"
set "BASH_EXE=C:\Program Files\Git\bin\bash.exe"

if not exist "%BASH_EXE%" (
    echo Git Bash not found at "%BASH_EXE%".
    echo Install Git for Windows from https://git-scm.com/download/win
    echo or edit BASH_EXE in this launcher for your Git Bash location.
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%venv\Scripts\python.exe" (
    echo venv not found. Run bootstrap-client.ps1 first to install.
    echo.
    echo If PowerShell scripts are blocked, open PowerShell as Admin and run:
    echo     Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
    echo Then: .\bootstrap-client.ps1 192.168.1.3 7979
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%.env" (
    echo .env not found. Run bootstrap-client.ps1 to create it.
    pause
    exit /b 1
)

REM Forward the optional first arg (e.g. "list-devices") to the launcher
set "EXTRA=%~1"

"%BASH_EXE%" -lc "cd \"$(cygpath -u '%PROJECT_DIR%')\" && ./venv/Scripts/python.exe -m hermes_voice.client %EXTRA%"

endlocal
