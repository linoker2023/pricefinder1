#!/usr/bin/env python3
"""Локальный демо-магазин для проверки парсера (без интернета).

Запуск:
    python tests/demo_server.py --port 8765
    python price_finder.py search "ноутбук" --sites demo

Отдаёт три типа страниц, чтобы покрыть все стратегии парсинга:
    /search?q=...   — листинг: карточки с CSS-классами + JSON-LD ItemList
    /product/<id>   — страница товара: microdata (itemprop) + og:/product: мета-теги
    /search2?q=...  — «сложный» листинг: цены только в JSON внутри <script>
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRODUCTS = [
    # (id, название, цена, старая цена, валюта, продавец, рейтинг, отзывы, категория, наличие)
    (1, "Ноутбук ASUS VivoBook 15 X515, 16 ГБ, SSD 512 ГБ", 42990, 54990, "RUB", "ASUS Store", 4.7, 312, "ноутбук", True),
    (2, "Ноутбук Lenovo IdeaPad 3 15ADA6, 8 ГБ, SSD 256 ГБ", 31490, 37990, "RUB", "ТехноСклад", 4.4, 187, "ноутбук", True),
    (3, "Ноутбук Apple MacBook Air 13 M2 256GB", 89990, 99990, "RUB", "iShop", 4.9, 540, "ноутбук макбук apple", True),
    (4, "Ноутбук HP 15s-eq2000, 8 ГБ, SSD 512 ГБ (уценённый)", 24990, 33990, "RUB", "Дисконт-Центр", 4.1, 45, "ноутбук", True),
    (5, "Смартфон Xiaomi Redmi Note 13 8/256 ГБ", 15990, 19990, "RUB", "MiStore", 4.6, 823, "смартфон телефон xiaomi", True),
    (6, "Смартфон Samsung Galaxy A55 8/256 ГБ", 27490, 32990, "RUB", "Samsung Official", 4.5, 401, "смартфон телефон samsung", True),
    (7, "Смартфон Apple iPhone 15 128 ГБ", 62990, 74990, "RUB", "iShop", 4.8, 1204, "смартфон телефон iphone apple", True),
    (8, "Смартфон Apple iPhone 15 128 ГБ (витринный образец)", 51990, None, "RUB", "Дисконт-Центр", 4.2, 12, "смартфон телефон iphone apple", False),
    (9, "Кофемашина DeLonghi Magnifica S ECAM 22.110", 33990, 41990, "RUB", "Coffee House", 4.7, 268, "кофемашина кофеварка", True),
    (10, "Кофемашина Philips Series 2200 EP2220/10", 27990, 34990, "RUB", "ТехноСклад", 4.4, 156, "кофемашина кофеварка", True),
    (11, "Шуруповёрт Bosch GSR 120-LI 2x2.0Ач", 7890, 9990, "RUB", "ИнструментПро", 4.8, 94, "шуруповёрт дрель bosch", True),
    (12, "Шуруповёрт Интерскол ДА-10/12М2", 3490, 4290, "RUB", "СтройБаза", 4.3, 61, "шуруповёрт дрель", True),
    (13, "Телевизор LG 55UR7800 55\" 4K", 41990, 52990, "RUB", "LG Store", 4.6, 233, "телевизор tv lg", True),
    (14, "Игровая приставка Sony PlayStation 5 Slim 1TB", 47990, 56990, "RUB", "GameZone", 4.9, 812, "playstation ps5 приставка sony", True),
    (15, "Игровая приставка Sony PlayStation 5 Slim (б/у)", 38990, None, "RUB", "Частный продавец", 4.0, 3, "playstation ps5 приставка sony", True),
    (16, "Видеокарта NVIDIA GeForce RTX 4070 12 ГБ Palit", 58990, 67990, "RUB", "ТехноСклад", 4.7, 143, "видеокарта rtx 4070 nvidia", True),
    (17, "Видеокарта NVIDIA GeForce RTX 4070 SUPER 12 ГБ", 71990, 79990, "RUB", "GameZone", 4.8, 76, "видеокарта rtx 4070 super nvidia", True),
    (18, "Робот-пылесос Xiaomi Robot Vacuum S10+", 21990, 27990, "RUB", "MiStore", 4.5, 358, "пылесос xiaomi", True),
    (19, "Наушники Sony WH-1000XM5 чёрные", 26990, 33990, "RUB", "Sony Store", 4.8, 492, "наушники sony", True),
    (20, "Наушники Apple AirPods Pro 2 USB-C", 18990, 22990, "RUB", "iShop", 4.7, 655, "наушники airpods apple", True),
]

CSS_PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>ДемоМаркет — поиск: {q}</title></head>
<body>
<div class="catalog">
{cards}
</div>
<script type="application/ld+json">{jsonld}</script>
</body></html>"""

