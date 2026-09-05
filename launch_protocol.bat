@echo off
rem Invoked by fmclip:// links. If already running, the second instance
rem just fails to bind the port and exits; harmless.
cd /d "%~dp0"
start "" pythonw server.py
timeout /t 1 >nul
start "" http://127.0.0.1:8934/
