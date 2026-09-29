#!/usr/bin/env bash
# Быстрая демонстрация: поднимает локальный демо-магазин и прогоняет несколько поисков.
# Запуск:  bash run_demo.sh
set -euo pipefail
cd "$(dirname "$0")"

PORT=8765
LOG=/tmp/pricefinder_demo.log
DB=$(mktemp -u /tmp/pricefinder_demo_XXXX.db)

echo "=== 1. Поднимаю демо-магазин на порту $PORT ==="
python3 tests/demo_server.py --port "$PORT" --quiet >"$LOG" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
sleep 2

echo
echo "=== 2. Список настроенных источников ==="
python3 price_finder.py sites | head -20

echo
echo "=== 3. Поиск: самые низкие цены на ноутбук (2 демо-площадки) ==="
python3 price_finder.py search "ноутбук" --db "$DB" --top 8 --by-site --best --force-color

echo
echo "=== 4. Поиск смартфона с исключением витринных образцов и выгрузкой в файлы ==="
python3 price_finder.py search "смартфон iphone" --db "$DB" --top 6 \
    --exclude "витринный" --in-stock \
    --csv demo_prices.csv --xlsx demo_prices.xlsx --html demo_report.html --force-color

echo
echo "=== 5. Мониторинг: один прогон с порогом цены ==="
python3 price_finder.py watch "шуруповёрт" --sites demo --once --target-price 4000 \
    --drop-pct 3 --db "$DB" --force-color

echo
echo "=== 6. История цен ==="
python3 price_finder.py history --db "$DB" --force-color

echo
echo "Готово. Файлы: out/demo_prices.csv, out/demo_prices.xlsx, out/demo_report.html, БД: $DB"
