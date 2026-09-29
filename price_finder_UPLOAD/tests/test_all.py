#!/usr/bin/env python3
"""Тесты pricefinder. Работают и через pytest, и напрямую:

    python tests/test_all.py
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pricefinder.parsers import Item, parse_items, summarize  # noqa: E402
from pricefinder.search import SearchEngine  # noqa: E402
from pricefinder.price import Converter, parse_price  # noqa: E402
from pricefinder.sites import SiteConfig, config_from_dict  # noqa: E402
from pricefinder.storage import Storage  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _site(**kw) -> SiteConfig:
    kw.setdefault("id", "test")
    kw.setdefault("name", "Тест")
    kw.setdefault("currency", "RUB")
    return SiteConfig(**kw)


# --- 1. парсинг цен ---------------------------------------------------------

PRICE_CASES = [
    ("42 990 ₽", 42990.0, "RUB"),
    ("24\u00a0990\u00a0₽", 24990.0, "RUB"),
    ("1 299,90 руб.", 1299.9, "RUB"),
    ("US$ 1,299.00", 1299.0, "USD"),
    ("1.299,00 €", 1299.0, "EUR"),
    ("12 345 678 ₸", 12345678.0, "KZT"),
    ("999", 999.0, "RUB"),
    ("3 490 р.", 3490.0, "RUB"),
    ("2 790,50 Br", 2790.5, "BYN"),
    ("51 990 ₽", 51990.0, "RUB"),
    ("1 234 567", 1234567.0, "RUB"),
    ("нет в наличии", None, None),
    ("", None, None),
]


def test_parse_price():
    for text, expected, currency in PRICE_CASES:
        price = parse_price(text)
        if expected is None:
            assert price is None, f"{text!r}: ожидали None, получили {price}"
        else:
            assert price is not None, f"{text!r}: цена не распознана"
            assert abs(price.amount - expected) < 0.01, f"{text!r}: {price.amount} != {expected}"
            assert price.currency == currency, f"{text!r}: валюта {price.currency} != {currency}"


def test_price_range_and_conversion():
    price = parse_price("от 500 до 700 руб.")
    assert price and price.amount == 500.0 and price.high == 700.0 and price.is_range
    assert parse_price("от 500 до 700 руб.", prefer_low=False).amount == 700.0

    conv = Converter(base="RUB", rates={"USD": 90.0, "EUR": 100.0})
    assert conv.convert(10, "USD") == 900.0
    assert conv.convert_price(parse_price("1.299,00 €")) == 129900.0
    assert conv.convert(10, "RUB") == 10          # базовая валюта
    assert conv.convert(10, "XYZ") == 10          # неизвестный курс -> без пересчёта
    assert conv.unknown_currencies([parse_price("5 $"), parse_price("5 ₽")]) == []      # USD есть в курсах
    assert conv.unknown_currencies([parse_price("5 ₸")]) == ["KZT"]                      # курса нет


# --- 2. стратегия CSS -------------------------------------------------------

CSS_HTML = """
<html><body>
  <div class="card">
    <a class="lnk" href="/item/1"><img class="pic" src="/img/1.jpg"></a>
    <div class="ttl">Товар А</div>
    <div class="old">50 000 ₽</div>
    <div class="cur" data-price="42990">42 990 ₽</div>
    <div class="seller">Продавец А</div>
    <div class="stock">В наличии</div>
  </div>
  <div class="card">
    <a class="lnk" href="https://shop.example/item/2?utm_source=mail"><img class="pic" src="/img/2.jpg"></a>
    <div class="ttl">Товар Б</div>
    <div class="cur">12 345,67 ₽</div>
    <div class="stock">Нет в наличии</div>
  </div>