CARD = """
  <div class="product-card" data-id="{pid}">
    <a class="product-card__link" href="/product/{pid}">
      <img class="product-card__img" src="/img/{pid}.jpg" alt="{title}">
      <div class="product-card__title">{title}</div>
    </a>
    <div class="product-card__price-old">{old}</div>
    <div class="product-card__price">{price}&nbsp;₽</div>
    <div class="product-card__seller">{seller}</div>
    <div class="product-card__rating" data-value="{rating}">{rating} ({reviews})</div>
    <div class="product-card__stock">{stock}</div>
  </div>"""

PRODUCT_PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>{title} — купить в ДемоМаркет</title>
<meta property="og:title" content="{title}">
<meta property="og:url" content="http://127.0.0.1:{port}/product/{pid}">
<meta property="og:image" content="http://127.0.0.1:{port}/img/{pid}.jpg">
<meta property="product:price:amount" content="{price_num}">
<meta property="product:price:currency" content="RUB">
<meta property="product:availability" content="{availability_meta}">
</head>
<body itemscope itemtype="https://schema.org/Product">
  <h1 itemprop="name">{title}</h1>
  <img itemprop="image" src="/img/{pid}.jpg" alt="{title}">
  <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
    <span itemprop="price" content="{price_num}">{price}&nbsp;₽</span>
    <meta itemprop="priceCurrency" content="RUB">
    <link itemprop="availability" href="https://schema.org/{availability_schema}">
    <span itemprop="seller">{seller}</span>
  </div>
  <div itemprop="aggregateRating" itemscope itemtype="https://schema.org/AggregateRating">
    <span itemprop="ratingValue">{rating}</span>
    <span itemprop="reviewCount">{reviews}</span>
  </div>
</body></html>"""

SCRIPT_PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>ДемоМаркет JS — {q}</title></head>
<body>
<div id="app"></div>
<script>
  window.__STATE__ = {state};
</script>
<script type="application/ld+json">
{jsonld}
</script>
</body></html>"""


def money(value: int | None) -> str:
    if value is None:
        return ""
    return f"{value:,}".replace(",", "\u00a0")


def search_products(query: str) -> list[tuple]:
    tokens = [t for t in re.split(r"[\s\-]+", query.lower()) if len(t) >= 3]
    found = []
    for row in PRODUCTS:
        haystack = row[1].lower() + " " + row[8].lower()
        if not tokens or any(t in haystack for t in tokens):
            found.append(row)
    return found


def build_jsonld(rows: list[tuple], port: int) -> str:
    elements = []
    for row in rows:
        pid, title, price, old, cur, seller, rating, reviews, _cats, stock = row
        offer: dict = {
            "@type": "Offer",
            "url": f"http://127.0.0.1:{port}/product/{pid}",
            "priceCurrency": cur,
            "price": price,
            "availability": "https://schema.org/InStock" if stock else "https://schema.org/OutOfStock",
            "seller": {"@type": "Organization", "name": seller},
        }
        if old:
            offer["priceSpecification"] = {"@type": "PriceSpecification", "price": old, "priceCurrency": cur}
        elements.append({
            "@type": "ListItem",
            "position": len(elements) + 1,
            "item": {
                "@type": "Product",
                "name": title,
                "image": f"http://127.0.0.1:{port}/img/{pid}.jpg",
                "url": f"http://127.0.0.1:{port}/product/{pid}",
                "aggregateRating": {"@type": "AggregateRating", "ratingValue": rating, "reviewCount": reviews},
                "offers": offer,
            },
        })
    return json.dumps({"@context": "https://schema.org", "@type": "ItemList", "itemListElement": elements},
                      ensure_ascii=False)


