@echo off
chcp 65001 >nul
REM ============================================================
REM  pricefinder — поиск цен по товарам из queries.txt (Windows)
REM ============================================================
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    where python >nul 2>nul || (echo [ОШИБКА] Python не найден. Запустите setup.bat & pause & exit /b 1)
)

if not exist queries.txt (
    echo Создаю queries.txt — откройте его в блокноте и впишите товары.
    python price_finder.py init-queries
    notepad queries.txt
    pause
    exit /b 0
)

python price_finder.py search --queries-file --top 15 --by-site --best --save out\results.xlsx
echo.
echo Результаты также сохранены в out\results.xlsx
pause
