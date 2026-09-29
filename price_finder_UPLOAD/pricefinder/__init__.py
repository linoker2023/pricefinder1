"""pricefinder — поиск самых низких цен на товар полюбым сайтам.

Модули:
    price   — парсинг и нормализация цен/валют
    sites   — загрузчик конфигурации сайтов (YAML)
    fetcher — загрузка HTML (requests, ретраи, опционально Playwright)
    parsers — извлечение карточек товаров (CSS-селекторы, JSON-LD, microdata, meta)
    storage — история цен в SQLite
    notify  — уведомления (Telegram / e-mail)
    reports — вывод в консоль, CSV, XLSX, JSON, HTML
"""

__version__ = "1.0.0"
