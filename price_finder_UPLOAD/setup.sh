#!/usr/bin/env bash
# pricefinder — установка (Linux / macOS). Запуск: bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ОШИБКА] python3 не найден. Установите Python 3.10+ (Linux: sudo apt install python3 python3-venv, macOS: brew install python)"
  exit 1
fi

echo "[1/3] Виртуальное окружение .venv"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/3] Зависимости"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "[3/3] Список товаров queries.txt"
[ -f queries.txt ] || python3 price_finder.py init-queries

cat <<'EOF'

============================================================
 Готово. Дальше:
   1) откройте queries.txt и впишите свои товары (по одному на строку)
   2) bash search.sh          — найти самые низкие цены
   3) bash watch.sh           — следить за ценами (каждые 30 минут)
============================================================
EOF
