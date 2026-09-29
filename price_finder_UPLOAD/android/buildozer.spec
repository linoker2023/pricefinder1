# ============================================================
#  buildozer.spec — сборка pricefinder в APK для Android
#  Сборка: bash android/build_apk.sh   (нужен Linux + Docker)
# ============================================================

[app]
title = Цены — поиск самых низких
package.name = pricefinder
package.domain = org.pricefinder

# Точка входа: gui_app.py обязан создавать App() и вызывать .run()
source.main = gui_app.py
source.dir = .
source.include_exts = py,yaml,yml,txt
source.include_patterns = config/sites.yaml,config/sites.template.yaml,queries.txt,pricefinder/*.py

# Что НЕ паковать
source.exclude_exts = spec,bat,sh,pyc,md,log,db
source.exclude_patterns = .venv/*,.venv-build/*,out/*,bin/*,.buildozer/*,__pycache__/*,*/__pycache__/*,.git/*,.github/*,_*.py,tests/*,android/*.sh,*.keystore

version = 1.0.0

# --- зависимости ------------------------------------------------------------
# Минимальный набор: requests + beautifulsoup4.
# НЕ нужны: отдельная YAML-библиотека (есть встроенный парсер pricefinder/yamlite.py),
#           lxml (без него работает html.parser — зато сборка в разы надёжнее),
#           openpyxl (Excel-отчёты в APK не выгружаются).
# Если хотите ускорить парсинг HTML — допишите lxml в конец списка,
# но сборка станет дольше и капризнее.
requirements = python3,kivy==2.3.1,requests,beautifulsoup4,charset-normalizer,idna,urllib3,certifi,soupsieve,typing_extensions

# --- разрешения -------------------------------------------------------------
# INTERNET — обязателен (запросы к сайтам). Остальное — по желанию.
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WAKE_LOCK,VIBRATE,FOREGROUND_SERVICE,RECEIVE_BOOT_COMPLETED

android.api = 33
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True

# --- внешний вид ------------------------------------------------------------
orientation = portrait
fullscreen = False

# Иконка и заставка: положите свои PNG в android/ и укажите пути
# icon.filename = android/icon.png
# splash.filename = android/splash.png

# --- поведение --------------------------------------------------------------
# Не выгружать приложение при сворачивании (важно для мониторинга цен)
android.allow_backup = True
android.wakelock = True

# Логирование kivy — включите на время отладки
android.release_artifact = apk
# android.log_level = 2
# presplash.color = "#10131A"

# --- сборка -----------------------------------------------------------------
# Если ставите kivy на хосте вручную — оставьте пустым;
# при сборке в Docker (build_apk.sh) всё ставится автоматически.
p4a.branch = develop
p4a.fork = kivy

# Для фоновой службы (уведомления о ценах, когда приложение закрыто):
# android.services = watcher:android/watcher_service.py
# (заготовка описана в android/ANDROID.md, раздел «Фоновая служба»)

# --- ввод -------------------------------------------------------------------
android.input_connection = SDLInputConnection
android.embedded_keyboard = False

# --- подпись ----------------------------------------------------------------
# Для отладки buildozer подпишет debug-ключом. Для публикации в Google Play
# создайте свой ключ и укажите его в release-профиле (см. ANDROID.md).

[buildozer]
log_level = 2
warn_on_root = True