</body></html>
"""


def test_css_strategy():
    site = _site(
        product_selector="div.card",
        fields={
            "title": ".ttl",
            "price": ".cur",
            "old_price": ".old",
            "url": "a.lnk",
            "image": "img.pic",
            "seller": ".seller",
            "availability": ".stock",
        },
    )
    items, strategy = parse_items(CSS_HTML, site, "https://shop.example/search?q=x")
    assert strategy == "css", strategy
    assert len(items) == 2
    cheap = items[0]
    assert cheap.title == "Товар Б" and cheap.price == 12345.67
    assert cheap.url == "https://shop.example/item/2"          # utm-метки вычищены
    assert items[1].old_price == 50000.0
    assert items[1].image == "https://shop.example/img/1.jpg"  # относительный src -> абсолютный
    assert items[1].seller == "Продавец А"
    assert items[1].availability == "В наличии"


def test_css_selector_variants():
    """Список селекторов, attr:, regex:, min:/first: — все формы из README."""
    site = _site(
        product_selector="div.card",
        fields={
            "title": [".missing", ".ttl"],              # первый непустой
            "price": "first:.cur",                      # режим first (не минимум)
            "url": "a.lnk",
            "availability": "regex:(В наличии|Нет в наличии)",
            "seller": "attr:data-price",                # значение атрибута
        },
    )
    items, strategy = parse_items(CSS_HTML, site, "https://shop.example/")
    assert strategy == "css" and len(items) == 2
    first = next(i for i in items if i.title == "Товар А")
    assert first.availability == "В наличии"
    assert first.seller == "42990"


def test_exclude_include_and_price_bounds():
    site = _site(
        product_selector="div.card",
        fields={"title": ".ttl", "price": ".cur", "url": "a.lnk"},
        exclude_keywords=["товар б"],
        min_price=1000,
    )
    items, _ = parse_items(CSS_HTML, site, "https://shop.example/")
    assert [i.title for i in items] == ["Товар А"]

    site2 = _site(
        product_selector="div.card",
        fields={"title": ".ttl", "price": ".cur", "url": "a.lnk"},
        max_price=20000,
    )
    items2, _ = parse_items(CSS_HTML, site2, "https://shop.example/")
    assert [i.title for i in items2] == ["Товар Б"]


# --- 3. стратегия JSON-LD ---------------------------------------------------

JSONLD_HTML = """
<html><head><title>Каталог</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
 {"@type":"ListItem","position":1,"item":{"@type":"Product","name":"Смартфон X 128GB",
   "image":"/img/x.jpg","url":"/product/x",
   "aggregateRating":{"@type":"AggregateRating","ratingValue":4.7,"reviewCount":312},
   "offers":{"@type":"Offer","priceCurrency":"RUB","price":15990,
             "availability":"https://schema.org/InStock","seller":{"@type":"Organization","name":"MiStore"}}}},
 {"@type":"ListItem","position":2,"item":{"@type":"Product","name":"Смартфон Y",
   "offers":{"@type":"AggregateOffer","lowPrice":"9990","highPrice":"12990","priceCurrency":"RUB"}}}
]}
</script>
<script type="application/ld+json">
[{"@context":"https://schema.org","@graph":[
   {"@id":"#p3","@type":"Product","name":"Чехол","offers":{"@id":"#o3","@type":"Offer","price":490,"priceCurrency":"RUB"}},
   {"@id":"#o3","availability":"https://schema.org/OutOfStock"}
]}]
</script>
</head><body>без разметки</body></html>
"""


def test_jsonld_strategy():
    site = _site()  # селекторов нет вообще — только авто-парсинг
    items, strategy = parse_items(JSONLD_HTML, site, "https://shop.example/search?q=смартфон")
    assert strategy == "jsonld", strategy
    titles = {i.title for i in items}
    assert titles == {"Смартфон X 128GB", "Смартфон Y", "Чехол"}, titles
    cheap = items[0]
    assert cheap.title == "Чехол" and cheap.price == 490.0
    phone = next(i for i in items if i.title == "Смартфон X 128GB")
    assert phone.rating == 4.7 and phone.reviews == 312
    assert phone.seller == "MiStore" and phone.availability == "в наличии"
    assert phone.url == "https://shop.example/product/x"
    assert phone.image == "https://shop.example/img/x.jpg"
    assert any(i.price == 9990.0 for i in items)      # AggregateOffer -> lowPrice


# --- 4. стратегия microdata -------------------------------------------------

MICRODATA_HTML = """
<html><body>
<div itemscope itemtype="https://schema.org/Product">
  <h1 itemprop="name">Кофемашина DeLonghi</h1>
  <img itemprop="image" src="/img/coffee.jpg">
  <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
    <meta itemprop="price" content="33990">
    <meta itemprop="priceCurrency" content="RUB">
    <link itemprop="availability" href="https://schema.org/InStock">
    <span itemprop="seller">Coffee House</span>
  </div>
