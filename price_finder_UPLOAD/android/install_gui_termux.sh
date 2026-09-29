#!/usr/bin/env bash
# ============================================================
#  Графический интерфейс pricefinder в Termux (Kivy + Termux:X11)
#  Запуск:  bash android/install_gui_termux.sh
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

if [ -z "${PREFIX:-}" ]; then
  echo "[!] Запускайте внутри Termux."
  exit 1
fi

[ -d .venv ] && . .venv/bin/activate

echo "[1/4] Системные библиотеки для графики"
pkg install -y termux-x11-nightly || pkg install -y termux-x11 || \
  echo "    (termux-x11 не установился — возьмите его из F-Droid: «Termux:X11»)"
pkg install -y python libffi-devel sdl2-devel sdl2_image-devel sdl2_mixer-devel sdl2_ttf-devel \
              libjpeg-turbo-devel pkg-config xorg-utils || true

echo "[2/4] Ставлю kivy"
export LDFLAGS="-L${PREFIX}/lib"
export CPPFLAGS="-I${PREFIX}/include"
pip install --upgrade pip wheel cython >/dev/null
pip install kivy || {
  echo "[!] kivy из pip не собрался. Альтернатива:"
  echo "      pkg install python-kivy   (репозиторий termux-user-repository)"
  exit 1
}

echo "[3/4] Проверка логики интерфейса (без окна)"
python gui_app.py --selftest || true

echo "[4/4] Как запускать"
cat <<'EOF'

============================================================
 Запуск графического интерфейса в Termux:

   # 1. включите «Termux:X11» (приложение должно быть установлено)
   termux-x11 :1 -ac &
   export DISPLAY=:1

   # 2. запустите интерфейс
   cd ~/price_finder && source .venv/bin/activate
   python price_finder.py gui

 Чтобы не сворачивалось и не засыпало:
   termux-wake-lock
   (отключить: termux-wake-unlock)

 Если окно не появляется — проверьте, что DISPLAY=:1 и Termux:X11 запущен.
 Текстовый режим работает всегда: python price_finder.py search "товар"
============================================================
EOF
