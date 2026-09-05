@echo off
rem One-time setup: clones this tool (if not already present), installs the
rem required Python package, registers the fmclip:// launch link, and starts
rem the tool. Safe to run again later to update to the latest version.
rem Windows only.

setlocal
set "REPO_URL=https://github.com/sup-kmaruyama/clipboard-manager.git"
set "DEST=%USERPROFILE%\clipboard-manager"

where git >nul 2>nul
if errorlevel 1 (
    echo Git is not installed. Install it first: https://git-scm.com/download/win
    pause
    exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
    echo Python is not installed. Install it first: https://www.python.org/downloads/
    pause
    exit /b 1
)

if exist "%DEST%\.git" (
    echo Updating existing copy at %DEST% ...
    cd /d "%DEST%"
    git pull
) else (
    echo Cloning into %DEST% ...
    git clone "%REPO_URL%" "%DEST%"
    cd /d "%DEST%"
)

echo Installing required Python package (pywin32) ...
python -m pip install --quiet pywin32

echo Registering the fmclip:// launch link ...
set "LAUNCHER=%DEST%\launch_protocol.bat"
reg add "HKCU\Software\Classes\fmclip" /ve /d "URL:FM Clipboard Manager Protocol" /f >nul
reg add "HKCU\Software\Classes\fmclip" /v "URL Protocol" /t REG_SZ /d "" /f >nul
reg add "HKCU\Software\Classes\fmclip\shell\open\command" /ve /d "\"%LAUNCHER%\" \"%%1\"" /f >nul

echo.
echo Setup complete. Starting the tool now ...
start "" python "%DEST%\server.py"
timeout /t 2 >nul
start "" http://127.0.0.1:8934/

echo.
echo From now on, you can launch it again any time by:
echo   - double-clicking "%DEST%\起動.bat", or
echo   - clicking any fmclip://open link (see launcher.html)
pause
