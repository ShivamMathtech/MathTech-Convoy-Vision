@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3.12 scripts\bootstrap.py
) else (
    python scripts\bootstrap.py
)
if %errorlevel% neq 0 pause

