@echo off
chcp 65001 >nul
REM ============================================================
REM  RO Economy Command Center - "Collect Fresh Data" button
REM  Double-click to scrape the live market and print tonight's
REM  grind board. A Chrome window opens; if Cloudflare shows a
REM  "verify you're human" box, click it once, then walk away.
REM ============================================================
cd /d "%~dp0collector"
call .venv\Scripts\activate.bat
python -m ro_collector.run_scrape_local
echo.
echo ============================================================
echo  Done. Scroll up for your GRIND BOARD.
echo ============================================================
pause