PRICE_SCALE = 1.0   # меняется флагом --scale: имитация падения/роста цен


class Handler(BaseHTTPRequestHandler):
    server_version = "DemoMarket/1.0"

    def log_message(self, fmt, *fmt_args):  # тише в консоли
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *fmt_args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        query = (params.get("q") or ["товар"])[0]
        port = self.server.server_address[1]  # type: ignore[attr-defined]
        try:
            mult = float((params.get("mult") or ["1"])[0])
        except ValueError:
            mult = 1.0
        mult *= PRICE_SCALE
        rows = [
            (r[0], r[1], int(round(r[2] * mult)), int(round(r[3] * mult)) if r[3] else None, *r[4:])
            for r in search_products(query)
        ]

        if parsed.path == "/":
            body = ("<html><body><h1>ДемоМаркет</h1><p>Поиск: /search?q=ноутбук · "
                    "Карточка: /product/1 · JS-вариант: /search2?q=ноутбук</p>"
                    f"<p>Товаров в базе: {len(PRODUCTS)}</p></body></html>")
            self._send(200, body)
        elif parsed.path == "/search":
            cards = []
            for row in rows:
                pid, title, price, old, cur, seller, rating, reviews, _cats, stock = row
                cards.append(CARD.format(
                    pid=pid, title=title, price=money(price), old=money(old) + (" ₽" if old else ""),
                    seller=seller, rating=rating, reviews=reviews,
                    stock="В наличии" if stock else "Нет в наличии",
                ))
            body = CSS_PAGE.format(q=query, cards="\n".join(cards), jsonld=build_jsonld(rows, port))
            self._send(200, body)
        elif parsed.path == "/search2":
            state = {
                "search": {
                    "query": query,
                    "items": [
                        {
                            "id": r[0], "title": r[1], "price": r[2], "oldPrice": r[3],
                            "currency": r[4], "seller": r[5], "rating": r[6], "reviews": r[7],
                            "url": f"/product/{r[0]}",
                        }
                        for r in rows
                    ],
                }
            }
            body = SCRIPT_PAGE.format(q=query, state=json.dumps(state, ensure_ascii=False),
                                      jsonld=build_jsonld(rows, port))
            self._send(200, body)
        elif parsed.path.startswith("/product/"):
            pid = int(parsed.path.rsplit("/", 1)[-1] or 0)
            row = next((r for r in PRODUCTS if r[0] == pid), None)
            if row is None:
                self._send(404, "<html><body>Не найдено</body></html>")
                return
            _pid, title, price, old, cur, seller, rating, reviews, _cats, stock = row
            body = PRODUCT_PAGE.format(
                title=title, pid=pid, price=money(price), price_num=price, port=port,
                seller=seller, rating=rating, reviews=reviews,
                availability_meta="in stock" if stock else "out of stock",
                availability_schema="InStock" if stock else "OutOfStock",
            )
            self._send(200, body)
        elif parsed.path == "/robots.txt":
            self._send(200, "User-agent: *\nAllow: /\n", content_type="text/plain")
        else:
            self._send(404, "<html><body>Не найдено</body></html>")

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальный демо-магазин для pricefinder")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="множитель всех цен (например 0.8 — имитация распродажи)")
    args = parser.parse_args()
    global PRICE_SCALE
    PRICE_SCALE = args.scale

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.verbose = not args.quiet  # type: ignore[attr-defined]
    print(f"ДемоМаркет запущен: http://{args.host}:{args.port}/search?q=ноутбук  (Ctrl+C — остановить)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
