@echo off
chcp 65001 >nul
REM ============================================================
REM  pricefinder — быстрый запуск (Windows)
REM  Двойной клик: установка зависимостей + создание списка товаров
REM ============================================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Python не найден в PATH.
    echo Установите Python 3.10+ с https://python.org ^(обязательно поставьте галочку "Add python.exe to PATH"^)
    pause
    exit /b 1
)

echo [1/3] Создаю виртуальное окружение .venv ...
if not exist .venv (
    python -m venv .venv
)

echo [2/3] Устанавливаю зависимости ...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt

echo [3/3] Проверяю список товаров queries.txt ...
if not exist queries.txt (
    python price_finder.py init-queries
)

echo.
echo ============================================================
echo  Готово. Дальше:
echo    1) откройте queries.txt в блокноте и впишите свои товары
echo    2) запустите поиск:  search.bat
echo ============================================================
pause