</div>
</body></html>
"""


def test_microdata_strategy():
    items, strategy = parse_items(MICRODATA_HTML, _site(), "https://shop.example/product/9")
    assert strategy == "microdata", strategy
    assert len(items) == 1
    it = items[0]
    assert it.title == "Кофемашина DeLonghi"
    assert it.price == 33990.0 and it.currency == "RUB"
    assert it.availability == "в наличии"
    assert it.image == "https://shop.example/img/coffee.jpg"


# --- 5. стратегия meta ------------------------------------------------------

META_HTML = """
<html><head>
<meta property="og:title" content="Наушники Sony WH-1000XM5">
<meta property="og:url" content="https://shop.example/p/sony">
<meta property="og:image" content="https://shop.example/img/sony.jpg">
<meta property="product:price:amount" content="26 990">
<meta property="product:price:currency" content="RUB">
<meta property="product:availability" content="in stock">
</head><body><p>страница товара без каталожной разметки</p></body></html>
"""


def test_meta_strategy():
    items, strategy = parse_items(META_HTML, _site(currency="USD"), "https://shop.example/p/sony")
    assert strategy == "meta", strategy
    assert len(items) == 1
    it = items[0]
    assert it.title == "Наушники Sony WH-1000XM5"
    assert it.price == 26990.0 and it.currency == "RUB"
    assert it.url == "https://shop.example/p/sony"


def test_empty_and_garbage_html():
    site = _site(product_selector="div.card", fields={"title": ".ttl", "price": ".cur"})
    assert parse_items("", site, "https://x/")[0] == []
    assert parse_items("<html><body>капча</body></html>", site, "https://x/")[0] == []


# --- 6. конфигурация --------------------------------------------------------

def test_config_loading_and_url_building():
    cfg = config_from_dict({
        "settings": {"timeout": 5, "currencies": {"base": "RUB", "rates": {"USD": 90}}},
        "sites": [
            {"id": "a", "name": "A", "enabled": True,
             "search_url": "https://a.example/s?q={query}&p={page}", "start_page": 0, "max_pages": 3,
             "unknown_option": 1},
            {"id": "b", "enabled": False, "search_url": "https://b.example/s?q={query}"},
            {"id": "c", "enabled": False, "static": True, "search_url": "https://c.example/top"},
        ],
    })
    assert cfg.by_id("A").id == "a"                    # поиск по имени, регистронезависимо
    assert [s.id for s in cfg.enabled()] == ["a"]
    assert [s.id for s in cfg.select(["b"], only_enabled=False)] == ["b"]
    assert cfg.sites[0].build_page_urls("iphone 15") == [
        "https://a.example/s?q=iphone+15&p=0",
        "https://a.example/s?q=iphone+15&p=1",
        "https://a.example/s?q=iphone+15&p=2",
    ]
    assert cfg.by_id("c").build_page_urls("что угодно") == ["https://c.example/top"]


def test_real_config_is_valid():
    """config/sites.yaml обязан грузиться и иметь демо-сайт."""
    import yaml

    data = yaml.safe_load((ROOT / "config" / "sites.yaml").read_text(encoding="utf-8"))
    cfg = config_from_dict(data)
    assert cfg.by_id("demo") is not None
    assert cfg.settings["currencies"]["base"] == "RUB"
    assert cfg.by_id("demo").build_page_urls("ноутбук")[0].startswith("http://127.0.0.1:8765/search?q=")


# --- 7. хранение истории ----------------------------------------------------

def _item(title: str, price: float, url: str, site_id: str = "test") -> Item:
    it = Item(site_id=site_id, site_name=site_id, title=title, price=price, currency="RUB", url=url)
    it.normalized_price = price
    return it


def test_storage_history_and_alerts():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp) / "t.db")
        item = _item("Товар", 1000.0, "https://x/1")

        events = storage.save_items([item], query="товар")
        assert events[0]["is_new"] and events[0]["all_time_low"] == 1000.0

        # та же цена -> новая точка не добавляется
        events = storage.save_items([item], query="товар")
        assert not events[0]["price_changed"]
        assert len(events[0]["history"]) == 1

        # цена упала
        cheaper = _item("Товар", 800.0, "https://x/1")
        events = storage.save_items([cheaper], query="товар")
        ev = events[0]
        assert ev["price_changed"] and ev["prev_price"] == 1000.0
        assert ev["drop_pct"] == -20.0 and ev["is_all_time_low"]
        assert len(ev["history"]) == 2

        # алерты не дублируются
        storage.log_alert(cheaper.uid, "товар", "all_time_low", 800.0, {})
        assert storage.alert_seen(cheaper.uid, "all_time_low", 800.0)
        assert not storage.alert_seen(cheaper.uid, "all_time_low", 799.0)

        rows = storage.all_items()
        assert rows[0]["min_price"] == 800.0 and rows[0]["max_price"] == 1000.0 and rows[0]["points"] == 2

        storage.add_target("товар", None, 850.0, 5.0)
        targets = storage.targets()
        assert targets[0]["target_price"] == 850.0
        storage.set_target_active(targets[0]["id"], False)
        assert storage.targets() == [] and len(storage.targets(only_active=False)) == 1
        storage.close()


# --- 8. сводка и отчёты ------------------------------------------------------

def test_summarize_and_reports():
    items = [
        _item("A", 100.0, "https://x/a"),
        _item("B", 200.0, "https://x/b"),
        _item("C", 300.0, "https://x/c"),
    ]
    stats = summarize(items)
    assert stats["count"] == 3 and stats["min"] == 100.0 and stats["median"] == 200.0
    assert stats["spread_pct"] == 200.0

    from pricefinder import reports

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assert reports.save_csv(items, tmp_path / "r.csv").exists()
        text = (tmp_path / "r.csv").read_text(encoding="utf-8-sig")
        assert text.splitlines()[0].startswith("rank;site;title")
        assert "100.0" in text

        assert reports.save_json(items, tmp_path / "r.json", "тест").exists()
        assert reports.save_html(items, tmp_path / "r.html", "тест").exists()
        assert "Самые низкие цены" in (tmp_path / "r.html").read_text(encoding="utf-8")
        assert reports.save_xlsx(items, tmp_path / "r.xlsx", "тест").exists()
        assert reports.save_auto(items, tmp_path / "auto.csv", "тест").suffix == ".csv"

        html, plain = reports.build_alert_html(
            [{"item": items[0], "prev_price": 150.0, "is_all_time_low": True}], "тест"
        )
        assert "Снижение цены" in html and "100" in plain


def test_sparkline():
    sys.path.insert(0, str(ROOT))
    import importlib

    pf = importlib.import_module("price_finder")
    assert pf.sparkline([]) == ""
    assert len(pf.sparkline([1, 2, 3, 4, 5])) == 5
    assert pf.sparkline([5, 5, 5]) == "▄▄▄"


# --- 9. поиск через демо-сервер (интеграция) --------------------------------

def test_demo_integration():
    """Поднимает демо-магазин отдельным процессом и ищет в нём товар."""
    import socket
    import subprocess

    port = 8899
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "tests" / "demo_server.py"), "--port", str(port), "--quiet"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):                       # ждём до ~8 секунд
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                import time as _time

                _time.sleep(0.2)
        else:
            raise AssertionError("демо-сервер не поднялся")

        import yaml

        from pricefinder.sites import config_from_dict

        cfg = config_from_dict(yaml.safe_load((ROOT / "config" / "sites.yaml").read_text(encoding="utf-8")))
        demo = cfg.by_id("demo")
        demo.search_url = demo.search_url.replace("8765", str(port))
        demo2 = cfg.by_id("demo2")
        demo2.search_url = demo2.search_url.replace("8765", str(port))

        engine = SearchEngine(cfg, workers=2)
        try:
            # одна площадка
            result = engine.search("ноутбук", [demo])
            assert result.errors == [], result.errors
            assert len(result.items) == 4
            prices = [i.price for i in result.items]
            assert prices == sorted(prices) and prices[0] == 24990.0
            assert result.items[0].title.startswith("Ноутбук HP")
            assert result.items[0].strategy == "css"
            assert result.items[0].old_price == 33990.0
            assert result.items[0].rating == 4.1

            # две площадки: вторая дешевле на 8% — сравнение цен работает
            both = engine.search("ноутбук", [demo, demo2])
            assert len(both.items) == 8, len(both.items)
            assert both.items[0].price == round(24990 * 0.92)
            assert {i.site_id for i in both.items} == {"demo", "demo2"}
            assert both.items[0].strategy == "jsonld"      # у demo2 селекторов нет

            # фильтры: исключаем витринные образцы и товары не в наличии
            filtered = engine.search("смартфон iphone", [demo],
                                     exclude_keywords=["витринный"], in_stock_only=True)
            titles = [i.title for i in filtered.items]
            assert titles and all("витринный" not in t.lower() for t in titles)

            # пагинация не ломает выдачу, даже если страницы кончились
            paged = engine.search("наушники", [demo], pages=5)
            assert len(paged.items) == 2
        finally:
            engine.fetcher.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


# --- 10. слияние одинаковых предложений и стабильность uid -------------------

def test_merge_same_offers():
    from pricefinder.parsers import merge_same_offers

    a = _item("Товар X", 100.0, "https://a.example/1", site_id="a")
    b = _item("Товар X", 100.0, "https://b.example/1", site_id="b")
    c = _item("товар x!", 100.0, "https://c.example/1", site_id="c")   # то же название, другой регистр/знаки
    d = _item("Товар X", 150.0, "https://d.example/1", site_id="d")   # другая цена — не сливается
    merged = merge_same_offers([d, a, b, c])
    assert len(merged) == 2, [m.title for m in merged]
    assert merged[0].price == 100.0
    assert sorted(merged[0].also_at) == [b.site_name, c.site_name]
    assert merged[0].uid == a.uid                                     # uid первой (самой дешёвой) площадки
    assert merged[1].price == 150.0 and merged[1].also_at == []


def test_uid_is_stable():
    cheap = _item("Товар", 100.0, "https://shop.example/item/1")
    expensive = _item("Товар", 80.0, "https://shop.example/item/1")
    http = _item("Товар", 100.0, "http://www.shop.example/item/1/")
    other = _item("Товар", 100.0, "https://shop.example/item/2")
    assert cheap.uid == expensive.uid        # цена не влияет на идентификатор
    assert cheap.uid == http.uid             # схема/www/слэш не влияют
    assert cheap.uid != other.uid            # другая ссылка — другое предложение
    assert cheap.uid != _item("Товар", 100.0, "https://shop.example/item/1", site_id="b").uid


# --- 11. разбор реальных HTML-фикстур ----------------------------------------

def test_fixture_bookvoed_css():
    """Фикстура —реальный HTML листинга Буквоеда (селекторы из config/sites.yaml)."""
    import yaml

    from pricefinder.sites import config_from_dict

    path = FIXTURES / "bookvoed_search.html"
    if not path.exists():
        print("    (фикстура bookvoed_search.html отсутствует — тест пропущен)")
        return
    cfg = config_from_dict(yaml.safe_load((ROOT / "config" / "sites.yaml").read_text(encoding="utf-8")))
    site = cfg.by_id("bookvoed")
    items, strategy = parse_items(
        path.read_text(encoding="utf-8"), site, "https://www.bookvoed.ru/search?q=x"
    )
    assert strategy == "css"
    assert len(items) >= 10, len(items)
    prices = [i.price for i in items]
    assert prices == sorted(prices) and prices[0] > 0
    assert items[0].url.startswith("https://www.bookvoed.ru/product/")
    assert all(i.title for i in items)
    assert any(i.old_price and i.old_price > i.price for i in items)   # зачёркнутая цена > текущей


def test_fixture_listing_autodetect():
    """Та же фикстура, но без селекторов — должен сработать авто-парсинг JSON-LD."""
    path = FIXTURES / "listing_css_jsonld.html"
    if not path.exists():
        return
    html = path.read_text(encoding="utf-8")
    items, strategy = parse_items(html, _site(), "https://shop.example/search?q=наушники")
    assert strategy == "jsonld", strategy
    assert {i.title for i in items} == {
        "Наушники Sony WH-1000XM5 чёрные",
        "Наушники Apple AirPods Pro 2 USB-C",
    }
    assert items[0].price == 18990.0                     # сортировка по цене
    assert items[1].price == 26990.0 and items[1].old_price is None
    assert items[1].availability == "в наличии"
    assert items[0].availability == "нет в наличии"
    assert items[1].rating == 4.8 and items[1].reviews == 492

    # а с селекторами побеждает css-стратегия
    site = _site(
        product_selector="div.product-card",
        fields={
            "title": ".product-card__title",
            "price": ".product-card__price",
            "old_price": "max:.product-card__price-old",
            "url": "a.product-card__link",
            "image": "img.product-card__img",
            "seller": ".product-card__seller",
            "availability": ".product-card__stock",
        },
    )
    items_css, strategy_css = parse_items(html, site, "https://shop.example/search?q=наушники")
    assert strategy_css == "css" and len(items_css) == 2
    assert items_css[1].old_price == 33990.0
    assert items_css[1].url == "https://shop.example/product/101"      # utm вычищен


def test_live_bookvoed():
    """Интеграция с живым сайтом (пропускается, если нет сети или сайт недоступен)."""
    import socket

    try:
        socket.create_connection(("www.bookvoed.ru", 443), timeout=4).close()
    except OSError:
        print("    (нет сети — тест живого сайта пропущен)")
        return

    import yaml

    from pricefinder.search import SearchEngine

    cfg = config_from_dict(yaml.safe_load((ROOT / "config" / "sites.yaml").read_text(encoding="utf-8")))
    site = cfg.by_id("bookvoed")
    engine = SearchEngine(cfg, workers=1)
    result = engine.search("гарри поттер", [site], limit_per_site=30)
    engine.fetcher.close()
    assert result.items, f"сайт не отдал карточки: {result.errors}"
    prices = [i.price for i in result.items]
    assert prices == sorted(prices)
    assert all(i.url.startswith("https://www.bookvoed.ru/product/") for i in result.items)
    assert any("Гарри Поттер" in i.title for i in result.items)


def test_parse_queries_file():
    """queries.txt — список товаров, который можно править в блокноте."""
    import tempfile

    pf = importlib.import_module("price_finder")
    text = """
