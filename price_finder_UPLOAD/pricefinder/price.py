"""Парсинг цен и работа с валютами.

Умеет доставать цену из произвольного текста: "1 299,90 ₽", "US$ 1,299.00",
"от 500 до 700 руб.", "12\u00a0999\u202f₽", "1.299,00 €" и т.п.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# --- валюты ---------------------------------------------------------------

CURRENCY_CODES: dict[str, str] = {
    "RUB": "₽",
    "BYN": "Br",
    "KZT": "₸",
    "UAH": "₴",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "PLN": "zł",
    "TRY": "₺",
    "CNY": "¥",
    "JPY": "¥",
    "GEL": "₾",
    "UZS": "soʻm",
    "AMD": "֏",
    "AZN": "₼",
    "KGS": "с",
    "MDL": "L",
    "INR": "₹",
}

# Токен (нижний регистр) -> ISO-код
SYMBOL_TO_CODE: dict[str, str] = {
    "₽": "RUB",
    "руб": "RUB",
    "рублей": "RUB",
    "рубля": "RUB",
    "р": "RUB",
    "br": "BYN",
    "белруб": "BYN",
    "₸": "KZT",
    "тенге": "KZT",
    "тг": "KZT",
    "₴": "UAH",
    "грн": "UAH",
    "$": "USD",
    "usd": "USD",
    "доллар": "USD",
    "долларов": "USD",
    "€": "EUR",
    "eur": "EUR",
    "евро": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "zł": "PLN",
    "pln": "PLN",
    "₺": "TRY",
    "try": "TRY",
    "¥": "CNY",
    "cny": "CNY",
    "jpy": "JPY",
    "₾": "GEL",
    "gel": "GEL",
    "֏": "AMD",
    "amd": "AMD",
    "₼": "AZN",
    "azn": "AZN",
    "soʻm": "UZS",
    "uzs": "UZS",
    "с": "KGS",
    "kgs": "KGS",
    "l": "MDL",
    "mdl": "MDL",
    "₹": "INR",
    "inr": "INR",
}

_SYMBOLS = "₽₴₸₼₾֏€£$¥"
# Важно: длинные токены идут раньше коротких, иначе «Br» схлопнется до «р».
_WORDS = (
    r"бел\.?\s?руб\.?|рублей|рубля|руб\.?|долларов|доллар|грн\.?|тенге|soʻm|евро|"
    r"usd|eur|gbp|pln|try|cny|jpy|gel|amd|azn|uzs|kgs|mdl|inr|тг\.?|бел\.?|zł|\bbr\b|"
    r"\bр\b|\bс\b|\bl\b"
)
_CURRENCY_RE = re.compile(rf"(?:[{_SYMBOLS}]|(?:{_WORDS}))", re.IGNORECASE | re.UNICODE)

# Разделители групп разрядов, которые надо просто выкинуть
_THIN_SPACES = "\u00a0\u2007\u202f\u2009\u2002\u2003\u200b"
_SPACERS = f"[\\s{_THIN_SPACES}·'\u00b4`]"  # всё, что является просто разделителем

# Число с разделителями тысяч (пробел/апостроф) или десятичное (точка/запятая)
_NUM = (
    rf"\d{{1,3}}(?:[{_THIN_SPACES}\s'\u00b4]\d{{3}})+(?:[.,]\d{{1,2}})?"   # 1 299 / 12 345,67
    rf"|\d{{1,3}}(?:[.,]\d{{3}})+(?:[.,]\d{{1,2}})?"                        # 1,299 / 1.299,00
    rf"|\d+(?:[.,]\d{{1,2}})?"                                               # 999 / 1299,90
)

_RANGE_RE = re.compile(
    rf"(?:от|from)\s*?(?P<lo>{_NUM})[\s\S]{{0,40}}?(?:до|to|[-—–])\s*?(?P<hi>{_NUM})",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(rf"(?P<num>{_NUM})", re.UNICODE)


@dataclass
class Price:
    """Нормализованная цена."""

    amount: float
    currency: str = "RUB"
    original: str = ""
    is_range: bool = False
    high: float | None = None
    confidence: float = 1.0  # 1.0 — число рядом с символом валюты, 0.6 — просто число

    def format(self, symbol: str | None = None) -> str:
        sym = symbol if symbol is not None else CURRENCY_CODES.get(self.currency, self.currency)
        return f"{format_amount(self.amount)} {sym}".strip()

    def __str__(self) -> str:
        return self.format()


def format_amount(value: float | int | None) -> str:
    """1234567.5 -> '1 234 567,50' (русский стиль, разделитель тысяч — пробел)."""
    if value is None:
        return "—"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value == int(value):
        return f"{int(value):,}".replace(",", " ")
    int_part, dec_part = f"{value:,.2f}".split(".")
    return f"{int_part.replace(',', ' ')},{dec_part}"


def parse_price(
    text: str | None,
    default_currency: str = "RUB",
    prefer_low: bool = True,
) -> Price | None:
    """Достаёт цену из текста. Возвращает None, если чисел нет.

    prefer_low=True — для диапазона «от 500 до 700» возьмёт 500.
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    cleaned = raw.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")

    cur_match = _CURRENCY_RE.search(cleaned)
    currency = _currency_from_match(cur_match) if cur_match else None

    # диапазон «от X до Y»
    m = _RANGE_RE.search(cleaned)
    if m:
        lo = _to_float(m.group("lo"))
        hi = _to_float(m.group("hi"))
        if lo is not None and hi is not None and hi >= lo:
            return Price(
                amount=lo if prefer_low else hi,
                currency=currency or default_currency,
                original=raw,
                is_range=True,
                high=hi,
                confidence=0.9,
            )

    numbers: list[float] = []
    for m in _PRICE_RE.finditer(cleaned):
        value = _to_float(m.group("num"))
        if value is not None:
            numbers.append(value)
    if not numbers:
        return None

    amount = min(numbers) if prefer_low else numbers[0]
    return Price(
        amount=amount,
        currency=currency or default_currency,
        original=raw,
        confidence=1.0 if currency else 0.6,
    )


