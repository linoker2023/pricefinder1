# pricefinder на Android

Программа работает на телефоне четырьмя способами. Выберите один — они не мешают друг другу.

| Способ | Что получаете | Сложность | Кому подходит |
|---|---|---|---|
| **A. Termux (консоль)** | весь функционал: поиск, мониторинг, история, отчёты | ★☆☆ | быстро начать, надёжнее всего |
| **B. Termux + графика** | сенсорный интерфейс (кнопки, вкладки) | ★★☆ | тем, кто не любит терминал |
| **C. Pydroid 3** | запуск `.py` в приложении-IDE | ★★☆ | без Termux, разовые проверки |
| **D. Свой APK** | обычное приложение с иконкой | ★★★ | «поставил и забыл», можно раздать друзьям. Готового файла нет — сборка за 20–40 мин в облаке GitHub, см. [APK.md](../APK.md) |

---

## A. Termux — консольный режим (рекомендую начать с него)

### A.1. Установить Termux

Берите **из F-Droid** или GitHub — версия в Google Play устарела и не обновляется:

* F-Droid: <https://f-droid.org/packages/com.termux/>
* GitHub: <https://github.com/termux/termux-app/releases>

### A.2. Скопировать программу на телефон

**Вариант 1 — через git** (если код в репозитории):

```bash
pkg install git
git clone <адрес_репозитория> ~/price_finder
cd ~/price_finder
```

**Вариант 2 — из памяти телефона.** Соберите папку `price_finder` в ZIP, скопируйте
в «Загрузки», затем:

```bash
pkg install unzip
termux-setup-storage          # разрешить Termux доступ к памяти (появится запрос)
cp /sdcard/Download/price_finder.zip ~/
cd ~ && unzip price_finder.zip
cd ~/price_finder
```

**Вариант 3 — с компьютера по USB/Wi‑Fi:** положите ZIP в `Download` и сделайте как в варианте 2.

### A.3. Установить зависимости

```bash
cd ~/price_finder
bash android/install_termux.sh
```

Скрипт поставит Python, `requests`, `beautifulsoup4` и (по возможности) `lxml`,
`PyYAML`, `openpyxl`. **lxml и PyYAML необязательны**: без lxml используется
встроенный `html.parser`, а вместо PyYAML — собственный мини-парсер
`pricefinder/yamlite.py` (он разбирает наш конфиг один в один как PyYAML).

### A.4. Проверить установку

```bash
source .venv/bin/activate
python price_finder.py env          # платформа, пути, какие библиотеки есть
python price_finder.py --version
```

### A.5. Где указывать товар

**Способ 1 — прямо в команде:**

```bash
python price_finder.py search "iphone 15 128gb"
python price_finder.py search "шуруповёрт bosch" --top 30 --by-site --best
python price_finder.py search "корм для кошек" --exclude "б/у" --max-price 3000
```

**Способ 2 — список товаров в `queries.txt`** (главный способ для телефона):

```bash
python price_finder.py init-queries     # создать файл с подсказками
nano queries.txt                        # править в Termux
```

Формат строки: `товар ; желаемая цена ; падение в % ; сайты через запятую`

```text
iphone 15 128gb ; 60000
ноутбук asus vivobook 15 ; 45000 ; 5
кофемашина delonghi ; 25000 ; 7 ; bookvoed
робот-пылесос xiaomi
```

Запуск по всему списку:

```bash
python price_finder.py search --queries-file
python price_finder.py search --queries-file --save out/prices.csv
```

Править `queries.txt` удобнее не в Termux, а в любом текстовом редакторе Android
(Acode, Quoda) — файл лежит в `/data/data/com.termux/files/home/price_finder/queries.txt`.
Можно также включить доступ к памяти (`termux-setup-storage`) и держать список в
`/sdcard/Documents/queries.txt`, запуская так:

```bash
python price_finder.py search -f /sdcard/Documents/queries.txt
```

### A.6. Мониторинг цен

**Пока Termux открыт:**

```bash
termux-wake-lock                                    # не давать телефону уснуть
python price_finder.py watch --queries-file --interval 30m --drop-pct 3
# остановить: Ctrl+C (в Termux — кнопка «VOL DOWN + Q» или долгое нажатие → Ctrl+C)
termux-wake-unlock
```

**По расписанию, даже когда Termux закрыт** (нужен Termux:API, см. раздел D.3):

```bash
bash android/setup_termux_job.sh 30m      # каждые 30 минут
bash android/setup_termux_job.sh --cancel # отключить
tail -f ~/pricefinder/watch.log           # смотреть журнал
bash android/watch_once.sh                # прогнать один цикл вручную
```

Android ограничивает период планировщика 15 минутами и может отложить запуск
при разряженной батарее — это нормально.

**Обязательно для Android 12+:** Настройки → Приложения → Termux → Батарея →
«Без ограничений», иначе система убивает фоновые задания.

### A.7. Уведомления

