@echo off
chcp 65001 >nul
REM ============================================================
REM  Log a real farm session to calibrate a spot's kills/hr.
REM  Pass args, e.g.:
REM    log_session.bat --spot Sleepers --minutes 60 --kills 1150
REM    log_session.bat --spot Sleepers --minutes 60 --loot "Great Nature:410"
REM ============================================================
cd /d "%~dp0collector"
call .venv\Scripts\activate.bat
python -m ro_collector.log_session %*
pause