def _currency_from_match(match: re.Match[str]) -> str | None:
    token = match.group(0).strip().lower().rstrip(".")
    token = re.sub(r"\s+", "", token)
    if token.startswith("бел"):
        return "BYN"
    code = SYMBOL_TO_CODE.get(token)
    if code:
        return code
    # символ валюты может идти вместе с точкой/пробелом — пробуем первый символ
    return SYMBOL_TO_CODE.get(token[:1])


def _to_float(num: str | None) -> float | None:
    """'1 299,90' -> 1299.9; '1,299.00' -> 1299.0; '1.299,00' -> 1299.0"""
    if num is None:
        return None
    s = re.sub(_SPACERS, "", str(num))
    s = s.strip(".,-·' ")
    if not s or not re.search(r"\d", s):
        return None

    last_comma = s.rfind(",")
    last_dot = s.rfind(".")
    if last_comma != -1 and last_dot != -1:
        if last_comma > last_dot:  # "1.299,00"
            s = s.replace(".", "").replace(",", ".")
        else:  # "1,299.00"
            s = s.replace(",", "")
    elif last_comma != -1:
        tail = s[last_comma + 1 :]
        # "1,299" трактуем как разделитель тысяч, "1299,90" — как десятичную дробь
        s = s.replace(",", "") if re.fullmatch(r"\d{3}", tail) else s.replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


# --- конвертация валют ----------------------------------------------------


@dataclass
class Converter:
    """Пересчёт в базовую валюту по курсам из конфига."""

    base: str = "RUB"
    rates: dict[str, float] = field(default_factory=dict)  # код -> сколько base за 1 единицу

    def convert(self, amount: float, currency: str | None) -> float:
        if not currency or currency.upper() == self.base.upper():
            return amount
        rate = self.rates.get(currency.upper())
        if not rate:
            return amount  # курс неизвестен — сравниваем «как есть»
        return amount * rate

    def convert_price(self, price: Price) -> float:
        return round(self.convert(price.amount, price.currency), 2)

    def symbol(self, currency: str | None) -> str:
        if not currency:
            return CURRENCY_CODES.get(self.base, self.base)
        return CURRENCY_CODES.get(currency.upper(), currency)

    def unknown_currencies(self, prices: Iterable[Price]) -> list[str]:
        seen = {p.currency.upper() for p in prices if p.currency and p.currency.upper() != self.base.upper()}
        return sorted(c for c in seen if c not in self.rates)


# --- живые курсы валют -----------------------------------------------------

def fetch_live_rates(base: str = "RUB", timeout: float = 12.0) -> dict[str, float]:
    """Курсы к базовой валюте через open.er-api.com (без ключей и регистрации).

    API отдаёт «сколько иностранной валюты за 1 base», поэтому берём обратное.
    При любой ошибке возвращает пустой словарь — вызывающий код использует
    локальные курсы из конфига.
    """
    try:
        import requests

        resp = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=timeout)
        data = resp.json()
        if data.get("result") != "success":
            return {}
        out: dict[str, float] = {}
        for code, value in (data.get("rates") or {}).items():
            try:
                if float(value) > 0:
                    out[str(code).upper()] = round(1.0 / float(value), 6)
            except (TypeError, ValueError):
                continue
        return out
    except Exception:
        return {}
