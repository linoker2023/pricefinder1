#!/usr/bin/env python3
"""pricefinder — поиск самых низких цен на товар по любому сайту.

Быстрый старт:
    python price_finder.py search "iphone 15 128gb"
    python price_finder.py search "шуруповёрт" --sites demo --html out/report.html
    python price_finder.py watch "playstation 5" --interval 30m --target-price 45000
    python price_finder.py sites                     # какие источники настроены
    python price_finder.py test-site demo "тест"     # отладка парсера конкретного сайта

Полная справка: python price_finder.py --help
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pricefinder import __version__, paths, reports  # noqa: E402
from pricefinder.fetcher import Fetcher  # noqa: E402
from pricefinder.notify import Notifier  # noqa: E402
from pricefinder.parsers import Item, merge_same_offers  # noqa: E402
from pricefinder.price import Converter, fetch_live_rates, parse_price  # noqa: E402
from pricefinder.search import SearchEngine, apply_ratio_filter, keywords_from_query  # noqa: E402
from pricefinder.sites import AppConfig, SiteConfig, load_config, parse_interval  # noqa: E402
from pricefinder.storage import Storage  # noqa: E402

DEFAULT_DB = str(paths.default_db_path())
DEFAULT_CONFIG = paths.PROJECT_DIR / "config" / "sites.yaml"
# Пути вычисляются при вызове (на Android папка программы может быть read-only)
QUERIES_FILE = paths.queries_file()

# Статические курсы-заглушки (обновляются через `update-rates` или вручную в конфиге)
FALLBACK_RATES = {"USD": 92.0, "EUR": 100.0, "CNY": 12.7, "KZT": 0.2, "BYN": 28.0, "UAH": 2.3,
                  "GBP": 117.0, "TRY": 2.8, "GEL": 34.0, "AMD": 0.23, "AZN": 54.0, "PLN": 23.0,
                  "JPY": 0.6, "UZS": 0.0073, "KGS": 1.05, "MDL": 5.2, "INR": 1.1}


# =========================================================================
#  Вспомогательное
# =========================================================================

def build_converter(settings: dict, live_rates: bool = False, verbose: bool = False) -> Converter:
    cur = settings.get("currencies") or {}
    base = str(cur.get("base") or settings.get("base_currency") or "RUB").upper()
    rates = dict(FALLBACK_RATES)
    rates.update({k.upper(): float(v) for k, v in (cur.get("rates") or {}).items()})
    if live_rates:
        fetched = fetch_live_rates(base)
        if fetched:
            rates.update(fetched)
            if verbose:
                print(f"  курсы валют обновлены ({len(fetched)} пар) на {datetime.now():%d.%m.%Y}", file=sys.stderr)
        elif verbose:
            print("  не удалось получить живые курсы — использую локальные", file=sys.stderr)
    return Converter(base=base, rates=rates)


def make_fetcher(args, settings: dict, force_js: bool | None = None) -> Fetcher:
    return Fetcher(
        timeout=args.timeout or float(settings.get("timeout", 20)),
        retries=args.retries or int(settings.get("retries", 3)),
        delay=args.delay if args.delay is not None else float(settings.get("delay", 1.0)),
        respect_robots=not args.ignore_robots and bool(settings.get("respect_robots", True)),
        user_agent=args.user_agent or str(settings.get("user_agent") or ""),
        proxy=args.proxy or str(settings.get("proxy") or ""),
        insecure=bool(args.insecure),
        use_browser=force_js,
        verbose=bool(args.verbose),
    )


def select_sites(config: AppConfig, args, allow_all: bool = True) -> list[SiteConfig]:
    ids = getattr(args, "sites", None)
    if ids:
        chosen = config.select([s.strip() for s in ids.split(",") if s.strip()], only_enabled=False)
        if not chosen:
            sys.exit(f"Сайты не найдены в конфиге: {ids}. Список: python price_finder.py sites")
        return chosen
    if getattr(args, "all_sites", False) and allow_all:
        return config.sites
    return config.enabled()


def save_outputs(items, args, query: str = "", errors=()) -> list[Path]:
    saved: list[Path] = []
    base_currency = getattr(args, "_base_currency", "RUB")
    for value, saver in (
        (getattr(args, "csv", None), lambda p: reports.save_csv(items, p)),
        (getattr(args, "json_out", None), lambda p: reports.save_json(items, p, query)),
        (getattr(args, "xlsx", None), lambda p: reports.save_xlsx(items, p, query)),
        (getattr(args, "html", None), lambda p: reports.save_html(items, p, query, errors, base_currency)),
        (getattr(args, "save", None), lambda p: reports.save_auto(items, p, query, errors, base_currency)),
    ):
        if value:
            saved.append(saver(paths.resolve_output_path(value)))
    return saved


def report_saved(saved: list[Path], color: bool = True) -> None:
    for path in saved:
        prefix = reports._c("  💾 сохранено:", reports.GREEN, color)
        print(f"{prefix} {path}")


# =========================================================================
#  Команда: search
# =========================================================================

QUERIES_TEMPLATE = """# Список товаров для поиска и мониторинга — по одному на строку.
# Формат строки:   товар ; желаемая цена ; падение в % ; сайты через запятую
# Всё, кроме товара, необязательно. Строки с # и пустые игнорируются.
#
# Запуск:
#   python price_finder.py search --queries-file          # найти цены по всем строкам
#   python price_finder.py watch --queries-file -i 30m    # следить за всеми строками
#
# Примеры:
# iphone 15 128gb ; 60000
# ноутбук asus vivobook 15 ; 45000 ; 5
# кофемашина delonghi magnifica ; 25000 ; 7 ; bookvoed
# наушники sony ; - ; - ; bookvoed      # прочерк = «поле не задано»
"""


def parse_queries_file(path: str | os.PathLike | None = None) -> list[dict]:
    """Читает список товаров из текстового файла (удобно править в блокноте).

    Строка: `товар ; целевая цена ; падение в % ; сайт1,сайт2`
    Возвращает список словарей с ключами query/target_price/drop_pct/sites.
    """
    file_path = Path(path).expanduser() if path else paths.queries_file()
    if not file_path.exists():
        sys.exit(
            f"Файл со списком товаров не найден: {file_path}\n"
            f"Создайте его командой: python price_finder.py init-queries\n"
            f"Формат строки: товар ; желаемая цена ; падение в % ; сайты"
        )
    queries: list[dict] = []
    for raw in file_path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[;|]", line)]
        # прочерк «-» означает «поле не задано» (нужно, чтобы дойти до сайтов)
        parts = ["" if p in {"-", "—", "–", "none", "нет"} else p for p in parts]
        entry: dict = {"query": parts[0], "sites": None, "target_price": None, "drop_pct": None}
        if len(parts) > 1 and parts[1]:
            try:
                entry["target_price"] = float(re.sub(r"[^\d.,\-]", "", parts[1]).replace(",", "."))
            except ValueError:
                print(f"  ⚠ не понял желаемую цену в строке «{line}» — игнорирую порог", file=sys.stderr)
        if len(parts) > 2 and parts[2]:
            try:
                entry["drop_pct"] = float(parts[2].replace(",", "."))
            except ValueError:
                print(f"  ⚠ не понял процент падения в строке «{line}» — игнорирую", file=sys.stderr)
        if len(parts) > 3 and parts[3]:
            entry["sites"] = parts[3]
        if entry["query"]:
            queries.append(entry)
    if not queries:
        sys.exit(f"В файле {file_path} нет ни одного товара (строки без # и не пустые)")
    return queries


def run_search_for(args, query: str, *, sites_override: str | None = None) -> int:
    """Один поиск из списка товаров (args.queries_file гасится, чтобы не было рекурсии)."""
    saved_flags = (args.queries_file, args.sites)
    args.queries_file = None
    args.query = [query]
    if sites_override:
        args.sites = sites_override
    try:
        return _search_one(args, query)
    finally:
        args.queries_file, args.sites = saved_flags


def cmd_search(args) -> int:
    if getattr(args, "queries_file", None):
        return cmd_search_file(args)

    query = " ".join(args.query or []).strip()
    if not query:
        sys.exit("Укажите товар, например:\n"
                 "  python price_finder.py search \"iphone 15\"\n"
                 "  python price_finder.py init-queries   # а затем правьте queries.txt\n"
                 "  python price_finder.py search --queries-file")
    return _search_one(args, query)


def cmd_search_file(args) -> int:
    """Поиск по списку товаров из текстового файла (queries.txt)."""
    entries = parse_queries_file(args.queries_file if isinstance(args.queries_file, str) else None)
    shown = Path(args.queries_file).name if isinstance(args.queries_file, str) else paths.queries_file().name
    print(reports._c(f"  Список товаров: {len(entries)} шт. ({shown})", reports.BOLD, args.color))
    failed = 0
    for idx, entry in enumerate(entries, 1):
        query = entry["query"]
        print(reports._c(f"\n{'=' * 78}\n  [{idx}/{len(entries)}] {query}"
                         + (f"  · ищу не дороже {entry['target_price']:g}" if entry.get("target_price") else "")
                         + f"\n{'=' * 78}", reports.CYAN, args.color))
        args.max_price = entry.get("target_price")
        code = run_search_for(args, query, sites_override=entry.get("sites"))
        failed += 1 if code else 0
    print(reports._c(f"\n  Готово: {len(entries) - failed}/{len(entries)} товаров с результатами.",
                     reports.BOLD, args.color))
    return 0 if failed < len(entries) else 1


def _search_one(args, query: str) -> int:
    config = load_config(args.config, prefer_yamlite=getattr(args, 'yamlite', False))
    settings = config.settings or {}

    sites = select_sites(config, args)
    if not sites:
        sys.exit("Нет включённых сайтов. Запустите `python price_finder.py sites` и включите нужные "
                 "(enabled: true) или добавьте свои.")

    converter = build_converter(settings, live_rates=args.update_rates, verbose=args.verbose)
    fetcher = make_fetcher(args, settings, force_js=True if args.js else (False if args.no_js else None))
    engine = SearchEngine(config, fetcher, workers=args.workers, force_js=True if args.js else None,
                          log=(lambda m: print(m, file=sys.stderr)) if args.verbose else None)

    color = args.color

    print(reports._c(f"  Ищу «{query}» на {len(sites)} площадках…", reports.DIM, color))
    result = engine.search(
        query,
        sites,
        limit_per_site=args.per_site,
        pages=args.pages,
        min_price=args.min_price,
        max_price=args.max_price,
        include_keywords=args.include,
        exclude_keywords=args.exclude,
        require_keyword=args.require_keyword,
        in_stock_only=args.in_stock,
    )

    items = apply_ratio_filter(result.items, args.max_ratio)
    if not args.no_merge:
        items = merge_same_offers(items)
    args._base_currency = converter.base

    reports.print_table(
        items,
        query=query,
        limit=args.top,
        color=color,
        width=args.width,
        base_currency=converter.base,
        show_url=not args.no_url,
    )
    if args.by_site:
        reports.print_site_summary(items, color=color, base_currency=converter.base)
    if args.show_errors:
        reports.print_errors(result.errors, color=color)
    elif result.errors and not args.quiet:
        bad = ", ".join(sorted({e["site"] for e in result.errors}))
        print(reports._c(f"  ⚠ {len(result.errors)} источник(ов) не ответили: {bad} (--show-errors для деталей)",
                         reports.DIM, color))

    if args.best and items:
        best = items[0]
        print(reports._c("  🏆 Лучшее предложение:", reports.BOLD, color))
        print(f"     {best.title}")
        price = best.normalized_price if best.normalized_price is not None else best.price
        print(f"     {reports.fmt(price, reports.CURRENCY_CODES.get(converter.base, converter.base))} "
              f"· {best.site_name}")
        print(f"     {best.url}")

    saved = save_outputs(items, args, query, result.errors)
    report_saved(saved, color)

    if not args.no_history:
        storage = Storage(args.db)
        try:
            events = storage.save_items(items, query=query)
            storage.log_search(query, [s.name for s in sites], items, items[0] if items else None)
            lows = [e for e in events if e.get("is_all_time_low") and not e.get("is_new")]
            if lows and not args.quiet:
                print(reports._c(f"  📉 Исторический минимум у {len(lows)} предложений (см. `history`)",
                                 reports.DIM, color))
        finally:
            storage.close()

    unknown = [
        c for c in {i.currency for i in items}
        if c and c.upper() != converter.base and c not in converter.rates
    ]
    if unknown and not args.quiet:
        print(reports._c(f"  ⚠ Нет курса для {', '.join(unknown)} — цены сравниваются без конвертации "
                         f"(--update-rates или пропишите курсы в конфиге)", reports.YELLOW, color))

    fetcher.close()
    if not items and not args.quiet:
        print(reports._c("  Попробуйте: --js (рендер в браузере), --all-sites, другой запрос "
                         "или проверьте селекторы через `test-site`.", reports.YELLOW, color))
    return 0 if items else 1


# =========================================================================
#  Команда: sites
# =========================================================================

def cmd_sites(args) -> int:
    config = load_config(args.config, prefer_yamlite=getattr(args, 'yamlite', False))
    if not config.sites:
        print("Конфиг пуст. Создайте его: python price_finder.py init-config")
        return 1
    color = args.color
    print()
    print(reports._c("  Настроенные источники цен", reports.BOLD, color))
    print(reports._c("  " + "─" * 96, reports.DIM, color))
    for site in config.sites:
        status = reports._c("вкл ", reports.GREEN, color) if site.enabled else reports._c("выкл", reports.RED, color)
        flags = []
        if site.js_render:
            flags.append("JS")
        if site.product_selector:
            flags.append("css")
        flags.append("авто(JSON-LD/microdata/meta)")
        print(f"  [{status}] {reports._c(site.id, reports.BOLD, color):<24} {site.name}")
        print(f"        стратегия: {', '.join(flags)}"
              + (f" · валюта: {site.currency}" if site.currency else "")
              + (f" · стр.: {site.max_pages}" if site.max_pages > 1 else ""))
        if site.search_url:
            print(reports._c(f"        {reports.truncate(site.search_url, 108)}", reports.DIM, color))
        if site.notes:
            print(reports._c(f"        ℹ {site.notes}", reports.YELLOW, color))
    print()
    enabled = config.enabled()
    print(reports._c(f"  Активных: {len(enabled)} из {len(config.sites)}. "
                     f"Включить/выключить: правка enabled в {args.config or DEFAULT_CONFIG}", reports.DIM, color))
    print()
    return 0


# =========================================================================
#  Команда: test-site
# =========================================================================

def cmd_test_site(args) -> int:
    config = load_config(args.config, prefer_yamlite=getattr(args, 'yamlite', False))
    settings = config.settings or {}
    site = config.by_id(args.site)
    if site is None:
        sys.exit(f"Сайт «{args.site}» не найден в конфиге. Список: python price_finder.py sites")
    converter = build_converter(settings, live_rates=False)
    fetcher = make_fetcher(args, settings, force_js=True if args.js else None)

    urls = site.build_page_urls(args.query, args.pages or 1)
    print(f"  Сайт: {site.name} ({site.id})")
    total = 0
    for url in urls:
        print(f"  URL:  {url}")
        res = fetcher.get(
            url,
            method=site.method,
            post_data=site.post_data or None,
            headers=site.headers or None,
            cookies=site.cookies or None,
            js_render=args.js or site.js_render,
            render_wait=site.render_wait,
            wait_selector=site.wait_selector,
        )
        print(f"  Ответ: HTTP {res.status} · движок {res.engine} · {len(res.html)} байт · {res.elapsed:.1f} c")
        if res.error:
            print(reports._c(f"  Ошибка: {res.error}", reports.RED, True))
        if args.dump_html:
            path = Path(args.dump_html)
            path.write_text(res.html or "", encoding="utf-8")
            print(f"  HTML сохранён: {path}")
        if not res.html:
            continue
        items, strategy = parse_items_safe(res.html, site, res.url, args.query, converter, args)
        print(f"  Стратегия парсинга: {strategy} · карточек: {len(items)}")
        for it in items[: args.sample]:
            print(f"    - {reports.fmt(it.price, converter.symbol(it.currency))} | "
                  f"{reports.truncate(it.title, 70)} | {reports.truncate(it.url, 60)}")
        total += len(items)
    fetcher.close()
    print(f"  Итого: {total} карточек")
    return 0 if total else 2


def parse_items_safe(html: str, site: SiteConfig, url: str, query: str, converter: Converter, args) -> tuple:
    from pricefinder.parsers import parse_items

    return parse_items(
        html,
        site=site,
        page_url=url,
        query=query,
        converter=converter,
        min_price=args.min_price,
        max_price=args.max_price,
        query_keywords=keywords_from_query(query),
        require_query_keyword=args.require_keyword,
    )


# =========================================================================
#  Команда: history
# =========================================================================

def cmd_history(args) -> int:
    storage = Storage(args.db)
    color = args.color
    try:
        rows = storage.all_items(query=args.query, limit=args.limit)
        if args.filter:
            needle = args.filter.lower()
            rows = [r for r in rows if needle in (r.get("title") or "").lower()
                    or needle in (r.get("site_name") or "").lower()]
        if not rows:
            print("  История пуста. Сначала выполните search (без --no-history).")
            return 1
        print()
        print(reports._c(f"  История цен ({len(rows)} позиций)", reports.BOLD, color))
        for row in rows[: args.limit]:
            uid = row["uid"]
            hist = storage.history(uid, limit=args.points)
            prices = [h["price"] for h in reversed(hist) if h["price"] is not None]
            spark = sparkline(prices)
            cur = min(prices) if prices else 0
            lo = min(prices) if prices else 0
            hi = max(prices) if prices else 0
            delta = ""
            if len(prices) >= 2 and prices[0]:
                pct = (prices[-1] - prices[0]) / prices[0] * 100
                delta = f"{'+' if pct >= 0 else ''}{pct:.1f}%"
            print(f"  {reports._c(reports.truncate(row['title'] or '', 62), reports.BOLD, color)}")
            delta_view = reports._c(delta, reports.GREEN if delta.startswith("-") else reports.RED, color) if delta else ""
            print(f"     {row['site_name']:<16} сейчас: {reports.fmt(cur)}   мин: {reports.fmt(lo)}   "
                  f"макс: {reports.fmt(hi)}   точек: {len(prices)}   {delta_view}")
            print(f"     {reports._c(spark, reports.CYAN, color)}  uid={uid}")
            print(f"     {reports._c(reports.truncate(row['url'] or '', 96), reports.DIM, color)}")
        print()
    finally:
        storage.close()
    return 0


SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 32) -> str:
    if not values:
        return ""
    series = values[-width:]
    lo, hi = min(series), max(series)
    if hi - lo < 1e-9:
        return SPARK_CHARS[3] * len(series)
    return "".join(SPARK_CHARS[int((v - lo) / (hi - lo) * (len(SPARK_CHARS) - 1))] for v in series)


# =========================================================================
#  Команда: watch
# =========================================================================

def cmd_watch(args) -> int:
    config = load_config(args.config, prefer_yamlite=getattr(args, 'yamlite', False))
    settings = config.settings or {}
    converter = build_converter(settings, live_rates=args.update_rates)
    interval = max(60.0, parse_interval(args.interval))
    storage = Storage(args.db)
    notifier = Notifier.from_settings(settings)
    color = args.color and not args.once

    targets: list[dict] = []
    if args.query:
        targets.append({
            "query": " ".join(args.query).strip(),
            "sites": args.sites,
            "target_price": args.target_price,
            "drop_pct": args.drop_pct,
        })
    elif getattr(args, "queries_file", None):
        for entry in parse_queries_file(args.queries_file if isinstance(args.queries_file, str) else None):
            targets.append({
                "query": entry["query"],
                "sites": entry.get("sites") or args.sites,
                "target_price": entry.get("target_price") or args.target_price,
                "drop_pct": entry.get("drop_pct") or args.drop_pct,
            })
    else:
        for t in storage.targets():
            targets.append({
                "query": t["query"],
                "sites": t.get("sites"),
                "target_price": t.get("target_price"),
                "drop_pct": t.get("drop_pct"),
            })
    if not targets:
        sys.exit("Укажите запрос (watch \"товар\") или добавьте цель: targets add \"товар\" --target-price 5000")

    sites_all = select_sites(config, args)
    print(reports._c(f"  Мониторинг: {len(targets)} запрос(ов), интервал {int(interval)} с, "
                     f"источников {len(sites_all)}. Ctrl+C — выход.", reports.BOLD, color))

    runs = 0
    try:
        while True:
            runs += 1
            for target in targets:
                site_list = (config.select([s.strip() for s in target["sites"].split(",")], only_enabled=False)
                             if target.get("sites") else sites_all)
                fetcher = make_fetcher(args, settings, force_js=True if args.js else None)
                engine = SearchEngine(config, fetcher, workers=args.workers)
                stamp = datetime.now().strftime("%H:%M:%S")
                print(reports._c(f"  [{stamp}] проверяю «{target['query']}»…", reports.DIM, color))
                result = engine.search(
                    target["query"], site_list,
                    limit_per_site=args.per_site, pages=args.pages,
                    min_price=args.min_price, max_price=args.max_price,
                    exclude_keywords=args.exclude, in_stock_only=args.in_stock,
                )
                items = merge_same_offers(apply_ratio_filter(result.items, args.max_ratio))
                fetcher.close()
                if not items:
                    print(reports._c(f"  [{stamp}] ничего не найдено"
                                     + (f" ({len(result.errors)} ошибок)" if result.errors else ""),
                                     reports.YELLOW, color))
                    continue

                events = storage.save_items(items, query=target["query"])
                storage.log_search(target["query"], [s.name for s in site_list], items, items[0])
                best = items[0]
                print(f"  [{stamp}] найдено {len(items)} · мин. "
                      f"{reports.fmt(best.normalized_price or best.price, converter.symbol(converter.base))} "
                      f"· {reports.truncate(best.title, 50)} ({best.site_name})")

                alerts = _collect_alerts(events, target, storage, args.alert_cooldown)
                if alerts:
                    for _kind, desc, event, price in alerts:
                        print(reports._c(f"    🔔 {desc}: {reports.fmt(price)} — "
                                         f"{reports.truncate(event['item'].title, 60)}", reports.GREEN, color))
                    subject = f"Цена снизилась: {target['query']}"
                    html, text = reports.build_alert_html(
                        [e for _, _, e, _ in alerts], target["query"], converter.base
                    )
                    if notifier.enabled and (notifier.telegram_token or notifier.smtp_host
                                               or notifier.termux_available()):
                        status = notifier.send(subject, html, text)
                        print(reports._c(f"    уведомление: {status}", reports.DIM, color))
                    else:
                        print(reports._c("    (уведомления не настроены: settings.telegram / settings.smtp "
                                         "в config/sites.yaml; на Android — Termux:API)", reports.DIM, color))
                    for kind, desc, event, price in alerts:
                        storage.log_alert(event["item"].uid, target["query"], kind, price,
                                          {"desc": desc, "title": event["item"].title,
                                           "url": event["item"].url, "site": event["item"].site_name})
                if args.save:
                    name = str(args.save).format(query=re.sub(r"\W+", "_", target["query"]))
                    path = paths.resolve_output_path(name)
                    reports.save_auto(items, path, target["query"], result.errors, converter.base)
                    print(reports._c(f"    💾 {path}", reports.DIM, color))

            if args.once or (args.runs and runs >= args.runs):
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print(reports._c("\n  Остановлено пользователем.", reports.YELLOW, color))
    finally:
        storage.close()
    return 0


def _collect_alerts(events: list[dict], target: dict, storage: Storage,
                    cooldown_hours: float = 6.0) -> list[tuple[str, str, dict, float]]:
    """Возвращает (стабильный kind, текст для человека, событие, цена).

    kind пишется в БД и используется для защиты от повторных уведомлений.
    """
    alerts: list[tuple[str, str, dict, float]] = []
    target_price = target.get("target_price")
    drop_pct = target.get("drop_pct")
    for ev in events:
        item: Item = ev["item"]
        price = item.normalized_price if item.normalized_price is not None else (item.price or 0)
        if target_price and price <= float(target_price):
            if not storage.alert_seen(item.uid, "target", price, cooldown_hours):
                alerts.append(("target", f"цена ниже цели {target_price:g}", ev, price))
        if ev.get("is_all_time_low") and not ev.get("is_new"):
            if not storage.alert_seen(item.uid, "all_time_low", price, cooldown_hours):
                alerts.append(("all_time_low", "исторический минимум", ev, price))
        if drop_pct and ev.get("drop_pct") is not None and ev["drop_pct"] <= -abs(float(drop_pct)):
            if not storage.alert_seen(item.uid, "drop", price, cooldown_hours):
                alerts.append(("drop", f"падение на {abs(ev['drop_pct']):.1f}% за шаг", ev, price))
    return alerts


# =========================================================================
#  Команда: targets
# =========================================================================

def cmd_targets(args) -> int:
    storage = Storage(args.db)
    try:
        if args.targets_action == "add":
            tid = storage.add_target(
                query=" ".join(args.query).strip(),
                sites=args.sites,
                target_price=args.target_price,
                drop_pct=args.drop_pct,
                notify=args.notify or "telegram,email",
            )
            print(f"  Добавлена цель #{tid}: «{' '.join(args.query)}»"
                  + (f", порог {args.target_price}" if args.target_price else ""))
        elif args.targets_action == "list":
            rows = storage.targets(only_active=not args.all)
            if not rows:
                print("  Целей нет. Добавьте: targets add \"товар\" --target-price 5000")
            for r in rows:
                print(f"  #{r['id']:<3} «{r['query']}»"
                      + (f"  sites={r['sites']}" if r.get("sites") else "")
                      + (f"  порог={r['target_price']}" if r.get("target_price") else "")
                      + (f"  падение={r['drop_pct']}%" if r.get("drop_pct") else "")
                      + ("  [выключена]" if not r["active"] else ""))
        elif args.targets_action == "remove":
            storage.set_target_active(args.id, False)
            print(f"  Цель #{args.id} отключена")
    finally:
        storage.close()
    return 0


# =========================================================================
#  Команды-утилиты
# =========================================================================

def cmd_parse_price(args) -> int:
    for text in args.text:
        price = parse_price(text, default_currency=args.currency)
        if price is None:
            print(f"  {text!r:<32} -> цена не распознана")
        else:
            extra = f" (диапазон до {price.high})" if price.is_range else ""
            print(f"  {text!r:<32} -> {price.amount} {price.currency} · «{price.format()}»"
                  f" · уверенность {price.confidence}{extra}")
    return 0


def cmd_update_rates(args) -> int:
    base = args.base.upper()
    rates = fetch_live_rates(base)
    if not rates:
        print("  Не удалось получить курсы (нет сети или API недоступен).")
        return 1
    wanted = [c.upper() for c in args.currencies.split(",")] if args.currencies else sorted(rates)
    lines = [f"    {c}: {rates[c]:.6g}" for c in wanted if c in rates]
    print(f"  Курсы к {base} (open.er-api.com):")
    print("\n".join(lines))
    if args.write_config:
        path = Path(args.config or DEFAULT_CONFIG)
        if path.exists():
            text = path.read_text(encoding="utf-8")
            block = "currencies:\n  base: " + base + "\n  rates:\n" + "".join(
                f"    {c}: {rates[c]:.6g}\n" for c in wanted if c in rates
            )
            if re.search(r"^currencies:", text, re.M):
                text = re.sub(r"^currencies:(?:\n(?:\s+.+|\s*))+", block, text, flags=re.M)
            else:
                text = block + "\n" + text
            path.write_text(text, encoding="utf-8")
            print(f"  Записано в {path}")
    return 0


def cmd_init_config(args) -> int:
    target = Path(args.output) if args.output else (
        DEFAULT_CONFIG if paths.is_writable(DEFAULT_CONFIG.parent) else paths.app_dir() / "config" / "sites.yaml"
    )
    if target.exists() and not args.force:
        print(f"  Конфиг уже существует: {target} (используйте --force для перезаписи)")
        return 1
    template = (HERE / "config" / "sites.template.yaml")
    if template.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    print(f"  Создан конфиг: {target}")
    return 0


def cmd_init_queries(args) -> int:
    """Создаёт queries.txt — список товаров, который удобно править в блокноте."""
    path = Path(args.output).expanduser() if args.output else paths.queries_file()
    if path.exists() and not args.force:
        print(f"  Файл уже существует: {path} (добавьте --force, чтобы перезаписать)")
        return 1
    path.write_text(QUERIES_TEMPLATE, encoding="utf-8")
    print(f"  Создан список товаров: {path}")
    print("  Откройте его в блокноте, впишите свои товары (по одному на строку) и запустите:")
    print("    python price_finder.py search --queries-file     # найти цены по всем")
    print("    python price_finder.py watch --queries-file -i 30m   # следить за всеми")
    return 0


def cmd_env(args) -> int:
    """Показывает платформу, пути и установленные библиотеки — первое, что смотреть на телефоне."""
    print()
    print(paths.environment_report())
    config_paths = [p for p in paths.config_search_paths()]
    used = next((p for p in config_paths if p.exists()), None)
    print(f"Конфиг: {used or 'не найден (создайте: python price_finder.py init-config)'}")
    print(f"Список товаров: {paths.queries_file()}"
          + ("" if paths.queries_file().exists() else "  (создайте: python price_finder.py init-queries)"))
    print()
    if paths.is_android():
        print("  Это Android. Памятка:")
        print("    • уведомления в шторку: установите приложение Termux:API и `pkg install termux-api`")
        print("    • чтобы телефон не убивал мониторинг: `termux-wake-lock` (см. android/ANDROID.md)")
        print("    • сенсорный интерфейс: python price_finder.py gui  (нужен kivy)")
    print()
    return 0


def cmd_notify_test(args) -> int:
    """Проверяет все настроенные каналы уведомлений."""
    config = load_config(args.config, prefer_yamlite=args.yamlite)
    notifier = Notifier.from_settings(config.settings or {})
    print("  Каналы:")
    print(f"    Android (Termux:API): {'доступен' if notifier.termux_available() else 'недоступен'}")
    print(f"    Telegram: {'настроен' if notifier.telegram_token and notifier.telegram_chat else 'не настроен'}")
    print(f"    E-mail (SMTP): {'настроен' if notifier.smtp_host and notifier.smtp_to else 'не настроен'}")
    status = notifier.test()
    if not status:
        print("  Нечего проверять: заполните settings.telegram / settings.smtp в config/sites.yaml"
              " или установите Termux:API")
        return 1
    print(f"  Результат отправки: {status}")
    return 0 if any(status.values()) else 1


def cmd_gui(args) -> int:
    """Запуск сенсорного интерфейса (Kivy). Флаг --selftest проверяет логику без окна."""
    from pricefinder.display import display_hint

    gui_path = paths.PROJECT_DIR / "gui_app.py"
    if not gui_path.exists():
        print(f"  Не найден файл интерфейса: {gui_path}")
        return 1
    if str(paths.PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(paths.PROJECT_DIR))
    try:
        # gui_app.py НЕ импортирует kivy на уровне модуля — это безопасно
        import gui_app
    except Exception as exc:  # noqa: BLE001
        print(f"  Не удалось загрузить модуль интерфейса: {type(exc).__name__}: {exc}")
        print("  Текстовый режим работает всегда: python price_finder.py search \"товар\"")
        return 1

    if getattr(args, "selftest", False):
        return gui_app.selftest()

    # Сначала kivy, потом дисплей: подсказка должна быть про главную проблему.
    # Проверяем ДО создания окна — иначе Kivy аварийно завершит процесс без
    # внятного сообщения (так бывает в Termux без Termux:X11).
    ok, reason = gui_app.kivy_available()
    if not ok:
        print(gui_app.kivy_install_hint(reason))
        return 1
    hint = display_hint()
    if hint:
        sys.stderr.write("\n" + hint + "\n\n")
        return 2
    return gui_app.main()


def cmd_serve_demo(args) -> int:
    demo = HERE / "tests" / "demo_server.py"
    if not demo.exists():
        print("  tests/demo_server.py не найден")
        return 1
    import subprocess

    print(f"  Демо-магазин: http://127.0.0.1:{args.port}/search?q=тест  (Ctrl+C — остановить)")
    return subprocess.call([sys.executable, str(demo), "--port", str(args.port)])


DEFAULT_CONFIG_TEXT = "settings:\n  timeout: 20\n  retries: 3\nsites: []\n"


# =========================================================================
#  CLI
# =========================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="price_finder.py",
        description="Поиск самых низких цен на товар по любому сайту (универсальный парсер).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python price_finder.py search "iphone 15 128gb"
  python price_finder.py search "шуруповёрт 18в" --top 30 --by-site --xlsx out/prices.xlsx
  python price_finder.py search "корм для кошек" --max-price 3000 --exclude "б/у,витрина" --html report.html
  python price_finder.py search "RTX 4070" --js --pages 2 --update-rates
  python price_finder.py watch "playstation 5" --interval 30m --target-price 45000
  python price_finder.py targets add "кофемашина" --target-price 25000 --drop-pct 5
  python price_finder.py history --filter "iphone" --points 60
  python price_finder.py test-site demo "ноутбук" --dump-html page.html
  python price_finder.py serve-demo            # локальный демо-магазин для проверки
  python price_finder.py parse-price "1 299,90 ₽" "от 500 до 700 руб." "US$1,299.00"
""",
    )
    parser.add_argument("--version", action="version", version=f"pricefinder {__version__}")
    parser.add_argument("-c", "--config", help="путь к конфиг сайтов (по умолчанию config/sites.yaml)")
    parser.add_argument("--db", default=os.environ.get("PRICEFINDER_DB", DEFAULT_DB),
                        help=f"файл базы истории цен (по умолчанию {DEFAULT_DB})")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог в stderr")
    parser.add_argument("--no-color", action="store_true", help="без ANSI-цветов")
    parser.add_argument("--force-color", action="store_true", help="цвета даже без TTY")

    # Общие флаги доступны и до, и после подкоманды
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", help="путь к конфиг сайтов (по умолчанию config/sites.yaml)")
    common.add_argument("--db", default=os.environ.get("PRICEFINDER_DB", DEFAULT_DB),
                        help=f"файл базы истории цен (по умолчанию {DEFAULT_DB})")
    common.add_argument("-v", "--verbose", action="store_true", help="подробный лог в stderr")
    common.add_argument("--no-color", action="store_true", help="без ANSI-цветов")
    common.add_argument("--force-color", action="store_true", help="цвета даже без TTY")
    common.add_argument("--yamlite", action="store_true",
                        help="использовать встроенный парсер YAML вместо PyYAML (как на Android)")

    sub = parser.add_subparsers(dest="command")

    # --- search ---
    p = sub.add_parser("search", aliases=["find"], help="найти самые низкие цены", parents=[common])
    p.add_argument("query", nargs="*", help="название товара (например: \"iphone 15 128gb\")")
    p.add_argument("-f", "--queries-file", nargs="?", const=str(paths.queries_file()), metavar="FILE",
                   help="взять товары из списка (по умолчанию queries.txt): товар ; цена ; %% падения ; сайты")
    p.add_argument("-s", "--sites", help="список сайтов через запятую (по умолчанию все включённые)")
    p.add_argument("--all-sites", action="store_true", help="использовать все сайты из конфига, включая выключенные")
    p.add_argument("-n", "--top", type=int, default=20, help="сколько позиций показать (по умолчанию 20)")
    p.add_argument("--per-site", type=int, default=60, help="максимум карточек с одного сайта")
    p.add_argument("--pages", type=int, help="сколько страниц выдачи обойти (иначе из конфига)")
    p.add_argument("--min-price", type=float, help="отсечь цены ниже (мусор, доставка)")
    p.add_argument("--max-price", type=float, help="отсечь цены выше")
    p.add_argument("--max-ratio", type=float, default=0, help="показывать только цены ≤ минимум×N (например 1.5)")
    p.add_argument("--include", nargs="*", help="оставить только товары с этими словами")
    p.add_argument("--exclude", nargs="*", help="исключить товары со словами (например 'б/у витрина')")
    p.add_argument("--require-keyword", action="store_true", help="требовать вхождения слов запроса в название")
    p.add_argument("--in-stock", action="store_true", help="только товары в наличии")
    p.add_argument("--workers", type=int, default=4, help="параллельных потоков на сайты")
    p.add_argument("--timeout", type=float, help="таймаут запроса, сек")
    p.add_argument("--retries", type=int, help="повторов при ошибках/антиботе")
    p.add_argument("--delay", type=float, help="пауза между запросами, сек")
    p.add_argument("--proxy", help="прокси, напр. http://127.0.0.1:8080")
    p.add_argument("--user-agent", help="свой User-Agent")
    p.add_argument("--js", action="store_true", help="принудительно рендерить страницы в браузере (Playwright)")
    p.add_argument("--no-js", action="store_true", help="принудительно отключить браузерный рендер")
    p.add_argument("--ignore-robots", action="store_true", help="не проверять robots.txt (на свой риск)")
    p.add_argument("--insecure", action="store_true", help="не проверять TLS-сертификаты")
    p.add_argument("--update-rates", action="store_true", help="подтянуть живые курсы валют")
    p.add_argument("--by-site", action="store_true", help="показать сводку по площадкам")
    p.add_argument("--best", action="store_true", help="подробно про лучшее предложение")
    p.add_argument("--show-errors", action="store_true", help="показать детали ошибок источников")
    p.add_argument("--no-history", action="store_true", help="не писать историю в БД")
    p.add_argument("--quiet", action="store_true", help="меньше поясняющих сообщений")
    p.add_argument("--width", type=int, default=118, help="ширина таблицы")
    p.add_argument("--no-url", action="store_true", help="скрыть колонку ссылок")
    p.add_argument("--no-merge", action="store_true",
                   help="не схлопывать одинаковые товары с разных площадок")
    p.add_argument("--csv", metavar="FILE", help="сохранить в CSV")
    p.add_argument("--json", dest="json_out", metavar="FILE", help="сохранить в JSON")
    p.add_argument("--xlsx", metavar="FILE", help="сохранить в Excel")
    p.add_argument("--html", metavar="FILE", help="сохранить HTML-отчёт")
    p.add_argument("--save", metavar="FILE", help="сохранить в файл (формат по расширению)")
    p.set_defaults(func=cmd_search)

    # --- watch ---
    w = sub.add_parser("watch", help="мониторинг цен с уведомлениями", parents=[common])
    w.add_argument("query", nargs="*", help="что мониторить (без аргумента — цели из queries.txt/БД)")
    w.add_argument("-f", "--queries-file", nargs="?", const=str(paths.queries_file()), metavar="FILE",
                   help="взять товары и пороги цен из списка (по умолчанию queries.txt)")
    w.add_argument("-i", "--interval", default="30m", help="интервал: 30m / 2h / 1d / 900 (сек)")
    w.add_argument("--target-price", type=float, help="порог цены для уведомления")
    w.add_argument("--drop-pct", type=float, help="уведомлять при падении цены на N%% за шаг")
    w.add_argument("--alert-cooldown", type=float, default=6.0,
                   help="не повторять уведомление о достижении цели чаще, чем раз в N часов (0 — без защиты)")
    w.add_argument("--once", action="store_true", help="один цикл и выйти")
    w.add_argument("--runs", type=int, help="сколько циклов выполнить")
    w.add_argument("--save", metavar="FILE", help="сохранять снимок каждую итерацию (можно {query} в имени)")
    w.add_argument("-s", "--sites", help="сайты через запятую")
    w.add_argument("--per-site", type=int, default=40)
    w.add_argument("--pages", type=int)
    w.add_argument("--min-price", type=float)
    w.add_argument("--max-price", type=float)
    w.add_argument("--max-ratio", type=float, default=0)
    w.add_argument("--exclude", nargs="*")
    w.add_argument("--in-stock", action="store_true")
    w.add_argument("--workers", type=int, default=4)
    w.add_argument("--timeout", type=float)
    w.add_argument("--retries", type=int)
    w.add_argument("--delay", type=float)
    w.add_argument("--proxy")
    w.add_argument("--user-agent")
    w.add_argument("--js", action="store_true")
    w.add_argument("--ignore-robots", action="store_true")
    w.add_argument("--insecure", action="store_true")
    w.add_argument("--update-rates", action="store_true")
    w.add_argument("--all-sites", action="store_true")
    w.set_defaults(func=cmd_watch)

    # --- sites ---
    s = sub.add_parser("sites", help="показать настроенные источники", parents=[common])
    s.set_defaults(func=cmd_sites)

    # --- test-site ---
    t = sub.add_parser("test-site", help="диагностика парсинга одного сайта", parents=[common])
    t.add_argument("site", help="id сайта из конфига")
    t.add_argument("query", nargs="?", default="товар", help="поисковый запрос")
    t.add_argument("--pages", type=int)
    t.add_argument("--sample", type=int, default=10, help="сколько карточек показать")
    t.add_argument("--dump-html", metavar="FILE", help="сохранить полученный HTML")
    t.add_argument("--js", action="store_true", help="рендерить в браузере")
    t.add_argument("--min-price", type=float)
    t.add_argument("--max-price", type=float)
    t.add_argument("--require-keyword", action="store_true")
    t.add_argument("--timeout", type=float)
    t.add_argument("--retries", type=int)
    t.add_argument("--delay", type=float)
    t.add_argument("--proxy")
    t.add_argument("--user-agent")
    t.add_argument("--ignore-robots", action="store_true")
    t.add_argument("--insecure", action="store_true")
    t.set_defaults(func=cmd_test_site)

    # --- history ---
    h = sub.add_parser("history", help="история цен из БД", parents=[common])
    h.add_argument("--query", help="фильтр по тексту запроса")
    h.add_argument("--filter", help="фильтр по названию товара/площадке")
    h.add_argument("--limit", type=int, default=25)
    h.add_argument("--points", type=int, default=40, help="точек в графике")
    h.set_defaults(func=cmd_history)

    # --- targets ---
    g = sub.add_parser("targets", help="цели мониторинга", parents=[common])
    gsub = g.add_subparsers(dest="targets_action", required=True)
    ga = gsub.add_parser("add", help="добавить цель", parents=[common])
    ga.add_argument("query", nargs="+")
    ga.add_argument("--sites")
    ga.add_argument("--target-price", type=float)
    ga.add_argument("--drop-pct", type=float)
    ga.add_argument("--notify", default="telegram,email")
    gl = gsub.add_parser("list", help="список целей", parents=[common])
    gl.add_argument("--all", action="store_true", help="включая отключённые")
    gr = gsub.add_parser("remove", help="отключить цель", parents=[common])
    gr.add_argument("id", type=int)
    g.set_defaults(func=cmd_targets)

    # --- parse-price ---
    pp = sub.add_parser("parse-price", help="проверить, как распознаётся цена из текста", parents=[common])
    pp.add_argument("text", nargs="+")
    pp.add_argument("--currency", default="RUB")
    pp.set_defaults(func=cmd_parse_price)

    # --- update-rates ---
    ur = sub.add_parser("update-rates", help="получить/записать курсы валют", parents=[common])
    ur.add_argument("--base", default="RUB")
    ur.add_argument("--currencies", help="список кодов через запятую")
    ur.add_argument("--write-config", action="store_true", help="обновить блок currencies в конфиге")
    ur.set_defaults(func=cmd_update_rates)

    # --- init-config ---
    ic = sub.add_parser("init-config", help="создать конфиг сайтов из шаблона", parents=[common])
    ic.add_argument("-o", "--output")
    ic.add_argument("--force", action="store_true")
    ic.set_defaults(func=cmd_init_config)

    # --- init-queries ---
    iq = sub.add_parser("init-queries", help="создать список товаров queries.txt", parents=[common])
    iq.add_argument("-o", "--output", help="куда сохранить (по умолчанию — папка данных, см. `env`)")
    iq.add_argument("--force", action="store_true", help="перезаписать существующий")
    iq.set_defaults(func=cmd_init_queries)

    # --- env ---
    env = sub.add_parser("env", help="показать окружение и пути (диагностика на телефоне)", parents=[common])
    env.set_defaults(func=cmd_env)

    # --- notify-test ---
    nt = sub.add_parser("notify-test", help="проверить уведомления (Android/Telegram/e-mail)", parents=[common])
    nt.set_defaults(func=cmd_notify_test)

    # --- gui ---
    gui = sub.add_parser("gui", help="запустить сенсорный интерфейс (Kivy; на Android — основной режим)",
                         parents=[common])
    gui.add_argument("--selftest", action="store_true",
                     help="проверить логику интерфейса без создания окна")
    gui.set_defaults(func=cmd_gui)

    # --- serve-demo ---
    sd = sub.add_parser("serve-demo", help="запустить локальный демо-магазин для проверки парсера", parents=[common])
    sd.add_argument("--port", type=int, default=8765)
    sd.set_defaults(func=cmd_serve_demo)

    return parser


