#!/usr/bin/env bash
# pricefinder — поиск цен по товарам из queries.txt. Запуск: bash search.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [ ! -f queries.txt ]; then
  echo "Создаю queries.txt — впишите туда свои товары и запустите скрипт ещё раз."
  python3 price_finder.py init-queries
  exit 0
fi

mkdir -p out
python3 price_finder.py search --queries-file --top 15 --by-site --best --save out/results.xlsx
echo
echo "Результаты также сохранены в out/results.xlsx"
