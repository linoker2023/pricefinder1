#!/usr/bin/env bash
# ============================================================
#  Один цикл мониторинга — его запускает планировщик Termux
#  (termux-job-scheduler) или cron. Ручной запуск:
#      bash android/watch_once.sh
# ============================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

LOG="${LOG:-$HOME/pricefinder/watch.log}"
mkdir -p "$(dirname "$LOG")"

PY=python
[ -x .venv/bin/python ] && PY=.venv/bin/python

# не даём процессору уснуть на время проверки (нужен termux-wake-lock из Termux:API)
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
  if [ -f queries.txt ]; then
    $PY price_finder.py watch --queries-file --once --drop-pct "${DROP_PCT:-3}"
  else
    echo "queries.txt не найден — создайте список товаров:"
    echo "  $PY price_finder.py init-queries"
  fi
} >> "$LOG" 2>&1

command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock

# держим лог в разумных пределах
if [ -f "$LOG" ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
