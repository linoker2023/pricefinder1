# pricefinder — поиск самых низких цен на товар

Универсальная программа на Python: ищет товар по **любому сайту**, вытаскивает цены,
сортирует от дешёвых к дорогим, показывает разброс, ведёт историю цен и присылает
уведомление, когда цена падает.

Сайты описываются в `config/sites.yaml`. Если селекторы не заданы — программа сама
находит карточки товаров по микроразметке **JSON‑LD (schema.org)**, **microdata (itemprop)**
или **meta-тегам (og:/product:)**, поэтому многие магазины работают «из коробки».

Работает на **компьютере и на Android** (Termux / Pydroid 3 / собранный APK):
есть консольный режим и сенсорный интерфейс на Kivy. Подробности —
**[android/ANDROID.md](android/ANDROID.md)**, пошаговая инструкция —
**[ИНСТРУКЦИЯ.md](ИНСТРУКЦИЯ.md)**.

```
  Самые низкие цены: «гарри поттер»
  Предложений: 8 · минимум 339 ₽ · медиана 473,50 ₽ · разброс 120.9%

№              Цена       Выгода   Товар                        Площадка          Ссылка
──────────────────────────────────────────────────────────────────────────────────────────
1.               339 ₽         −28%   Раскрашиваем мир Гарри По…   Буквоед           bookvoed.ru/product/raskrashivaem…
2.               370 ₽         −22%   Harry Potter and the Cham…   Буквоед           bookvoed.ru/product/harry-potter-…
3.               468 ₽          −1%   Гарри Поттер. Большая кни…   Буквоед           bookvoed.ru/product/garri-potter-…
```

---

## 1. Установка

Нужен Python 3.10+ (проверено на 3.11).

```bash
cd price_finder
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Опционально — браузерный движок для сайтов, которые рисуют цены через JavaScript:

```bash
pip install playwright && playwright install chromium
```

## 2. Быстрый старт (проверка без интернета)

В комплекте локальный демо-магазин и два демо-источника (`demo`, `demo2`):

```bash
# терминал 1 — поднимаем демо-магазин
python price_finder.py serve-demo          # или: python tests/demo_server.py

# терминал 2 — ищем
python price_finder.py search "ноутбук"
python price_finder.py search "смартфон iphone" --by-site --best --top 30
python price_finder.py search "кофемашина" --xlsx out/prices.xlsx --html out/report.html
```

Реальный сайт из коробки (проверено на живой выдаче: 60 карточек за один запрос,
HTTP 200 без браузера; селекторы в конфиге сняты с настоящей вёрстки):

```bash
python price_finder.py search "гарри поттер" --sites bookvoed --top 10
python price_finder.py search "детектив" --sites bookvoed --exclude "электронная" --csv books.csv
```

Другие площадки (`ozon`, `wildberries`, `yandex-market`, `aliexpress`, `dns`,
`citilink`, `avito`, `ebay`, `amazon`, `chitai-gorod`) в конфиге **выключены** —
у них агрессивная антибот-защита и/или выдача рисуется через JavaScript.
Включайте осознанно и начинайте с диагностики:

```bash
python price_finder.py test-site ozon "ssd" --dump-html ozon.html --js
```

## 3. Где указывать товар

**Способ 1 — прямо в команде:**

```bash
python price_finder.py search "iphone 15 128gb"
python price_finder.py watch "playstation 5" --interval 30m --target-price 45000
```

**Способ 2 — список товаров в `queries.txt`** (удобно править в блокноте):

```bash
python price_finder.py init-queries        # создаст файл с подсказками
```

```text
# товар ; желаемая цена ; падение в % ; сайты через запятую
iphone 15 128gb ; 60000
ноутбук asus vivobook 15 ; 45000 ; 5
кофемашина delonghi magnifica ; 25000 ; 7 ; bookvoed
наушники sony ; - ; - ; bookvoed          # прочерк = «поле не задано»
робот-пылесос xiaomi
```

```bash
python price_finder.py search --queries-file            # найти цены по всему списку
python price_finder.py watch  --queries-file -i 30m     # следить за всем списком
python price_finder.py search -f мой_список.txt         # свой файл
```

**Способ 3 — «цели» в базе** (живут между запусками):

```bash
python price_finder.py targets add "кофемашина" --target-price 25000 --drop-pct 5
python price_finder.py watch -i 2h
```

**Без терминала (Windows):** `setup.bat` → правите `queries.txt` → `search.bat` /
`watch.bat`. В Linux/macOS то же самое: `bash setup.sh`, `bash search.sh`, `bash watch.sh`.

Пошаговый разбор установки, команд, уведомлений и планировщика задач —
в файле **[ИНСТРУКЦИЯ.md](ИНСТРУКЦИЯ.md)**.

## 4. Команды

| Команда | Зачем |
|---|---|
| `search "товар"` | найти самые низкие цены (основная команда) |
| `watch "товар"` | мониторинг по расписанию + уведомления |
| `sites` | какие источники настроены и чем они парсятся |
| `test-site <id> "запрос"` | диагностика одного сайта: HTTP-код, стратегия, карточки, дамп HTML |
| `history` | история цен из БД: минимум/максимум, динамика, спарклайн |
| `targets add/list/remove` | список товаров для мониторинга с порогом цены |
| `parse-price "текст"` | проверить, как распознаётся цена из строки |
| `update-rates` | скачать/записать живые курсы валют |
| `init-config` | создать конфиг из шаблона |
| `gui` | сенсорный интерфейс (Android/ПК, нужен kivy); `gui --selftest` — проверка без окна |
| `env` | диагностика: платформа, пути, установленные библиотеки |
| `notify-test` | проверить уведомления (шторка Android / Telegram / e-mail) |
| `init-queries` | создать `queries.txt` — список товаров |
| `serve-demo` | запустить локальный демо-магазин |

### search — основные флаги

```bash
python price_finder.py search "шуруповёрт 18в" \
    --sites demo,bookvoed \      # источники (по умолчанию все enabled: true)
    --all-sites \                # взять вообще все сайты из конфига
    --top 30 \                   # сколько строк показать
    --pages 2 \                  # сколько страниц выдачи обойти
    --per-site 60 \              # максимум карточек с одного сайта
    --min-price 500 --max-price 30000 \
    --max-ratio 1.6 \            # отбросить всё дороже «минимум × 1.6»
    --exclude "б/у" "витрина" \  # исключить мусор
    --include "bosch" \          # оставить только нужное
    --require-keyword \          # в названии обязаны быть слова из запроса
    --in-stock \                 # только товары в наличии
    --by-site --best \           # сводка по площадкам + подробности о лиде
    --update-rates \             # живые курсы валют (цены в $ / € пересчитаются)
    --js \                       # принудительно рендерить страницы в браузере
    --csv out/p.csv --xlsx out/p.xlsx --json out/p.json --html out/p.html