# Атрибуты, которые должны существо у args независимо от подкоманды
_DEFAULTS: dict[str, object] = {
    "color": True,
    "min_price": None,
    "max_price": None,
    "max_ratio": 0.0,
    "csv": None,
    "json_out": None,
    "xlsx": None,
    "html": None,
    "save": None,
    "sites": None,
    "all_sites": False,
    "workers": 4,
    "timeout": None,
    "retries": None,
    "delay": None,
    "proxy": None,
    "user_agent": None,
    "js": False,
    "no_js": False,
    "ignore_robots": False,
    "insecure": False,
    "update_rates": False,
    "per_site": 60,
    "pages": None,
    "in_stock": False,
    "include": None,
    "exclude": None,
    "require_keyword": False,
    "quiet": False,
    "width": 118,
    "no_url": False,
    "by_site": False,
    "best": False,
    "show_errors": False,
    "no_history": False,
    "no_merge": False,
    "verbose": False,
    "queries_file": None,
    "yamlite": False,
    "query": [],
    "force_color": False,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    top, rest = parser.parse_known_args(argv)
    if not getattr(top, "command", None):
        parser.print_help()
        raise SystemExit(2)
    args = parser.parse_args(rest, namespace=top)  # флаги работают и до, и после подкоманды
    for name, default in _DEFAULTS.items():
        if not hasattr(args, name) or getattr(args, name) is None:
            setattr(args, name, default)
    args.color = (not args.no_color) and (bool(args.force_color) or sys.stdout.isatty())
    # На Android папка программы только для чтения — копируем конфиг и список
    # товаров в папку данных при первом запуске.
    paths.ensure_user_files(verbose=bool(getattr(args, "verbose", False)))
    return int(args.func(args) or 0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nПрервано.")
        raise SystemExit(130)
