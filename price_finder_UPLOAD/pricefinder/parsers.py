"""Извлечение карточек товаров из HTML.

Четыре стратегии (пробуются по порядку, пока не дадут результат):
  1. css        — селекторы из конфига сайта (точный контроль);
  2. jsonld     — микроразметка schema.org в <script type="application/ld+json">;
  3. microdata  — разметка itemprop (schema.org в атрибутах);
  4. meta       — og:/product: мета-теги (страница одного товара).

Благодаря 2–4 программа работает на «любом сайте» даже без прописанных селекторов.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .price import Converter, Price, parse_price
from .sites import SiteConfig

# itemprop-атрибуты, по которым ищем цену
_PRICE_ITEMPROPS = ("price", "lowprice", "lowPrice", "highprice", "amount")


@dataclass
class Item:
    site_id: str
    site_name: str
    title: str = ""
    price: float | None = None          # в валюте сайта
    currency: str = "RUB"
    price_original: str = ""            # как написано на странице
    price_range_high: float | None = None
    url: str = ""
    image: str = ""
    seller: str = ""
    rating: float | None = None
    reviews: int | None = None
    availability: str = ""
    old_price: float | None = None
    source_url: str = ""                # URL страницы поиска
    strategy: str = ""
    normalized_price: float | None = None  # в базовой валюте
    matched_keywords: list[str] = field(default_factory=list)
    also_at: list[str] = field(default_factory=list)  # где ещё найдено такое же предложение

    @property
    def uid(self) -> str:
        """Стабильный идентификатор предложения: площадка + нормализованная ссылка.

        Цена в идентификатор не входит — иначе история цен рвалась бы при каждом
        изменении цены. Если ссылки нет, берётся нормализованное название.
        """
        basis = _url_identity(self.url) if self.url else _norm_title(self.title)
        return hashlib.sha1(f"{self.site_id}|{basis}".encode("utf-8", "ignore")).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "site": self.site_name,
            "site_id": self.site_id,
            "title": self.title,
            "price": self.price,
            "currency": self.currency,
            "price_text": self.price_original,
            "price_max": self.price_range_high,
            "normalized_price": self.normalized_price,
            "url": self.url,
            "image": self.image,
            "seller": self.seller,
            "rating": self.rating,
            "reviews": self.reviews,
            "availability": self.availability,
            "old_price": self.old_price,
            "strategy": self.strategy,
            "source_url": self.source_url,
            "also_at": ", ".join(self.also_at),
        }


# =========================================================================
#  Публичный API
# =========================================================================

def parse_items(
    html: str,
    site: SiteConfig,
    page_url: str,
    query: str = "",
    converter: Converter | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    query_keywords: list[str] | None = None,
    require_query_keyword: bool = False,
    include_keywords: Sequence[str] | None = None,
    exclude_keywords: Sequence[str] | None = None,
) -> tuple[list[Item], str]:
    """Возвращает (список карточек, имя сработавшей стратегии)."""
    converter = converter or Converter()
    if not html or not html.strip():
        return [], "empty"
    soup = BeautifulSoup(html, "lxml" if _has_lxml() else "html.parser")

    strategies: list[tuple[str, Any]] = []
    if site.product_selector or site.fields:
        strategies.append(("css", lambda: parse_by_css(soup, site, page_url)))
    strategies.append(("jsonld", lambda: parse_jsonld(soup, site, page_url)))
    strategies.append(("microdata", lambda: parse_microdata(soup, site, page_url)))
    strategies.append(("meta", lambda: parse_meta(soup, site, page_url)))

    for name, func in strategies:
        try:
            raw = func()
        except Exception:
            raw = []
        if not raw:
            continue
        items = clean_items(
            raw,
            site=site,
            page_url=page_url,
            strategy=name,
            converter=converter,
            min_price=min_price,
            max_price=max_price,
            query_keywords=query_keywords,
            require_query_keyword=require_query_keyword,
            include_keywords=include_keywords,
            exclude_keywords=exclude_keywords,
        )
        if items:
            return items, name
    return [], "none"


def _has_lxml() -> bool:
    """lxml ускоряет разбор HTML в 2-3 раза, но программа работает и без него.

    PRICEFINDER_HTML_PARSER=html.parser — принудительно использовать встроенный
    парсер (полезно для проверки переносимости на Android/Pydroid).
    """
    import os

    if os.environ.get("PRICEFINDER_HTML_PARSER", "").lower() in ("html.parser", "builtin", "stdlib"):
        return False
    try:
        import lxml  # noqa: F401

        return True
    except ImportError:
        return False


# =========================================================================
#  1. CSS-селекторы из конфига
# =========================================================================

def parse_by_css(soup: BeautifulSoup, site: SiteConfig, page_url: str) -> list[dict[str, Any]]:
    fields = site.fields or {}
    containers = soup.select(site.product_selector) if site.product_selector else []
    if not containers:
        if not fields.get("price"):
            return []
        # без контейнера пробуем собрать одну карточку со страницы
        containers = [soup]

    out: list[dict[str, Any]] = []
    for node in containers:
        rec: dict[str, Any] = {}
        for key in ("title", "price", "old_price", "url", "image", "seller", "rating", "reviews", "availability", "currency"):
            sel = fields.get(key)
            if not sel:
                continue
            value = _resolve_selector(node, sel, base_url=page_url, attr_hint=key)
            if value not in (None, ""):
                rec[key] = value
        if rec:
            out.append(rec)
    return out


def _resolve_selector(node: Any, spec: Any, base_url: str = "", attr_hint: str = "") -> Any:
    """Поддерживает: список селекторов, 'attr:href', 'regex:...', 'json:...', 'text'."""
    if isinstance(spec, (list, tuple)):
        for variant in spec:
            value = _resolve_selector(node, variant, base_url, attr_hint)
            if value not in (None, ""):
                return value
        return None

    spec = str(spec).strip()
    if not spec:
        return None

    if spec.startswith("json:"):
        return _resolve_json_path(node, spec[5:].strip())
    if spec.startswith("regex:"):
        return _resolve_regex(node, spec[6:].strip())
    if spec.startswith("min:") or spec.startswith("max:") or spec.startswith("first:"):
        mode, _, rest = spec.partition(":")
        value = _resolve_selector(node, rest.strip(), base_url, attr_hint)
        if isinstance(value, list):
            return {"mode": mode, "values": value}
        return value
    if spec.startswith("text:"):
        sel = spec[5:].strip()
        el = node.select_one(sel) if sel else node
        return _clean_text(el.get_text(" ", strip=True)) if el is not None else None
    if spec.startswith("html:"):
        el = node.select_one(spec[5:].strip())
        return str(el) if el is not None else None
    if spec.startswith("attr:"):
        attr = spec[5:].strip()
        return _first_attr(node, attr, base_url)

    # обычный CSS-селектор
    els = node.select(spec) if hasattr(node, "select") else []
    if not els:
        return None
    if attr_hint == "url":
        return _pick_url(els, base_url)
    if attr_hint == "image":
        return _pick_image(els, base_url)
    if attr_hint in ("rating", "reviews"):
        for el in els:
            style = el.get("style") or ""
            m = re.search(r"width:\s*([\d.]+)%", style)
            if m and attr_hint == "rating":
                return float(m.group(1)) / 20.0
            for a in ("content", "data-rating", "data-value", "title"):
                if el.get(a):
                    return el[a]
            txt = _clean_text(el.get_text(" ", strip=True))
            if txt:
                return txt
        return None
    if attr_hint in ("price", "old_price", "currency"):
        # собираем все текстовые кандидаты: видимый текст важнее атрибута content
        candidates: list[str] = []
        for el in els:
            txt = _clean_text(el.get_text(" ", strip=True))
            if txt:
                candidates.append(txt)
            if el.get("content"):
                candidates.append(str(el["content"]))
        return candidates if candidates else None
    for el in els:
        txt = _clean_text(el.get_text(" ", strip=True))
        if txt:
            return txt
    return None


def _first_attr(node: Any, attr: str, base_url: str) -> Any:
    candidates = [node, *getattr(node, "select", lambda *_: [])("*")]
    for el in candidates:
        val = el.get(attr)
        if val:
            if attr in ("href", "src"):
                return urljoin(base_url, str(val).strip())
            return str(val).strip()
    return None


def _pick_url(els: Sequence[Any], base_url: str) -> str | None:
    for el in els:
        for attr in ("href", "data-href", "data-url", "data-link"):
            if el.get(attr):
                return urljoin(base_url, str(el[attr]).strip())
        found = el.select_one("a[href]")
        if found:
            return urljoin(base_url, str(found["href"]).strip())
    return None


def _pick_image(els: Sequence[Any], base_url: str) -> str | None:
    for el in els:
        for attr in ("src", "data-src", "data-original", "srcset"):
            if el.get(attr):
                value = str(el[attr]).split(",")[0].split(" ")[0].strip()
                return urljoin(base_url, value)
    return None


def _resolve_json_path(node: Any, path: str) -> Any:
    """'json:window.state' / 'json:#data-script' — данные из <script>."""
    scripts: Iterable[Any] = []
    if path.startswith("#"):
        el = node.select_one(path) if hasattr(node, "select_one") else None
        scripts = [el] if el else []
    else:
        scripts = node.select("script:not([src])") if hasattr(node, "select") else []
    token = None if path.startswith("#") else path.split(".")[-1]
    for sc in scripts:
        if sc is None:
            continue
        text = sc.get_text(" ", strip=False) or ""
        if token and token not in text:
            continue
        data = _extract_json(text, token)
        if data is not None:
            return json.dumps(data, ensure_ascii=False)
    return None


def _extract_json(text: str, token: str | None) -> Any:
    if token:
        m = re.search(re.escape(token) + r"\s*=\s*", text)
        if m:
            start = m.end()
            return _json_at(text, start)
    for m in re.finditer(r"[\{\[]", text):
        value = _json_at(text, m.start())
        if isinstance(value, (dict, list)):
            return value
    return None


def _json_at(text: str, start: int) -> Any:
    if start >= len(text) or text[start] not in "{[":
        return None
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _resolve_regex(node: Any, pattern: str) -> Any:
    text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else str(node)
    try:
        m = re.search(pattern, text)
    except re.error:
        return None
    if not m:
        return None
    if m.groups():
        return m.group(1)
    return m.group(0)


# =========================================================================
#  2. JSON-LD (schema.org)
# =========================================================================

def parse_jsonld(soup: BeautifulSoup, site: SiteConfig, page_url: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/(?:ld\+)?json", re.I)}):
        text = script.get_text(strip=False) or ""
        if not text.strip():
            continue
        for data in _iter_json_blocks(text):
            out.extend(_items_from_jsonld(data, page_url))
    return out


def _iter_json_blocks(text: str) -> Iterable[Any]:
    try:
        yield json.loads(text)
        return
    except json.JSONDecodeError:
        pass
    # частая проблема: несколько JSON-объектов подряд или мусор вокруг
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx] not in "{[":
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        yield obj
        idx = end


def _items_from_jsonld(data: Any, page_url: str) -> list[dict[str, Any]]:
    nodes = _flatten_jsonld(data)
    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("@id"), str):
            by_id[node["@id"]] = node

    def resolve(ref: Any) -> dict[str, Any] | None:
        if isinstance(ref, dict):
            return ref
        if isinstance(ref, str) and ref in by_id:
            return by_id[ref]
        return None

    results: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        types = _types_of(node)
        if "ItemList" in types or "OfferCatalog" in types:
            for elem in node.get("itemListElement") or []:
                if not isinstance(elem, dict):
                    continue
                product = resolve(elem.get("item")) or elem
                item = _product_to_rec(product, resolve)
                if item:
                    item.setdefault("url", elem.get("url") or "")
                    results.append(item)
        elif "Product" in types:
            item = _product_to_rec(node, resolve)
            if item:
                results.append(item)
        elif "Offer" in types and not any("Product" in _types_of(n) for n in nodes if isinstance(n, dict)):
            rec = _offer_to_rec(node, resolve)
            if rec:
                results.append(rec)

    for rec in results:
        if rec.get("url"):
            rec["url"] = urljoin(page_url, str(rec["url"]))
        if rec.get("image"):
            rec["image"] = urljoin(page_url, str(rec["image"]))
    return results


def _flatten_jsonld(data: Any) -> list[Any]:
    out: list[Any] = []
    if isinstance(data, list):
        for elem in data:
            out.extend(_flatten_jsonld(elem))
    elif isinstance(data, dict):
        out.append(data)
        graph = data.get("@graph")
        if graph is not None:
            out.extend(_flatten_jsonld(graph))
    return out


def _types_of(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type") or node.get("type") or []
    if isinstance(raw, str):
        raw = [raw]
    return {str(t).split(":")[-1] for t in raw if isinstance(t, (str, int))}


def _product_to_rec(product: Any, resolve) -> dict[str, Any] | None:
    product = resolve(product)
    if not isinstance(product, dict):
        return None
    rec: dict[str, Any] = {
        "title": _first_str(product.get("name"), product.get("title")),
        "url": _first_str(product.get("url"), product.get("@id")),
        "image": _image_of(product.get("image")),
        "rating": _rating_of(product.get("aggregateRating")),
        "reviews": _reviews_of(product.get("aggregateRating")),
        "seller": _seller_of(product.get("brand"), product.get("seller")),
    }
    offers = product.get("offers") or product.get("offer")
    offer_recs: list[dict[str, Any]] = []
    if isinstance(offers, list):
        for offer in offers:
            r = _offer_to_rec(offer, resolve)
            if r:
                offer_recs.append(r)
    elif offers is not None:
        r = _offer_to_rec(offers, resolve)
        if r:
            offer_recs.append(r)

    if offer_recs:
        best = min(
            offer_recs,
            key=lambda r: _num(r.get("price")) if _num(r.get("price")) is not None else float("inf"),
        )
        rec.update(best)
    return rec if rec.get("title") or rec.get("price") else None


def _offer_to_rec(offer: Any, resolve) -> dict[str, Any] | None:
    offer = resolve(offer)
    if not isinstance(offer, dict):
        return None
    types = _types_of(offer)
    rec: dict[str, Any] = {}
    if "AggregateOffer" in types:
        rec["price"] = offer.get("lowPrice") or offer.get("price")
        rec["old_price"] = offer.get("highPrice")
        rec["is_range"] = bool(offer.get("lowPrice") and offer.get("highPrice"))
    else:
        spec = offer.get("priceSpecification")
        rec["price"] = offer.get("price") or (spec.get("price") if isinstance(spec, dict) else None)
    spec = offer.get("priceSpecification")
    rec["currency"] = _first_str(offer.get("priceCurrency")) or (
        _first_str(spec.get("priceCurrency")) if isinstance(spec, dict) else ""
    )
    rec["availability"] = _availability_of(offer.get("availability"))
    rec["url"] = rec.get("url") or _first_str(offer.get("url"))
    rec["seller"] = rec.get("seller") or _seller_of(offer.get("seller"))
    offered = offer.get("itemOffered")
    rec["title"] = rec.get("title") or _first_str(
        offer.get("name"), offered.get("name") if isinstance(offered, dict) else None
    )
    return {k: v for k, v in rec.items() if v not in (None, "")} or None


def _image_of(image: Any) -> str:
    if isinstance(image, str):
        return image
    if isinstance(image, list) and image:
        return _image_of(image[0])
    if isinstance(image, dict):
        return str(image.get("url") or image.get("contentUrl") or "")
    return ""


def _rating_of(rating: Any) -> float | None:
    if isinstance(rating, dict):
        value = _num(rating.get("ratingValue"))
        return value
    if isinstance(rating, (int, float, str)):
        return _num(rating)
    return None


def _reviews_of(rating: Any) -> int | None:
    if isinstance(rating, dict):
        value = _num(rating.get("reviewCount") or rating.get("ratingCount"))
        return int(value) if value is not None else None
    return None


def _seller_of(*candidates: Any) -> str:
    for cand in candidates:
        if isinstance(cand, str) and cand:
            return cand
        if isinstance(cand, dict):
            name = cand.get("name")
            if name:
                return str(name)
        if isinstance(cand, list) and cand:
            name = _seller_of(cand[0])
            if name:
                return name
    return ""


def _availability_of(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    low = text.lower()
    if "instock" in low or "in_stock" in low:
        return "в наличии"
    if "outofstock" in low:
        return "нет в наличии"
    if "preorder" in low:
        return "предзаказ"
    return text.rstrip("/").split("/")[-1]


def _first_str(*values: Any) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)):
            return str(v)
    return ""


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        p = parse_price(value, prefer_low=True)
        return p.amount if p else None
    return None


# =========================================================================
#  3. Microdata (itemprop)
# =========================================================================

def parse_microdata(soup: BeautifulSoup, site: SiteConfig, page_url: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    product_nodes = soup.find_all(attrs={"itemprop": "itemListElement"}) or soup.find_all(
        attrs={"itemtype": re.compile(r"schema\.org/Product", re.I)}
    )
    if not product_nodes:
        # страница одной oferty: ищем itemprop=price
        price_nodes = [n for n in soup.find_all(attrs={"itemprop": re.compile("price|lowPrice", re.I)})]
        if price_nodes:
            product_nodes = [_climb_to_product(n) for n in price_nodes]
    for node in product_nodes:
        if node is None:
            continue
        rec = _microdata_rec(node, page_url)
        if rec:
            results.append(rec)
    return results


def _climb_to_product(node: Any) -> Any:
    current = node
    for _ in range(8):
        parent = current.parent
        if parent is None:
            break
        itemtype = str(parent.get("itemtype") or "")
        if "Product" in itemtype or "Offer" in itemtype:
            return parent
        if parent.find(attrs={"itemprop": ["name", "title"]}):
            return parent
        current = parent
    return node.parent


def _microdata_rec(node: Any, page_url: str) -> dict[str, Any] | None:
    def prop(name: str, attr: str | None = None, tag: str | None = None) -> Any:
        el = (
            node.find(tag or True, attrs={"itemprop": name})
            if hasattr(node, "find")
            else None
        )
        if el is None:
            return None
        if attr:
            return el.get(attr)
        if el.name in ("link", "meta", "image"):
            # пустые элементы: значение лежит в атрибуте
            return el.get("href") or el.get("content") or el.get("src")
        if el.get("content"):
            return el["content"]
        return el.get_text(" ", strip=True)

    title = prop("name") or prop("title")
    price = prop("price") or prop("lowPrice") or prop("amount")
    price_el = node.find(True, attrs={"itemprop": re.compile("price|lowPrice", re.I)}) if hasattr(node, "find") else None
    if price is None and price_el is not None:
        price = price_el.get("content") or price_el.get_text(" ", strip=True)
    currency = prop("priceCurrency")
    link = prop("url", "href") or prop("url")
    image = prop("image", "src") or prop("image")
    availability = prop("availability", "href") or prop("availability")
    if not title and not price:
        return None
    if isinstance(link, list):
        link = link[0]
    rec = {
        "title": _clean_text(str(title)) if title else "",
        "price": [str(price)] if price else None,
        "currency": str(currency) if currency else None,
        "url": urljoin(page_url, str(link).strip()) if link else "",
        "image": urljoin(page_url, str(image).strip()) if image else "",
        "availability": _availability_of(availability),
        "seller": _clean_text(str(prop("seller") or "")),
    }
    return {k: v for k, v in rec.items() if v not in (None, "", [])}


# =========================================================================
#  4. Мета-теги (страница одного товара)
# =========================================================================

def parse_meta(soup: BeautifulSoup, site: SiteConfig, page_url: str) -> list[dict[str, Any]]:
    def meta(*names: str) -> str:
        for name in names:
            el = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if el and el.get("content"):
                return str(el["content"]).strip()
        return ""

    title = meta("og:title", "twitter:title", "product:plural_title") or (
        soup.title.get_text(strip=True) if soup.title else ""
    )
    price = meta(
        "product:price:amount",
        "og:price:amount",
        "twitter:data1",
        "product:sale_price:amount",
        "price",
    )
    currency = meta("product:price:currency", "og:price:currency", "product:sale_price:currency")
    if not price:
        return []
    link = meta("og:url") or page_url
    image = meta("og:image", "twitter:image")
    return [
        {
            "title": title,
            "price": [price],
            "currency": currency or None,
            "url": urljoin(page_url, link),
            "image": urljoin(page_url, image) if image else "",
            "availability": meta("product:availability", "og:availability"),
        }
    ]


# =========================================================================
#  Очистка / фильтрация / нормализация
# =========================================================================

def clean_items(
    raw_items: Iterable[dict[str, Any]],
    *,
    site: SiteConfig,
    page_url: str,
    strategy: str,
    converter: Converter,
    min_price: float | None = None,
    max_price: float | None = None,
    query_keywords: Sequence[str] | None = None,
    require_query_keyword: bool = False,
    include_keywords: Sequence[str] | None = None,
    exclude_keywords: Sequence[str] | None = None,
) -> list[Item]:
    min_price = _first_not_none(min_price, site.min_price)
    max_price = _first_not_none(max_price, site.max_price)
    banned = list(dict.fromkeys([*site.exclude_keywords, *(exclude_keywords or [])]))
    required = list(dict.fromkeys([*site.include_keywords, *(include_keywords or [])]))

    items: list[Item] = []
    for raw in raw_items:
        item = _build_item(raw, site=site, page_url=page_url, strategy=strategy, converter=converter)
        if item is None:
            continue
        if min_price is not None and item.price is not None and item.price < float(min_price):
            continue
        if max_price is not None and item.price is not None and item.price > float(max_price):
            continue
        title_low = item.title.lower()
        if banned and any(kw in title_low for kw in banned):
            continue
        if required and not any(kw in title_low for kw in required):
            continue
        if require_query_keyword:
            matched = [kw for kw in (query_keywords or []) if kw in title_low]
            if not matched:
                continue
            item.matched_keywords = matched
        items.append(item)

    deduped = _dedupe(items)
    deduped.sort(key=lambda it: (it.normalized_price if it.normalized_price is not None else float("inf")))
    return deduped


def _build_item(
    raw: dict[str, Any],
    *,
    site: SiteConfig,
    page_url: str,
    strategy: str,
    converter: Converter,
) -> Item | None:
    default_cur = (raw.get("currency") or site.currency or converter.base or "RUB").upper()
    price_value = _pick_price(raw.get("price"), default_cur)
    if price_value is None:
        return None
    title = _clean_text(str(raw.get("title") or "")).strip(" \t\n-–—|")
    if len(title) < 2:
        title = _title_from_url(raw.get("url") or page_url) or title
    if not title:
        return None

    item = Item(
        site_id=site.id,
        site_name=site.name or site.id,
        title=title[:400],
        price=price_value.amount,
        currency=price_value.currency,
        price_original=price_value.original[:80],
        price_range_high=price_value.high,
        url=normalize_url(str(raw.get("url") or ""), page_url),
        image=normalize_url(str(raw.get("image") or ""), page_url),
        seller=_clean_text(str(raw.get("seller") or ""))[:120],
        rating=_to_float(raw.get("rating")),
        reviews=int(_to_float(raw.get("reviews")) or 0) or None,
        availability=_clean_text(str(raw.get("availability") or ""))[:40],
        old_price=_pick_price(raw.get("old_price"), default_cur).amount
        if raw.get("old_price") and _pick_price(raw.get("old_price"), default_cur)
        else None,
        source_url=page_url,
        strategy=strategy,
    )
    item.normalized_price = converter.convert_price(price_value)
    return item


def _pick_price(value: Any, default_cur: str) -> Price | None:
    """Достаёт цену из значения поля.

    Поддерживает режимы из конфига: {"mode": "min|max|first", "values": [...]}.
    По умолчанию берётся минимальное число — для пар «старая/новая цена» в одном
    контейнере это обычно реальная (низкая) цена.
    """
    if value is None:
        return None
    mode = "min"
    if isinstance(value, dict) and "values" in value:
        mode = str(value.get("mode") or "min")
        value = value["values"]

    if isinstance(value, (list, tuple)):
        candidates = [str(v) for v in value if v not in (None, "")]
    else:
        candidates = [str(value)]

    parsed: list[Price] = []
    for cand in candidates:
        price = parse_price(cand, default_currency=default_cur)
        if price and price.amount > 0:
            parsed.append(price)
    if not parsed:
        return None
    if mode == "max":
        return max(parsed, key=lambda p: p.amount)
    if mode == "first":
        return parsed[0]
    # «min» (по умолчанию). Одно число разбилось на части ("12 345,67" -> 12345 и 67) —
    # берём первое; иначе в контейнере несколько цен (новая + зачёркнутая) — берём меньшую.
    if len(parsed) >= 2 and parsed[0].amount > parsed[1].amount:
        return parsed[0]
    return min(parsed, key=lambda p: p.amount)


def dedupe_items(items: Sequence[Item]) -> list[Item]:
    """Публичная обёртка: убирает повторы (нужно при склейке нескольких страниц)."""
    return _dedupe(items)


def _dedupe(items: Sequence[Item]) -> list[Item]:
    """Убирает повторы внутри одной площадки (тот же URL или «название + цена»)."""
    seen: set[tuple[str, str]] = set()
    out: list[Item] = []
    for it in items:
        url_key = re.sub(r"https?://(www\.)?", "", it.url).rstrip("/") if it.url else ""
        title_key = re.sub(r"[^0-9a-zа-яё]+", " ", it.title.lower()).strip()
        marker = (it.site_id, url_key or f"{title_key}|{it.price}")
        if marker in seen:
            continue
        seen.add(marker)
        out.append(it)
    return out


def _url_identity(url: str) -> str:
    """URL без схемы, www и utm-меток — чтобы http/https и зеркала не плодили дубли."""
    text = re.sub(r"^https?://", "", (url or "").strip().lower())
    text = re.sub(r"^www\.", "", text)
    return text.rstrip("/")


def _norm_title(title: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", " ", (title or "").lower()).strip()


def merge_same_offers(items: Sequence[Item]) -> list[Item]:
    """Схлопывает одинаковые товары с ОДИНАКОВОЙ ценой, найденные на разных площадках.

    Разные цены не объединяются — иначе потерялся бы смысл сравнения.
    В выдаче остаётся одно предложение, остальные площадки попадают в also_at
    (в таблице отображается как «Площадка +1»).
    """
    merged: dict[str, Item] = {}
    order: list[str] = []
    for it in items:
        price = it.normalized_price if it.normalized_price is not None else (it.price or 0.0)
        key = f"{_norm_title(it.title)}|{round(float(price), 2)}"
        if key not in merged:
            merged[key] = _clone(it)
            order.append(key)
            continue
        current = merged[key]
        cheaper = float(price) < float(current.normalized_price or current.price or 0.0)
        if cheaper:
            sites = [current.site_name, *current.also_at, it.site_name]
            _copy_into(current, it)
        else:
            sites = [current.site_name, *current.also_at, it.site_name]
        current.also_at = [s for s in dict.fromkeys(x for x in sites if x) if s != current.site_name]
    result = [merged[k] for k in order]
    result.sort(key=lambda i: (i.normalized_price if i.normalized_price is not None else float("inf")))
    return result


def _clone(item: Item) -> Item:
    clone = Item(**{name: getattr(item, name) for name in item.__dataclass_fields__})
    clone.also_at = []
    return clone


def _copy_into(target: Item, source: Item) -> None:
    for name in ("site_id", "site_name", "price", "currency", "price_original", "url", "image",
                 "seller", "rating", "reviews", "availability", "normalized_price", "strategy",
                 "source_url"):
        setattr(target, name, getattr(source, name))


def normalize_url(url: str, base: str = "") -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if base:
        url = urljoin(base, url)
    try:
        parts = urlsplit(url)
        if not parts.scheme:
            return url
        query = "&".join(
            p for p in parts.query.split("&") if p and not p.lower().startswith(("utm_", "yclid", "gclid"))
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except ValueError:
        return url


def _title_from_url(url: str) -> str:
    if not url:
        return ""
    path = urlsplit(url).path.strip("/").split("/")[-1]
    return re.sub(r"[-_]+", " ", re.sub(r"\.\w+$", "", path)).strip()


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", str(text).replace("\u00a0", " "))
    return text.strip()


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ".").strip())
    except ValueError:
        match = re.search(r"[\d.,]+", str(value))
        if match:
            try:
                return float(match.group(0).replace(",", "."))
            except ValueError:
                return None
        return None


def _first_not_none(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


# =========================================================================
#  Сводная статистика по результатам поиска
# =========================================================================

def summarize(items: Sequence[Item]) -> dict[str, Any]:
    prices = [it.normalized_price for it in items if it.normalized_price is not None]
    if not prices:
        return {"count": 0}
    low, high = min(prices), max(prices)
    median = statistics.median(prices)
    per_site: dict[str, dict[str, Any]] = {}
    for it in items:
        st = per_site.setdefault(
            it.site_name, {"count": 0, "min": float("inf"), "max": 0.0, "currency": it.currency}
        )
        st["count"] += 1
        value = it.normalized_price or 0.0
        st["min"] = min(st["min"], value)
        st["max"] = max(st["max"], value)
    return {
        "count": len(items),
        "min": low,
        "max": high,
        "median": median,
        "avg": round(sum(prices) / len(prices), 2),
        "sites": per_site,
        "spread_pct": round((high - low) / low * 100, 1) if low else 0.0,
    }