```

Результат сортируется по цене в **базовой валюте** (`settings.currencies.base`),
поэтому предложения в ₽, $ и € сравниваются корректно.

По умолчанию результаты пишутся в `price_finder.db` — это основа для `history` и `watch`.
Отключается флагом `--no-history`. Одинаковые товары с одинаковой ценой на разных
площадках схлопываются в одну строку (`Площадка +1`); отключается `--no-merge`.

### watch — мониторинг и уведомления

```bash
# каждые 30 минут, уведомить при цене ниже 45 000 ₽ или падении на 5% за шаг
python price_finder.py watch "playstation 5" --interval 30m --target-price 45000 --drop-pct 5

# один прогон (для cron/systemd/Планировщика задач)
python price_finder.py watch "кофемашина" --once --target-price 25000

# следить за всеми целями из БД
python price_finder.py targets add "кофемашина" --target-price 25000 --drop-pct 5
python price_finder.py targets add "пылесос" --sites bookvoed --target-price 20000
python price_finder.py watch --interval 2h
```

Типы срабатываний:
* **цена ниже цели** (`--target-price`);
* **исторический минимум** — цена ниже всех ранее наблюденных;
* **падение на N% за шаг** (`--drop-pct`).

Повторы подавляются: одно и то же событие не шлётся дважды, а «цена ниже цели» —
не чаще раза в `--alert-cooldown` часов (по умолчанию 6).

### history — что было с ценой

```bash
python price_finder.py history --limit 20
python price_finder.py history --filter iphone --points 60
```

```
  История цен (2 позиций)
  Шуруповёрт Интерскол ДА-10/12М2
     ДемоМаркет  сейчас: 2 966 ₽   мин: 2 966 ₽   макс: 3 490 ₽   точек: 2   -15.0%
     █▁  uid=3a7b7727574775d8
     http://127.0.0.1:8765/product/12
