#!/usr/bin/env bash
# pricefinder — мониторинг цен по товарам из queries.txt. Запуск: bash watch.sh
# Остановка: Ctrl+C. В фоне: nohup bash watch.sh > watch.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [ ! -f queries.txt ]; then
  echo "Сначала создайте список товаров: bash search.sh (или python3 price_finder.py init-queries)"
  exit 1
fi

mkdir -p out
INTERVAL="${1:-30m}"
echo "Мониторинг каждые $INTERVAL (изменить: bash watch.sh 2h). Остановка — Ctrl+C"
python3 price_finder.py watch --queries-file --interval "$INTERVAL" --drop-pct 3 \
  --save 'out/snapshot_{query}.xlsx'
