#!/usr/bin/env bash
# ============================================================
#  Быстрый запуск pricefinder в Termux.
#  Скопируйте в ~/start.sh или добавьте ярлык через Termux:Widget.
#
#  Использование:
#    bash android/termux_start.sh                 # интерактивное меню
#    bash android/termux_start.sh search "товар"  # сразу поиск
#    bash android/termux_start.sh watch           # мониторинг списка
#    bash android/termux_start.sh gui             # графический интерфейс
# ============================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PY=python
[ -x .venv/bin/python ] && PY=.venv/bin/python
[ -d .venv ] && . .venv/bin/activate 2>/dev/null

ACTION="${1:-menu}"
shift || true

case "$ACTION" in
  search)
    if [ "$#" -gt 0 ]; then
      $PY price_finder.py search "$*"
    else
      $PY price_finder.py search --queries-file
    fi
    ;;
  watch)
    command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
    $PY price_finder.py watch --queries-file --interval "${1:-30m}" --drop-pct "${2:-3}"
    command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock
    ;;
  job)
    bash android/setup_termux_job.sh "${1:-30m}"
    ;;
  history)
    $PY price_finder.py history --limit "${1:-20}"
    ;;
  gui)
    if ! $PY -c "import kivy" >/dev/null 2>&1; then
      echo "[i] kivy не установлен — запускаю установку: bash android/install_gui_termux.sh"
      bash android/install_gui_termux.sh || exit 1
    fi
    if [ -z "${DISPLAY:-}" ]; then
      command -v termux-x11 >/dev/null 2>&1 || {
        echo "[!] Не установлен Termux:X11 (нужен для окна). Возьмите его из F-Droid."
        echo "    А пока доступен текстовый режим: bash android/termux_start.sh search \"товар\""
        exit 1
      }
      termux-x11 :1 -ac >/dev/null 2>&1 &
      sleep 2
      export DISPLAY=:1
    fi
    $PY price_finder.py gui
    ;;
  env)
    $PY price_finder.py env
    ;;
  sites)
    $PY price_finder.py sites
    ;;
  menu|*)
    cat <<EOF

  pricefinder на Android — что запустить?

    1) Найти цены по одному товару
    2) Найти цены по списку queries.txt
    3) Править список товаров (nano queries.txt)
    4) Мониторинг (Termux открыт)
    5) Мониторинг по расписанию (termux-job-scheduler)
    6) История цен
    7) Графический интерфейс (нужен Termux:X11)
    8) Список площадок
    9) Диагностика окружения

EOF
    read -r -p "  Ваш выбор [1-9]: " choice
    case "$choice" in
      1) read -r -p "  Товар: " query; $PY price_finder.py search "$query" ;;
      2) $PY price_finder.py search --queries-file ;;
      3) [ -f queries.txt ] || $PY price_finder.py init-queries
         command -v nano >/dev/null 2>&1 && nano queries.txt || $PY -c "print(open('queries.txt',encoding='utf-8').read())" ;;
      4) bash android/termux_start.sh watch ;;
      5) bash android/termux_start.sh job ;;
      6) bash android/termux_start.sh history ;;
      7) bash android/termux_start.sh gui ;;
      8) bash android/termux_start.sh sites ;;
      9) bash android/termux_start.sh env ;;
      *) echo "  Ничего не выбрано" ;;
    esac
    ;;
esac
