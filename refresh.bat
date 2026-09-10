@echo off
chcp 65001 >nul
REM ============================================================
REM  RO Economy Command Center - "Refresh Reference Data" (monthly)
REM  Re-crawls server monster drop tables + wiki turn-in quests.
REM  Headless (no Cloudflare gate here); takes ~20-40 min.
REM  Run this occasionally, not daily.
REM ============================================================
cd /d "%~dp0collector"
call .venv\Scripts\activate.bat
python -m ro_collector.run_refresh
echo.
echo Done. Reference data (monsters, drops, quests) refreshed.
echo NPC prices come from the CP crawl: python -m ro_collector.enrich_items
pause
