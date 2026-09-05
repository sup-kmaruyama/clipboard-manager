@echo off
rem Double-click this file to start the clipboard history manager.
rem First run only: "pip install pywin32" is required (see README).
cd /d "%~dp0"
start "" python server.py
timeout /t 2 >nul
start "" http://127.0.0.1:8934/