| Канал | Как включить |
|---|---|
| **Шторка Android** | приложение **Termux:API** из F-Droid + `pkg install termux-api` |
| **Telegram** | `settings.telegram.bot_token` и `chat_id` в `config/sites.yaml` |
| **E-mail** | `settings.smtp.*` в `config/sites.yaml` |

Проверка всех каналов:

```bash
python price_finder.py notify-test
```

### A.8. Отчёты и файлы

По умолчанию всё сохраняется в `~/price_finder/out/`. Чтобы открыть файл в другом
приложении:

```bash
termux-setup-storage
cp out/prices.csv /sdcard/Download/       # дальше откроете из «Загрузок»
termux-share out/prices.csv               # сразу отправить в Telegram/почту
```

Пути можно переназначить переменными окружения:

```bash
export PRICEFINDER_HOME=/sdcard/Documents/pricefinder     # база, конфиг и отчёты
export PRICEFINDER_DB=$PRICEFINDER_HOME/prices.db
```

---

## B. Termux + графический интерфейс

```bash
bash android/install_gui_termux.sh        # поставит SDL2-библиотеки и kivy
```

Запуск (нужно приложение **Termux:X11** из F-Droid):

```bash
termux-x11 :1 -ac &
export DISPLAY=:1
cd ~/price_finder && source .venv/bin/activate
python price_finder.py gui
```

Что есть в интерфейсе:

| Вкладка | Назначение |
|---|---|
| **Поиск** | поле «товар» → кнопка «Найти цены»; результат — список от дешёвого к дорогому, кнопка «Открыть» ведёт в браузер |
| **Список** | редактор `queries.txt`: «Сохранить», «Найти по всем», «Следить» |
| **Слежка** | запуск/остановка мониторинга, журнал срабатываний (🔔 — цена упала) |
| **История** | минимум/максимум, график-спарклайн по каждому товару |
| **Сайты** | галочки: какие площадки участвуют; кнопка «Диагностика сайта» |
| **Настройки** | число результатов, страницы, ценовой коридор, чёрный список слов, задержка, JS-рендер, курсы, период мониторинга, wakelock |

Проверка логики интерфейса без окна (полезно, если графика не поднялась):

```bash
python gui_app.py --selftest
```

Если kivy не собрался — ничего страшного, консольный режим (раздел A) даёт тот же
функционал.

---

## C. Pydroid 3 (без Termux)

1. Установите **Pydroid 3** (Play Store) и плагин **Pydroid repository plugin**.
2. Меню → `Pip` → вкладка `Install` → поставьте `requests` и `beautifulsoup4`
   (остальное необязательно: программа работает без lxml, PyYAML и openpyxl).
3. Скопируйте папку `price_finder` в память телефона, например в `Documents`.
4. В Pydroid: `Open` → выберите `price_finder/price_finder.py`.
5. В окне терминала Pydroid (`Terminal`) выполните:

```bash
cd /sdcard/Documents/price_finder
python price_finder.py env
python price_finder.py search "iphone 15"
```

Особенности Pydroid:

* рабочая папка доступна на запись, поэтому база и отчёты создаются рядом с программой;
* GUI (kivy) в Pydroid тоже ставится через Pip, но стабильность ниже, чем в Termux;
* планировщика нет — мониторинг только пока открыто приложение.

---

## D. Собрать APK (обычное приложение с иконкой)

> **Готового APK для скачивания нет — его нужно собрать.** Самый простой способ
> не требует ни компьютера, ни программ: загрузите проект на GitHub и нажмите
> «Run workflow» — облачный сборщик отдаст готовый `.apk` через 20–40 минут.
> Пошагово с картинками-пояснениями: **[../APK.md](../APK.md)**.
> Ниже — вариант для своего компьютера с Linux/WSL.

### D.1. Что нужно

* **компьютер с Linux** (или WSL2) — на самом Android собрать APK нельзя;
* Docker (проще всего) либо вручную: JDK 17, Android SDK/NDK, buildozer;
* 10–15 ГБ места и 30–90 минут на первую сборку.

### D.2. Сборка

```bash
cd price_finder
bash android/build_apk.sh            # debug-APK в контейнере (SDK/NDK ставятся сами)
bash android/build_apk.sh release    # release-вариант
bash android/build_apk.sh --local    # без Docker, buildozer на хосте
```

Готовый файл появится в `bin/pricefinder-1.0.0-...apk` — скопируйте его на телефон
и разрешите установку из неизвестных источников.

Что уже настроено в `android/buildozer.spec`:

* точка входа `gui_app.py` (приложение сразу открывает сенсорный интерфейс);
* зависимости: `python3, kivy, requests, beautifulsoup4, lxml` — **PyYAML не нужен**;
* разрешения: `INTERNET`, `ACCESS_NETWORK_STATE`, `WAKE_LOCK`, `VIBRATE`,
  `FOREGROUND_SERVICE`, `RECEIVE_BOOT_COMPLETED`;
