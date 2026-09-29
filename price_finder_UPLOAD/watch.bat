@echo off
chcp 65001 >nul
REM ============================================================
REM  pricefinder — мониторинг цен по товарам из queries.txt
REM  Окно можно свернуть; остановка — Ctrl+C
REM ============================================================
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    where python >nul 2>nul || (echo [ОШИБКА] Python не найден. Запустите setup.bat & pause & exit /b 1)
)

if not exist queries.txt (
    echo Сначала создайте queries.txt: запустите search.bat или python price_finder.py init-queries
    pause
    exit /b 1
)

echo Мониторинг каждые 30 минут. Остановка — Ctrl+C
python price_finder.py watch --queries-file --interval 30m --drop-pct 3 --save out\snapshot_{query}.xlsx
pause