```

## 5. Как подключить свой сайт

Откройте `config/sites.yaml`, скопируйте блок `my-shop` и заполните:

```yaml
  - id: myshop
    name: Мой магазин
    enabled: true
    search_url: "https://myshop.ru/search?q={query}&sort=price&page={page}"
    product_selector: "div.product-card"       # контейнер одной карточки
    fields:
      title: ".product-card__title"
      price: ".product-card__price"
      old_price: "max:.price-old"
      url: "a.product-card__link"              # автоматически возьмёт href
      image: "img.product-card__img"            # автоматически возьмёт src
      seller: ".seller"
      rating: ".rating"
      availability: ".stock"
    currency: RUB
    max_pages: 2
    delay: 1.5
    min_price: 10
    exclude_keywords: ["б/у", "витрина"]
    js_render: false                            # true, если контент грузит JS
```

**Если не указывать `product_selector` и `fields` вообще** — программа попробует
JSON‑LD, microdata и meta-теги. Для многих магазинов этого достаточно.

Проверка без лишней возни:

```bash
python price_finder.py test-site myshop "запрос" --sample 5 --dump-html page.html
```

Вывод покажет HTTP-код, размер ответа, сработавшую стратегию и первые карточки.
Если `HTTP 403/429` — сайт видит бота; если «карточки не распознаны» — не те селекторы
или нужен `js_render: true`.

### Форматы значений в `fields`

| Запись | Что делает |
|---|---|
| `".title"` | текст первого подходящего элемента |
| `["h3.title", ".name"]` | список: берётся первый непустой вариант |
| `"attr:data-price"` | значение атрибута (у контейнера или потомка) |
| `"regex:(\\d[\\d\\s]{2,})\\s*₽"` | регулярка по тексту контейнера (группа 1) |
| `"json:window.__STATE__"` | JSON из `<script>` (для SPA: Ozon, WB и т.п.) |
| `"min:.price"`, `"max:.price"`, `"first:.price"` | как выбрать значение, если элементов несколько |
| `"a.link"` для `url` | автоматически берётся `href` (и делается абсолютным) |
| `"img"` для `image` | автоматически берётся `src` / `data-src` / `srcset` |

Без префикса для поля `price` берётся **минимальное** число среди найденных
(так отсекается зачёркнутая старая цена), для `old_price` удобнее `max:`.

### Все параметры сайта

`id, name, enabled, search_url, sort_by_price_url, static, method (GET/POST/JSON),
post_data, query_param, page_param, start_page, max_pages, product_selector, fields,
currency, currency_selector, js_render, render_wait, wait_selector, delay, headers,
cookies, proxy (глобально в settings), min_price, max_price, include_keywords,
exclude_keywords, notes`

В `search_url` подставляются `{query}` (URL-encoded запрос) и `{page}`.
Если `{page}` в шаблоне нет, номер страницы добавляется параметром `page_param`.

## 6. Настройки (`settings` в конфиге)

```yaml
settings:
  timeout: 20          # таймаут запроса
  retries: 3           # повторы при 403/429/сбоях (с ротацией User-Agent)
  delay: 1.0           # вежливая пауза между запросами
  respect_robots: true # учитывать robots.txt (обход: --ignore-robots)
  workers: 4           # параллельный опрос сайтов
  # user_agent: "..."
  # proxy: "http://127.0.0.1:8080"
  currencies:
    base: RUB
    rates: {USD: 92.0, EUR: 100.0, CNY: 12.7}
  telegram: {bot_token: "", chat_id: ""}
  smtp: {host: "", port: 587, ssl: false, user: "", password: "", sender: "", to: ""}
```

Курсы валют: `python price_finder.py update-rates --write-config` — скачает актуальные
(open.er-api.com) и обновит блок `currencies`. Или `--update-rates` в любом поиске.

### Уведомления

**Telegram**: создайте бота у @BotFather → `bot_token`; узнайте `chat_id`
(напишите боту и откройте `https://api.telegram.org/bot<TOKEN>/getUpdates`).

**E-mail (SMTP)**:
```yaml
  smtp:
    host: smtp.gmail.com      # Яндекс: smtp.yandex.ru, Mail.ru: smtp.mail.ru
    port: 587                 # 465 + ssl: true
    user: you@gmail.com
    password: "пароль приложения"   # не основной пароль!
    to: you@gmail.com
```

## 7. Антибот: что делать, если сайт не отдаёт данные

1. `js_render: true` + установленный Playwright — самый частый случай (Ozon, WB, Маркет).
2. `delay: 2…5`, `retries: 3` — не долбить сайт.
3. Свои `headers` (Referer, Accept-Language) и `cookies` из вашего браузера.
4. `--proxy` / `settings.proxy` — ротация прокси.
5. Проверить `robots.txt` и условия использования сайта: парсинг может быть запрещён
   правилами площадки. `respect_robots: true` по умолчанию уважает robots.txt.