* `android.wakelock = True` — приложение не выгружается при сворачивании.

Своя иконка: положите `icon.png` (512×512) в `android/` и раскомментируйте строку
`icon.filename` в `buildozer.spec`.

Публикация в Google Play: подпишите release-сборку своим ключом
(`keytool -genkey -v -keystore pricefinder.keystore -alias pricefinder -keyalg RSA -keysize 2048 -validity 10000`),
затем в `buildozer.spec` укажите `release.artifact` и параметры подписи, либо
подпишите готовый APK через `apksigner`.

### D.3. Уведомления в шторке

Внутри APK системные уведомления идут через `plyer`/`android` API; в текущей сборке
используются Telegram и e-mail (работают везде) — заполните их в `config/sites.yaml`.
Если вы используете Termux, то `Termux:API` даёт нативные уведомления без APK:

```bash
pkg install termux-api     # + приложение «Termux:API» из F-Droid
```

### D.4. Фоновая служба (необязательно, для продвинутых)

Чтобы цены проверялись, когда приложение закрыто, в `buildozer.spec` есть строка

```
# android.services = watcher:android/watcher_service.py
```

Реализация службы — это отдельный небольшой файл на `pyjnius` с
`startForeground()` и периодическим вызовом `pricefinder.gui_logic.run_search`.
Проще тот же результат даёт вариант A.6 (`termux-job-scheduler`) — без сборки APK.

---

## E. Что на Android работает, а что нет

| Возможность | Android | Комментарий |
|---|---|---|
| Поиск цен, фильтры, сортировка | ✅ | полностью |
| Список товаров `queries.txt` | ✅ | удобно править в любом редакторе |
| История цен в SQLite | ✅ | база в `~/pricefinder/` или `PRICEFINDER_HOME` |
| Мониторинг `watch` | ✅ | пока Termux открыт |
| Мониторинг по расписанию | ✅ | `termux-job-scheduler` (нужен Termux:API) |
| Уведомления Telegram / e-mail | ✅ | работают везде |
| Уведомления в шторке | ✅ в Termux | нужен Termux:API |
| Отчёты CSV / JSON / HTML | ✅ | открываются в браузере/таблицах Android |
| Отчёты XLSX | ⚠️ | нужен `openpyxl` (в Termux ставится, в Pydroid — как повезёт) |
| JS-рендер сайтов (Playwright) | ❌ | Chromium для Android через Playwright не ставится — используйте сайты с серверной выдачей (например `bookvoed`) или компьютер |
| Сборка APK | ❌ на телефоне | только Linux/WSL |

Из-за отсутствия JS-рендера на телефоне крупные маркетплейсы (Ozon, WB, Яндекс.Маркет)
чаще всего не отдают данные — им нужен браузер. Что реально работает без браузера:
сайты с серверной вёрсткой и микроразметкой JSON‑LD/microdata (книжные, магазины
электроники с SSR, зарубежные площадки без жёсткой антибот-защиты). Проверяйте любую
площадку командой:

```bash
python price_finder.py test-site <id> "запрос"
```

---

## F. Быстрая шпаргалка для Termux

```bash
cd ~/price_finder && source .venv/bin/activate    # начало работы

python price_finder.py env                        # диагностика
python price_finder.py sites                      # какие площадки настроены
python price_finder.py init-queries               # создать список товаров
nano queries.txt                                  # вписать свои товары

python price_finder.py search "товар"             # один товар
python price_finder.py search --queries-file      # весь список
python price_finder.py history --limit 20         # что было с ценами

termux-wake-lock
python price_finder.py watch --queries-file -i 30m --drop-pct 3
# Ctrl+C, затем:
termux-wake-unlock

bash android/setup_termux_job.sh 30m              # мониторинг по расписанию
python price_finder.py notify-test                # проверка уведомлений
python gui_app.py --selftest                      # проверка логики GUI
```

---

## G. Если не получается

| Симптом | Решение |
|---|---|
| `pkg: command not found` | вы не в Termux, а в другом терминале Android |
| `python: not found` | `pkg install python` |
| `ModuleNotFoundError: requests` | `source .venv/bin/activate`, затем `pip install requests beautifulsoup4` |
| `pip` падает при сборке lxml | пропустите lxml — программа работает на `html.parser` (см. `python price_finder.py env`) |
| Не читается конфиг | `PRICEFINDER_YAMLITE=1 python price_finder.py sites` — встроенный парсер YAML |
| `Read-only file system` при сохранении | задайте `export PRICEFINDER_HOME=$HOME/pricefinder` |
| HTTP 403/429 от маркетплейса | на телефоне не лечится (нет браузера) — перенесите этот источник на ПК |
| Мониторинг останавливается через несколько минут | включите wakelock и «Батарея → Без ограничений» для Termux |
| kivy не устанавливается | используйте консольный режим (раздел A) — он полностью функционален |