# комментарий
iphone 15 128gb ; 60000
ноутбук asus ; 45 000 ; 5
кофемашина | 25000 | 7 | bookvoed
наушники sony ; - ; - ; bookvoed
робот-пылесос
   # ещё комментарий
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "queries.txt"
        path.write_text(text, encoding="utf-8")
        entries = pf.parse_queries_file(path)

    assert len(entries) == 5, entries
    assert entries[0] == {"query": "iphone 15 128gb", "target_price": 60000.0,
                          "drop_pct": None, "sites": None}
    assert entries[1]["target_price"] == 45000.0 and entries[1]["drop_pct"] == 5.0   # пробел в цене
    assert entries[2]["sites"] == "bookvoed" and entries[2]["drop_pct"] == 7.0       # разделитель |
    assert entries[3]["query"] == "наушники sony" and entries[3]["target_price"] is None
    assert entries[3]["sites"] == "bookvoed"                                          # прочерк «-»
    assert entries[4] == {"query": "робот-пылесос", "target_price": None,
                          "drop_pct": None, "sites": None}


# --- 12. CLI: все команды на месте ------------------------------------------

def test_cli_commands_registered():
    """Новые команды (gui, env, notify-test, init-queries) должны быть в справке."""
    import subprocess

    result = subprocess.run([sys.executable, str(ROOT / "price_finder.py"), "--help"],
                            capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert result.returncode == 0, result.stderr
    for command in ("search", "watch", "history", "sites", "test-site", "targets",
                    "parse-price", "update-rates", "init-config", "init-queries",
                    "env", "notify-test", "gui", "serve-demo"):
        assert command in result.stdout, f"в справке нет команды {command}"

    # справка команды gui упоминает --selftest
    result2 = subprocess.run([sys.executable, str(ROOT / "price_finder.py"), "gui", "--help"],
                             capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert "--selftest" in result2.stdout


def test_cli_runs_without_optional_deps():
    """Без PyYAML, lxml и openpyxl поиск обязан работать (сценарий Android)."""
    import subprocess

    env = dict(os.environ, PRICEFINDER_YAMLITE="1", PRICEFINDER_HTML_PARSER="html.parser")
    result = subprocess.run(
        [sys.executable, str(ROOT / "price_finder.py"), "sites", "--no-color"],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT), env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "demo" in result.stdout and "bookvoed" in result.stdout


# --- runner ------------------------------------------------------------------

def main() -> int:
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]
    failed = 0
    for name, func in tests:
        try:
            func()
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: {type(exc).__name__}: {exc}")
    print(f"\n  {len(tests) - failed}/{len(tests)} тестов пройдено")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