6. Для маркетплейсов часто честнее и стабильнее официальные API:
   * Wildberries: `https://search.wildberries.ru/...` (открытый поиск) и API продавца;
   * Ozon: Seller API; Яндекс.Маркет: партнерский API.
   Такой источник добавляется как `method: JSON` + `post_data`/`search_url` с `{query}`,
   а цена достаётся через `json:`-селектор.

Проверка причины — одной командой:
```bash
python price_finder.py test-site ozon "ssd" --dump-html ozon.html --js
```

## 8. Структура проекта

```
price_finder/
├── price_finder.py          # CLI: search / watch / history / sites / test-site / targets …
├── requirements.txt
├── README.md
├── ИНСТРУКЦИЯ.md            # пошаговая инструкция: установка, запуск, уведомления
├── queries.txt              # ВАШ список товаров (search/watch --queries-file)
├── setup.bat / setup.sh     # установка в один клик
├── search.bat / search.sh   # поиск по queries.txt без ввода команд
├── watch.bat / watch.sh     # мониторинг по queries.txt
├── run_demo.sh              # «всё сразу»: демо-магазин + пример поиска
├── config/
│   ├── sites.yaml           # настройки источников, валют, уведомлений
│   └── sites.template.yaml  # шаблон для init-config
├── gui_app.py               # точка входа GUI (Android/APK); --selftest без окна
├── pricefinder/
│   ├── price.py             # парсинг цен («1 299,90 ₽», «от 500 до 700 руб.»), валюты, курсы
│   ├── sites.py             # загрузка/валидация конфига, построение URL, интервалы
│   ├── yamlite.py           # встроенный мини-парсер YAML — программа работает БЕЗ PyYAML
│   ├── paths.py             # пути для ПК/Termux/APK (где БД, конфиг, отчёты)
│   ├── fetcher.py           # HTTP: ретраи, robots.txt, прокси, Playwright
│   ├── parsers.py           # 4 стратегии извлечения карточек + очистка/дедуп/слияние
│   ├── search.py            # параллельный опрос сайтов, склейка и сортировка
│   ├── storage.py           # SQLite: товары, история цен, цели, журнал уведомлений
│   ├── notify.py            # шторка Android (Termux:API) + Telegram + SMTP
│   ├── gui_logic.py         # логика интерфейса без kivy (её тестируем на любом устройстве)
│   ├── gui_ui.py            # виджеты Kivy (импортируются только при запуске окна)
│   ├── display.py           # проверка доступности графики до импорта kivy
│   └── reports.py           # консоль, CSV, XLSX, JSON, HTML-отчёт
├── APK.md                   # как получить готовый APK (GitHub Actions / Linux / Codespaces)
├── pack_source.py           # собрать price_finder_source.zip для загрузки на GitHub
├── .github/workflows/build-apk.yml   # авто-сборка APK в облаке GitHub
├── android/
│   ├── ANDROID.md           # подробная инструкция по запуску на телефоне
│   ├── install_termux.sh    # установка в Termux одной командой
│   ├── install_gui_termux.sh# kivy + Termux:X11 для сенсорного интерфейса
│   ├── termux_start.sh      # меню: поиск / мониторинг / история / GUI
│   ├── watch_once.sh        # один цикл мониторинга (для планировщика)
│   ├── setup_termux_job.sh  # мониторинг по расписанию через termux-job-scheduler
│   ├── buildozer.spec       # настройки сборки APK
│   └── build_apk.sh         # сборка APK (Linux + Docker)
└── tests/
    ├── test_all.py          # 23 теста ядра (pytest или python tests/test_all.py)
    ├── test_gui.py          # 20 тестов мобильной части: YAML, пути, GUI, Android
    ├── demo_server.py       # локальный демо-магазин (3 типа верстки)
    └── fixtures/            # HTML-примеры реальных разметок
```

Тесты:
```bash
python tests/test_all.py        # или: pytest tests/ -q
```

## 9. Форматы выгрузки

* `--csv` — CSV с `;` и BOM (открывается в Excel сразу, колонки: цена, площадка, ссылка…);
* `--xlsx` — две вкладки («Цены» с фильтром и гиперссылками, «Сводка»), лучшая строка подсвечена;
* `--json` — машинально читаемый результат + сводная статистика;
* `--html` — автономный отчёт (inline CSS, открывается в любом браузере);
* `--save файл.расширение` — формат определится по расширению.

Относительные имена складываются в `out/`.

## 10. Как это работает внутри

