@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" CodingPlan_monitor.py
) else (
    start "" pythonw CodingPlan_monitor.py
)
exit
