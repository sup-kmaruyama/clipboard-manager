@echo off
rem One-time setup: registers the "fmclip://" custom protocol so that
rem clicking a fmclip:// link launches this folder's clipboard manager.
rem No administrator rights required (registered for current user only).

set "LAUNCHER=%~dp0launch_protocol.bat"

reg add "HKCU\Software\Classes\fmclip" /ve /d "URL:FM Clipboard Manager Protocol" /f
reg add "HKCU\Software\Classes\fmclip" /v "URL Protocol" /t REG_SZ /d "" /f
reg add "HKCU\Software\Classes\fmclip\shell\open\command" /ve /d "\"%LAUNCHER%\" \"%%1\"" /f

echo.
echo Done. The fmclip:// protocol is now registered.
echo Open launcher.html and click the button to try it.
pause
