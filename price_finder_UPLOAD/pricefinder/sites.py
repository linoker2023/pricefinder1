"""Загрузка и валидация конфигурации сайтов (config/sites.yaml)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import yamlite

try:  # PyYAML — если установлен; иначе работает встроенный мини-парсер (важно на Android)
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from . import paths

# Устаревшее имя оставлено для совместимости — всегда читайте config_search_paths()
DEFAULT_CONFIG_PATHS = paths.config_search_paths()


@dataclass
class SiteConfig:
    """Описание одного сайта-источника цен."""

    id: str
    name: str = ""
    enabled: bool = True
    search_url: str = ""                      # шаблон с {query}
    method: str = "GET"                       # GET | POST | JSON
    post_data: dict[str, Any] = field(default_factory=dict)
    query_param: str = "q"                    # для метода JSON
    page_param: str = "page"
    start_page: int = 1
    max_pages: int = 1
    product_selector: str = ""                # контейнер карточки товара
    fields: dict[str, str] = field(default_factory=dict)
    link_absolute: str = ""                   # базовый URL для относительных ссылок
    currency: str = "RUB"                     # валюта сайта по умолчанию
    currency_selector: str = ""
    static: bool = False                      # страница-листинг без поиска
    sort_by_price_url: str = ""               # готовый URL, уже отсортированный по цене
    js_render: bool = False                   # нужен браузер (Playwright)
    render_wait: float = 2.5
    wait_selector: str = ""
    delay: float = 1.0                        # пауза между страницами, сек
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    min_price: float | None = None            # отсечь мусор (доставка, «0 ₽»)
    max_price: float | None = None
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        self.id = str(self.id).strip()
        self.name = self.name or self.id
        self.method = (self.method or "GET").upper()
        self.fields = {k.lower(): v for k, v in (self.fields or {}).items()}
        self.exclude_keywords = [str(k).lower() for k in self.exclude_keywords]
        self.include_keywords = [str(k).lower() for k in self.include_keywords]

    @property
    def needs_browser(self) -> bool:
        return bool(self.js_render)

    def build_page_urls(self, query: str, pages: int | None = None) -> list[str]:
        """Список URL для запроса (с учётом пагинации)."""
        if self.static and self.search_url:
            return [self.search_url]

        base = self.sort_by_price_url or self.search_url
        if not base:
            return []
        total = pages if pages is not None else self.max_pages
        total = max(1, int(total or 1))
        urls: list[str] = []
        for offset in range(total):
            page_no = self.start_page + offset
            url = base
            if "{query}" in url:
                url = url.replace("{query}", quote_query(query))
            if "{page}" in url:
                url = url.replace("{page}", str(page_no))
            elif total > 1 and self.page_param:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{self.page_param}={page_no}"
            urls.append(url)
        return urls


def quote_query(query: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(query.strip())


@dataclass
class AppConfig:
    sites: list[SiteConfig] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    def by_id(self, site_id: str) -> SiteConfig | None:
        site_id = site_id.strip().lower()
        for s in self.sites:
            if s.id.lower() == site_id or s.name.lower() == site_id:
                return s
        return None

    def enabled(self) -> list[SiteConfig]:
        return [s for s in self.sites if s.enabled]

    def select(self, ids: list[str] | None = None, only_enabled: bool = True) -> list[SiteConfig]:
        pool = self.enabled() if only_enabled else self.sites
        if not ids:
            return pool
        wanted = [i.strip().lower() for i in ids]
        chosen: list[SiteConfig] = []
        for site in self.sites:
            if site.id.lower() in wanted or site.name.lower() in wanted:
                chosen.append(site)
        return chosen


def load_config(path: str | os.PathLike | None = None, *, prefer_yamlite: bool | None = None) -> AppConfig:
    """Читает YAML/JSON-конфиг. Если путь не задан — ищет в типовых местах.

    prefer_yamlite=True — использовать встроенный мини-парсер вместо PyYAML
    (проверка переносимости на Android; по умолчанию берётся из PRICEFINDER_YAMLITE).
    """
    if prefer_yamlite is None:
        prefer_yamlite = os.environ.get("PRICEFINDER_YAMLITE", "").lower() in ("1", "true", "yes")
    cfg_path = Path(path).expanduser() if path else None
    if cfg_path is None:
        for candidate in paths.config_search_paths():   # пересчитываем: пути зависят от окружения
            if candidate.exists():
                cfg_path = candidate
                break
    if cfg_path is None or not cfg_path.exists():
        return AppConfig(settings={})

    text = cfg_path.read_text(encoding="utf-8")
    if cfg_path.suffix.lower() in {".json"}:
        import json

        data = json.loads(text)
    elif yaml is not None and not prefer_yamlite:
        data = yaml.safe_load(text) or {}
    else:
        data = yamlite.safe_load(text) or {}

    return config_from_dict(data)


def config_from_dict(data: dict[str, Any]) -> AppConfig:
    settings = dict(data.get("settings") or {})
    currencies = data.get("currencies") or {}
    settings.setdefault("currencies", currencies)

    sites: list[SiteConfig] = []
    valid = {f.name for f in SiteConfig.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    for raw in data.get("sites") or []:
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        known = {k: v for k, v in raw.items() if k in valid}
        sites.append(SiteConfig(**known))
    return AppConfig(sites=sites, settings=settings)


def parse_interval(text: str | float | int) -> float:
    """'90' / '30m' / '2h' / '1d' -> секунды."""
    import re as _re

    if isinstance(text, (int, float)):
        return max(5.0, float(text))
    value = str(text).strip().lower()
    match = _re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*([smhd]?)", value)
    if not match:
        raise ValueError(f"не понял интервал: {text!r} (примеры: 30m, 2h, 1d, 900)")
    number = float(match.group(1).replace(",", "."))
    multiplier = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return max(1.0, number * multiplier)
