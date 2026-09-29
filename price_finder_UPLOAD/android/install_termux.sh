#!/usr/bin/env bash
# ============================================================
#  Установка pricefinder в Termux (Android)
#  Запуск:  bash android/install_termux.sh
# ============================================================
set -euo pipefail

if [ -z "${PREFIX:-}" ]; then
  echo "[!] Скрипт рассчитан на Termux. Откройте Termux и выполните:"
  echo "      cd ~/price_finder && bash android/install_termux.sh"
  exit 1
fi

cd "$(dirname "$0")/.." || exit 1
echo "[i] Рабочая папка: $(pwd)"

echo "[1/6] Обновляю пакеты Termux"
pkg update -y
pkg upgrade -y || true

echo "[2/6] Ставлю python, git и базовые библиотеки"
pkg install -y python git libxml2 libxslt libffi openssl

echo "[3/6] Создаю виртуальное окружение"
python -m venv .venv || {
  echo "[!] venv не создался — поставлю пакеты глобально"
  VENV_PY=python
  VENV_PIP="python -m pip"
}
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
  VENV_PY=python
  VENV_PIP="pip"
fi

echo "[4/6] Обязательные зависимости (requests + beautifulsoup4)"
$VENV_PIP install --upgrade pip wheel setuptools >/dev/null
$VENV_PIP install requests beautifulsoup4

echo "[5/6] Необязательные, но полезные"
# PyYAML: ускоряет чтение конфига; без него работает встроенный мини-парсер
pkg install -y python-yaml >/dev/null 2>&1 || $VENV_PIP install pyyaml || \
  echo "    (PyYAML не поставился — не страшно, есть встроенный парсер YAML)"
# lxml: быстрее разбирает HTML; без него используется html.parser
pkg install -y python-lxml >/dev/null 2>&1 || $VENV_PIP install lxml || \
  echo "    (lxml не поставился — используется html.parser, чуть медленнее)"
# openpyxl: только если нужны отчёты Excel на телефоне
$VENV_PIP install openpyxl || echo "    (openpyxl не поставился — Excel-отчёты будут недоступны)"

echo "[6/6] Проверяю установку"
$VENV_PY price_finder.py env || true
$VENV_PY price_finder.py init-config  >/dev/null 2>&1 || true
$VENV_PY price_finder.py init-queries >/dev/null 2>&1 || true

cat <<'EOF'

============================================================
 Готово! Что дальше:

 1) Активируйте окружение (один раз за сессию Termux):
      cd ~/price_finder && source .venv/bin/activate

 2) Текстовый режим (работает всегда):
      python price_finder.py search "iphone 15"
      python price_finder.py search --queries-file

 3) Список товаров — правьте в любом редакторе:
      nano queries.txt          # или «Открыть» в Acode/Quoda

 4) Графический интерфейс (нужен kivy + termux-x11):
      bash android/install_gui_termux.sh
      python price_finder.py gui

 5) Уведомления в шторку Android:
      установите приложение «Termux:API» из F-Droid, затем:
      pkg install termux-api
      python price_finder.py notify-test

 6) Мониторинг по расписанию (даже когда Termux закрыт):
      bash android/setup_termux_job.sh "30m"

 Подробная инструкция: android/ANDROID.md
============================================================
EOF
