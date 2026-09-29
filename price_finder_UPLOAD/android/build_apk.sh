#!/usr/bin/env bash
# ============================================================
#  Сборка APK pricefinder (нужен Linux; Android SDK/NDK ставит Docker)
#
#  bash android/build_apk.sh            # debug-APK
#  bash android/build_apk.sh release    # release-APK (нужна своя подпись)
#  bash android/build_apk.sh --local    # без Docker (buildozer на хосте)
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

MODE="${1:-debug}"
PROJECT_DIR="$(pwd)"

if [ ! -f android/buildozer.spec ]; then
  echo "[!] Не найден android/buildozer.spec"
  exit 1
fi
cp android/buildozer.spec ./buildozer.spec
trap 'rm -f buildozer.spec' EXIT

# --- вариант 1: Docker (рекомендуется) --------------------------------------
if [ "$MODE" != "--local" ] && command -v docker >/dev/null 2>&1; then
  echo "[i] Собираю в контейнере (первый запуск качает ~5 ГБ и занимает 30–90 минут)"
  docker run --rm -it \
    -v "${PROJECT_DIR}:/home/user/project" \
    -v pricefinder_buildozer_cache:/home/user/.buildozer \
    -w /home/user/project \
    ubuntu:22.04 bash -lc '
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y -qq --no-install-recommends \
        git zip unzip python3 python3-pip python3-venv openjdk-17-jdk \
        autoconf automake libtool libltdl-dev libffi-dev libssl-dev \
        build-essential cmake pkg-config zlib1g-dev
      pip3 install --break-system-packages --upgrade pip wheel
      pip3 install --break-system-packages buildozer cython==0.29.36
      cd /home/user/project
      buildozer android debug || buildozer android release
    '
  echo
  echo "[✓] Готово. APK лежит в bin/"
  ls -lh bin/*.apk 2>/dev/null || true
  exit 0
fi

# --- вариант 2: buildozer на хосте ------------------------------------------
if [ "$MODE" = "--local" ] || ! command -v docker >/dev/null 2>&1; then
  if ! command -v buildozer >/dev/null 2>&1; then
    echo "[i] Устанавливаю buildozer в виртуальное окружение .venv-build"
    python3 -m venv .venv-build
    # shellcheck disable=SC1091
    . .venv-build/bin/activate
    pip install --upgrade pip wheel
    pip install buildozer "cython==0.29.36"
  else
    command -v python3 >/dev/null && true
  fi

  echo "[i] Понадобятся (Ubuntu/Debian):"
  echo "      sudo apt install git zip unzip openjdk-17-jdk autoconf libtool libffi-dev libssl-dev build-essential cmake pkg-config zlib1g-dev"
  echo "[i] Первая сборка качает Android SDK/NDK (~5 ГБ) и идёт 30–90 минут."
  read -r -p "Продолжить? [y/N] " answer
  case "$answer" in
    y|Y|yes) ;;
    *) echo "Отменено"; exit 1 ;;
  esac

  if [ "$MODE" = "release" ]; then
    buildozer android release
  else
    buildozer android debug
  fi
  echo
  echo "[✓] APK в bin/:"
  ls -lh bin/*.apk 2>/dev/null || true
fi
