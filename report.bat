@echo off
chcp 65001 >nul
REM ============================================================
REM  RO Economy Command Center - open the dashboard (no scrape)
REM  Rebuilds market_report.html from the current database and
REM  opens it. Use this to explore data anytime between scrapes.
REM ============================================================
cd /d "%~dp0collector"
call .venv\Scripts\activate.bat
python -m ro_collector.report
