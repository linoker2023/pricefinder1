#!/usr/bin/env bash
# ============================================================
#  Мониторинг цен по расписанию в Termux (без постоянно открытого окна)
#  Запуск:  bash android/setup_termux_job.sh [период]
#           bash android/setup_termux_job.sh 30m
#           bash android/setup_termux_job.sh 2h
#  Отключить: bash android/setup_termux_job.sh --cancel
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

PERIOD="${1:-30m}"
PROJECT_DIR="$(pwd)"
JOB_SCRIPT="${PROJECT_DIR}/android/watch_once.sh"

if ! command -v termux-job-scheduler >/dev/null 2>&1; then
  cat <<'EOF'
[!] termux-job-scheduler не найден.

Установите:
  1) приложение «Termux:API» из F-Droid (не из Google Play — там устаревшая версия);
  2) в Termux:  pkg install termux-api

Альтернатива без Termux:API — держать окно Termux открытым и запустить:
  python price_finder.py watch --queries-file --interval 30m
EOF
  exit 1
fi

if [ "$PERIOD" = "--cancel" ] || [ "$PERIOD" = "cancel" ]; then
  termux-job-scheduler --cancel-all
  echo "Все задания планировщика отменены."
  exit 0
fi

# превращаем «30m» / «2h» / «1d» в миллисекунды
value="$(echo "$PERIOD" | tr -dc '0-9.')"
unit="$(echo "$PERIOD" | tr -dc 'smhd')"
case "$unit" in
  s) ms=1000 ;;
  h) ms=3600000 ;;
  d) ms=86400000 ;;
  *) ms=60000 ;;
esac
period_ms="$(python -c "print(int(float('${value:-30}') * ${ms}))" 2>/dev/null || echo 1800000)"
if [ "$period_ms" -lt 900000 ]; then
  echo "[i] Termux ограничивает период 15 минутами — ставлю 900000 мс (15 мин)."
  period_ms=900000
fi

termux-job-scheduler \
  --period-ms "$period_ms" \
  --network any \
  --battery-not-low true \
  --script "$JOB_SCRIPT"

echo "Задание создано: каждые $((period_ms / 60000)) мин будет запускаться android/watch_once.sh"
echo "Лог: ~/pricefinder/watch.log"
echo
termux-job-scheduler --pending || true
cat <<'EOF'

Проверка и управление:
  bash android/watch_once.sh                 # прогнать один цикл сейчас
  tail -f ~/pricefinder/watch.log            # смотреть лог
  termux-job-scheduler --pending             # список заданий
  bash android/setup_termux_job.sh --cancel  # отключить

Важно для Android 12+:
  • Настройки → Приложения → Termux → Батарея → «Без ограничений»;
  • отключите «экономный режим» для Termux, иначе система убьёт задание;
  • уведомления придут, если установлен Termux:API (см. android/ANDROID.md).
EOF
