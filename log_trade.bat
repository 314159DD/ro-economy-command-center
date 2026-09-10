@echo off
chcp 65001 >nul
REM ============================================================
REM  Log a real trade to the ledger. Pass args, e.g.:
REM    log_trade.bat --buy "Poring Card" --qty 3 --price 50000 --strategy flip
REM    log_trade.bat --sell 909 --qty 15 --price 150 --strategy mm
REM ============================================================
cd /d "%~dp0collector"
call .venv\Scripts\activate.bat
python -m ro_collector.log_trade %*
pause
