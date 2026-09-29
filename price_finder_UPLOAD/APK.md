# Как получить APK на телефон

Коротко: **готового APK для скачивания нет** — его нужно собрать из исходников.
Это требование Google и самой технологии: APK собирается компилятором
(python-for-android/buildozer), которому нужны Android SDK/NDK (~5 ГБ) и 30–90 минут
работы. Ниже — три рабочих способа, от самого простого к самому сложному.

> Если цель — «просто чтобы работало на телефоне», APK вообще не обязателен:
> вариант **Termux** (см. `android/ANDROID.md`, раздел A) устанавливается за 3 минуты
> и даёт весь функционал, включая мониторинг по расписанию и уведомления в шторку.

---

## Способ 1 (рекомендую): GitHub соберёт APK за вас — бесплатно, без установки программ

Нужен только бесплатный аккаунт GitHub и браузер. Всё соберётся в облаке,
вы скачаете готовый `.apk`.

### Шаг 1. Загрузить проект на GitHub

**Через браузер (проще всего):**

1. Зарегистрируйтесь/войдите на <https://github.com>.
2. Нажмите **+** (справа сверху) → **New repository**.
3. Имя: `pricefinder`. Галочку *Add a README* **не ставьте**. Нажмите **Create repository**.
4. На странице нового репозитория нажмите **uploading an existing file**.
5. Распакуйте архив `price_finder_source.zip` и перетащите в окно браузера
   **содержимое папки `price_finder`** (файлы `gui_app.py`, `price_finder.py`,
   папки `pricefinder`, `config`, `android`, `.github`, `tests` и т.д.).
6. Внизу нажмите **Commit changes**.

> Важно: папка `.github` с файлом `workflows/build-apk.yml` должна попасть в репозиторий —
> именно он запускает сборку. Включите отображение скрытых файлов в проводнике
> (Windows: Вид → Показать → Скрытые элементы).

**Или через git в консоли:**

```bash
cd price_finder
git init && git add . && git commit -m "pricefinder"
git branch -M main
git remote add origin https://github.com/ВАШ_ЛОГИН/pricefinder.git
git push -u origin main
```

### Шаг 2. Запустить сборку

1. В репозитории откройте вкладку **Actions**.
2. Если появится надпись «Workflows aren't being run on this fork» — нажмите
   **I understand my workflows, go ahead and run them**.
3. Слева выберите **build-apk** → справа **Run workflow** → зелёная кнопка **Run workflow**.

### Шаг 3. Скачать APK

1. Обновите страницу: появится жёлтая (идёт) или зелёная (готова) строка запуска.
   Сборка занимает **20–40 минут**.
2. Кликните по запуску → блок **Artifacts** → скачайте **pricefinder-apk**.
3. Распакуйте ZIP — внутри файл вида
   `pricefinder-1.0.0-arm64-v8a_armeabi-v7a-debug.apk`.
4. Перекиньте его на телефон (Telegram «Избранное», Google Drive, USB, почта).
5. На телефоне откройте файл → разрешите «Установку из неизвестных источников» →
   Установить.

Если сборка упала (красный крестик): откройте запуск → скачайте артефакт
**build-log** → посмотрите последние строки. Чаще всего помогает повторный запуск
(Run workflow) — зависимости скачиваются заново.

---

## Способ 2: собрать на своём компьютере (Linux или Windows+WSL)

На Windows без WSL собрать нельзя — buildozer работает только в Linux.

```bash
# Windows: установите WSL (PowerShell от админа)
wsl --install -d Ubuntu-22.04

# дальше внутри Ubuntu
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk autoconf automake libtool \
    libltdl-dev libffi-dev libssl-dev build-essential cmake pkg-config \
    zlib1g-dev python3-dev python3-venv python3-pip

cd price_finder
bash android/build_apk.sh --local      # без Docker
# или просто: bash android/build_apk.sh   (если установлен Docker)
```

Первая сборка качает SDK/NDK (~5 ГБ) и идёт 30–90 минут. Результат — в `bin/`.
Повторные сборки идут быстрее (кэш в `~/.buildozer`).

---

## Способ 3: GitHub Codespaces (облачный Linux в браузере)

Если своего Linux нет, а способ 1 не сработал:

1. В репозитории: зелёная кнопка **Code** → **Codespaces** → **Create codespace on main**.
2. В открывшемся терминале:

```bash
sudo apt update && sudo apt install -y openjdk-17-jdk autoconf automake libtool \
  libltdl-dev libffi-dev libssl-dev build-essential cmake pkg-config zlib1g-dev \
  python3-dev zip unzip
pip install buildozer "cython==0.29.36"
cp android/buildozer.spec ./buildozer.spec
buildozer android debug
```

3. Готовый APK появится в `bin/` — скачайте правой кнопкой → **Download**.
   Бесплатный лимит Codespaces: 60 часов в месяц, этого хватает.

---

## Что внутри APK и как им пользоваться

* При запуске открывается сенсорный интерфейс: вкладки **Поиск / Список / Слежка /
  История / Сайты / Настройки**.
* Товар вводится в поле на вкладке «Поиск» или списком на вкладке «Список»
  (файл `queries.txt`, формат: `товар ; желаемая цена ; падение % ; сайты`).
* При первом запуске конфиг `config/sites.yaml` и `queries.txt` копируются из
  пакета в папку приложения (внутри APK они только для чтения) — править площадки
  можно на вкладке «Сайты» галочками.
* История цен пишется в базу приложения, поэтому «исторический минимум» работает
  между запусками.
* Уведомления: заполните Telegram/SMTP во вкладке настроек конфига
  (`settings.telegram`, `settings.smtp`).
* Разрешения: только интернет (`INTERNET`, `ACCESS_NETWORK_STATE`) + `WAKE_LOCK`
  и `VIBRATE`, чтобы мониторинг не прерывался. Данные никуда не отправляются,
  кроме тех сайтов, которые вы сами парсите.

### Ограничения APK

| Что | Работает |
|---|---|
| Поиск цен, фильтры, история, мониторинг | ✅ |
| Уведомления Telegram / e-mail | ✅ |
| Отчёты CSV / JSON / HTML | ✅ (сохраняются в папку приложения) |
| Отчёты XLSX | ❌ (в APK не пакуется openpyxl) |
| JS-рендер сайтов (Playwright) | ❌ (Chromium на Android так не ставится) |
| Мониторинг при закрытом приложении | ⚠️ ограниченно: Android выгружает процесс; надёжнее Termux + `setup_termux_job.sh` |

---

## Подписать APK для публикации (необязательно)

Debug-APK подписан отладочным ключом — для себя этого достаточно. Для Google Play:

```bash
keytool -genkey -v -keystore pricefinder.keystore -alias pricefinder \
        -keyalg RSA -keysize 2048 -validity 10000
```

затем в `android/buildozer.spec` раскомментируйте блок подписи и соберите
`buildozer android release`.

---

## Иконка приложения

Положите `icon.png` (512×512, непрозрачный) в папку `android/` и раскомментируйте
в `android/buildozer.spec` строку:

```
icon.filename = android/icon.png
```

После этого пересоберите APK — приложение появится в меню с вашей иконкой.
