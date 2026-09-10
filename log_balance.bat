@echo off
chcp 65001 >nul
REM ============================================================
REM  Log a zeny balance snapshot. Pass args, e.g.:
REM    log_balance.bat 12000000
REM    log_balance.bat 12_000_000
REM ============================================================
cd /d "%~dp0collector"
call .venv\Scripts\activate.bat
python -m ro_collector.log_balance %*
pause