1. `sites.py` строит URL выдачи для каждого источника (`{query}`, `{page}`).
2. `fetcher.py` скачивает страницы параллельно по сайтам, с ретраями и ротацией
   User-Agent; при `js_render` — через Playwright.
3. `parsers.py` пробует 4 стратегии: CSS-селекторы → JSON‑LD → microdata → meta.
   Первая, давшая результат, побеждает (её имя видно в `--json`/CSV в поле `strategy`).
4. Цены нормализуются (`price.py`): «1 299,90 ₽», «US$1,299.00», «от 500 до 700 руб.»
   → число + валюта; пересчёт в базовую валюту.
5. Фильтры (`min/max-price`, ключевые слова, наличие), дедупликация, слияние
   одинаковых предложений с разных площадок, сортировка по цене.
6. `storage.py` пишет историю цен; `watch` сравнивает с предыдущими значениями и
   формирует уведомления; `reports.py` рисует таблицу/файлы.

## 11. Если что-то пошло не так

| Симптом | Что делать |
|---|---|
| `HTTP 403 / 429 / 503` | сайт видит бота: `--js`, больше `delay`, свои `headers`/`cookies`, прокси |
| «карточки не распознаны» | неверные селекторы или контент грузит JS: `test-site <id> "q" --dump-html p.html` и правьте `fields` |
| «robots.txt disallow» | сайт запрещает парсинг каталога; можно обойти `--ignore-robots` (на ваш риск и ответственность) |
| цен мало / много мусора | `--require-keyword`, `--include`, `--exclude`, `--max-ratio 1.5`, `--in-stock`, `min_price` в конфиге |
| цены в разных валютах сравниваются неверно | `--update-rates` или пропишите курсы в `settings.currencies.rates` |
| `нужен Playwright` | `pip install playwright && playwright install chromium` |
| нет уведомлений | заполните `settings.telegram` / `settings.smtp` в `config/sites.yaml` |
| цена в выдаче ≠ цена в корзине | так работает у всех парсеров: регион, скидка по карте и доставка видны только в карточке товара |

## 12. Запуск на Android

> **Нужен APK-файл?** Готового APK в репозитории нет — он собирается из исходников.
> Проще всего собрать его бесплатно в облаке GitHub (20–40 минут, скачаете готовый
> файл): пошаговая инструкция в **[APK.md](APK.md)** (внутри уже лежит готовый
> workflow `.github/workflows/build-apk.yml`).


Четыре способа — подробно в **[android/ANDROID.md](android/ANDROID.md)**:

| Способ | Команды |
|---|---|
| **Termux (консоль)** | `bash android/install_termux.sh` → `python price_finder.py search "товар"` |
| **Termux + GUI** | `bash android/install_gui_termux.sh` → `termux-x11 :1 -ac &` → `export DISPLAY=:1` → `python price_finder.py gui` |
| **Pydroid 3** | Pip → `requests`, `beautifulsoup4` → открыть `price_finder.py` |
| **Свой APK** | на Linux: `bash android/build_apk.sh` → установить `bin/*.apk` |

Особенности мобильной версии:

* **PyYAML не нужен** — конфиг читает встроенный `pricefinder/yamlite.py`
  (результат байт-в-байт совпадает с PyYAML, это проверяет тест);
* **lxml и openpyxl необязательны** — без lxml работает `html.parser`, без openpyxl
  недоступен только `--xlsx`;
* данные (база цен, отчёты, список товаров) кладутся в доступную для записи папку:
  на телефоне это `~/pricefinder/`, посмотреть — `python price_finder.py env`;
* уведомления в **шторку Android** через Termux:API, плюс Telegram и e-mail;
* мониторинг по расписанию без открытого окна — `bash android/setup_termux_job.sh 30m`;
* **Playwright на Android не ставится**, поэтому площадки с чисто клиентской
  выдачей (Ozon, WB, Яндекс.Маркет) на телефоне не парсятся — для них нужен ПК.

Минимальный набор зависимостей на телефоне: `requests` + `beautifulsoup4`.

## 13. Ограничения и этика

* Данные принадлежат сайтам; перед автоматизацией проверьте их условия использования
  и `robots.txt`. Используйте минимально необходимую частоту запросов (`delay`).
* Селекторы ломаются, когда сайт меняет вёрстку — лечится правкой `fields`
  (диагностика: `test-site ... --dump-html`).
* Цены на странице поиска могут отличаться от цены в карточке товара (регион,
  скидки по карте, доставка) — для финальной проверки переходите по ссылке.
