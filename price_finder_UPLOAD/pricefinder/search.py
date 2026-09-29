"""Оркестрация поиска: параллельный опрос сайтов, пагинация, склейка и сортировка результатов."""

from __future__ import annotations

import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .fetcher import Fetcher, FetchResult
from .parsers import Item, dedupe_items, parse_items
from .price import Converter
from .sites import AppConfig, SiteConfig

STOPWORDS = {
    "купить", "цена", "цены", "недорого", "дешево", "дешёвый", "заказать", "заказ", "с", "в", "на", "по",
    "для", "и", "или", "the", "buy", "price", "cheap", "online", "за", "от", "до", "сша", "б/у",
}


def keywords_from_query(query: str, min_len: int = 3) -> list[str]:
    tokens = re.findall(r"[0-9a-zа-яё]{2,}", query.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) >= min_len]


@dataclass
class SearchResult:
    query: str
    items: list[Item] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    per_site: dict[str, int] = field(default_factory=dict)
    elapsed: float = 0.0
    pages_fetched: int = 0


class SearchEngine:
    def __init__(
        self,
        config: AppConfig,
        fetcher: Fetcher | None = None,
        *,
        workers: int = 4,
        force_js: bool | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        settings = config.settings or {}
        self.fetcher = fetcher or Fetcher(
            timeout=float(settings.get("timeout", 20)),
            retries=int(settings.get("retries", 3)),
            delay=float(settings.get("delay", 1.0)),
            respect_robots=bool(settings.get("respect_robots", True)),
            user_agent=str(settings.get("user_agent") or ""),
            proxy=str(settings.get("proxy") or ""),
            verbose=bool(settings.get("verbose", False)),
        )
        self.workers = max(1, workers)
        self.force_js = force_js
        self.log = log or (lambda msg: None)
        self.converter = Converter(
            base=str((settings.get("currencies") or {}).get("base", settings.get("base_currency", "RUB"))).upper(),
            rates={k.upper(): float(v) for k, v in ((settings.get("currencies") or {}).get("rates") or {}).items()},
        )

    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        sites: Sequence[SiteConfig],
        *,
        limit_per_site: int = 50,
        pages: int | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        include_keywords: Sequence[str] | None = None,
        exclude_keywords: Sequence[str] | None = None,
        require_keyword: bool = False,
        in_stock_only: bool = False,
    ) -> SearchResult:
        started = time.time()
        result = SearchResult(query=query)
        if not sites:
            result.errors.append({"site": "-", "error": "нет включённых сайтов (см. config/sites.yaml)"})
            return result

        keywords = keywords_from_query(query)
        extra_exclude = [k.lower() for k in (exclude_keywords or [])]
        extra_include = [k.lower() for k in (include_keywords or [])]

        with ThreadPoolExecutor(max_workers=min(self.workers, len(sites))) as pool:
            futures = {
                pool.submit(
                    self._search_site,
                    site,
                    query,
                    keywords,
                    pages,
                    limit_per_site,
                    min_price,
                    max_price,
                    extra_include,
                    extra_exclude,
                    require_keyword,
                ): site
                for site in sites
            }
            for fut in as_completed(futures):
                site = futures[fut]
                try:
                    items, errors, pages_done = fut.result()
                except Exception as exc:  # noqa: BLE001
                    items, errors, pages_done = [], [{"site": site.name, "error": f"{type(exc).__name__}: {exc}"}], 0
                result.pages_fetched += pages_done
                result.per_site[site.name] = len(items)
                if items:
                    self.log(f"  ✓ {site.name}: {len(items)} предложений ({pages_done} стр.)")
                else:
                    self.log(f"  ✗ {site.name}: ничего не найдено")
                result.items.extend(items)
                result.errors.extend(errors)

        # глобальные фильтры
        if include_keywords:
            wanted = [k.lower() for k in include_keywords]
            result.items = [i for i in result.items if any(k in i.title.lower() for k in wanted)]
        if exclude_keywords:
            banned = [k.lower() for k in exclude_keywords]
            result.items = [i for i in result.items if not any(k in i.title.lower() for k in banned)]
        if in_stock_only:
            result.items = [i for i in result.items if _in_stock(i)]

        result.items.sort(key=lambda it: (it.normalized_price if it.normalized_price is not None else float("inf")))
        result.elapsed = time.time() - started
        return result

    # ------------------------------------------------------------------
    def _search_site(
        self,
        site: SiteConfig,
        query: str,
        keywords: Sequence[str],
        pages: int | None,
        limit_per_site: int,
        min_price: float | None,
        max_price: float | None,
        include_keywords: Sequence[str],
        exclude_keywords: Sequence[str],
        require_keyword: bool,
    ) -> tuple[list[Item], list[dict[str, str]], int]:
        site_min = min_price if min_price is not None else site.min_price
        site_max = max_price if max_price is not None else site.max_price
        all_excludes = list(dict.fromkeys([*site.exclude_keywords, *exclude_keywords]))
        all_includes = list(dict.fromkeys([*site.include_keywords, *include_keywords]))

        urls = site.build_page_urls(query, pages if pages is not None else site.max_pages)
        if not urls:
            return [], [{"site": site.name, "error": "в конфиге не задан search_url"}], 0

        items: list[Item] = []
        errors: list[dict[str, str]] = []
        pages_done = 0
        strategies: set[str] = set()

        for url in urls:
            fetched = self._fetch(site, url, query)
            if not fetched.ok or not fetched.html:
                errors.append({"site": site.name, "url": url, "error": fetched.error or f"HTTP {fetched.status}"})
                break
            pages_done += 1
            page_items, strategy = parse_items(
                fetched.html,
                site=site,
                page_url=fetched.url,
                query=query,
                converter=self.converter,
                min_price=site_min,
                max_price=site_max,
                query_keywords=keywords,
                require_query_keyword=require_keyword,
                # ключевые слова сайта (из конфига) + заданные в команде
                include_keywords=all_includes,
                exclude_keywords=all_excludes,
            )
            if page_items:
                strategies.add(strategy)
                items.extend(page_items)
                self.log(f"    · {site.name} стр.{pages_done}: {len(page_items)} карточек [{strategy}]")
            if not page_items:
                # дальше листать бессмысленно
                if pages_done == 1 and fetched.status == 200:
                    errors.append({
                        "site": site.name,
                        "url": url,
                        "error": "страница получена, но карточки не распознаны — проверьте селекторы "
                                 "или включите js_render",
                    })
                break
            if len(items) >= limit_per_site:
                break
            if site.delay:
                time.sleep(min(site.delay, 3.0))

        if items and strategies:
            for it in items:
                if not it.strategy:
                    it.strategy = next(iter(strategies))
        items = dedupe_items(items)   # одна и та же карточка может приехать с нескольких страниц
        items.sort(key=lambda it: (it.normalized_price if it.normalized_price is not None else float("inf")))
        return items[:limit_per_site], errors, pages_done

    # ------------------------------------------------------------------
    def _fetch(self, site: SiteConfig, url: str, query: str) -> FetchResult:
        use_js = self.force_js if self.force_js is not None else site.js_render
        post_data = None
        method = site.method
        if method in ("POST", "JSON") and site.post_data:
            post_data = _sub_query(site.post_data, query)
        return self.fetcher.get(
            url,
            method=method,
            post_data=post_data,
            headers=site.headers or None,
            cookies=site.cookies or None,
            js_render=bool(use_js),
            render_wait=site.render_wait,
            wait_selector=site.wait_selector,
        )


def _sub_query(data: Any, query: str) -> Any:
    if isinstance(data, dict):
        return {k: _sub_query(v, query) for k, v in data.items()}
    if isinstance(data, list):
        return [_sub_query(v, query) for v in data]
    if isinstance(data, str) and "{query}" in data:
        from .sites import quote_query

        return data.replace("{query}", quote_query(query))
    return data


def apply_ratio_filter(items: list[Item], ratio: float | None) -> list[Item]:
    """Оставляет только предложения не дороже «минимум × ratio» (0/None — выключено)."""
    if not ratio or not items:
        return items
    priced = [i for i in items if i.normalized_price]
    if not priced:
        return items
    low = min(i.normalized_price for i in priced)
    return [i for i in items if not i.normalized_price or i.normalized_price <= low * float(ratio)]


def _in_stock(item: Item) -> bool:
    text = (item.availability or "").lower()
    if not text:
        return True
    if "нет" in text or "out" in text or "отсут" in text:
        return False
    return True


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)
