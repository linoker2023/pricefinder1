"""Логика графического интерфейса — без импорта Kivy.

Вынесено отдельно, чтобы её можно было тестировать на любом устройстве
(в том числе в Termux без графики) и переиспользовать из gui_app.py.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import paths
from .notify import Notifier
from .parsers import Item, merge_same_offers
from .price import CURRENCY_CODES, Converter
from .reports import fmt
from .fetcher import Fetcher
from .price import fetch_live_rates
from .search import SearchEngine, apply_ratio_filter
from .sites import parse_interval
from .sites import AppConfig, SiteConfig, load_config
from .storage import Storage

DEFAULT_GUI_SETTINGS: dict[str, Any] = {
    "top": 20,                 # сколько предложений показывать
    "pages": 1,                # страниц выдачи на сайт
    "min_price": None,
    "max_price": None,
    "max_ratio": 0.0,          # 0 = выключено; 1.5 = не показывать дороже «минимум × 1.5»
    "exclude": "",             # слова-исключения через запятую
    "in_stock_only": False,
    "require_keyword": False,
    "delay": 1.0,
    "timeout": 20,
    "retries": 2,
    "js_render": False,        # рендерить сайты в браузере (нужен Playwright)
    "update_rates": False,
    "interval_minutes": 30,    # период мониторинга
    "drop_pct": 3.0,           # уведомлять при падении на N%
    "save_history": True,
    "wakelock": False,
}


def settings_path() -> Path:
    return paths.app_dir() / "gui_settings.json"


def load_gui_settings() -> dict[str, Any]:
    data = dict(DEFAULT_GUI_SETTINGS)
    file_path = settings_path()
    if file_path.exists():
        try:
            stored = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                data.update(stored)
        except (json.JSONDecodeError, OSError):
            pass
    return data


def save_gui_settings(settings: dict[str, Any]) -> Path:
    file_path = settings_path()
    file_path.write_text(
        json.dumps({k: settings.get(k, DEFAULT_GUI_SETTINGS.get(k)) for k in DEFAULT_GUI_SETTINGS},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return file_path


# --- поиск в фоне ----------------------------------------------------------


@dataclass
class SearchTask:
    """Фоновый поиск: запускается в потоке, результат отдаётся колбэком в UI-поток."""

    query: str
    site_ids: list[str]
    settings: dict[str, Any]
    on_done: Callable[[list[Item], list[dict[str, str]], str], None]
    items: list[Item] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    message: str = ""
    thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            items, errors, message = run_search(self.query, self.site_ids, self.settings)
        except Exception as exc:  # noqa: BLE001
            items, errors, message = [], [], f"Ошибка: {type(exc).__name__}: {exc}"
        self.items, self.errors, self.message = items, errors, message
        self.on_done(items, errors, message)


def run_search(query: str, site_ids: list[str] | None, settings: dict[str, Any],
               prefer_yamlite: bool = False) -> tuple[list[Item], list[dict[str, str]], str]:
    """Один поиск. Возвращает (карточки, ошибки, текст статуса)."""
    query = (query or "").strip()
    if not query:
        return [], [], "Введите название товара"

    config = load_config(prefer_yamlite=prefer_yamlite)
    sites = _select_sites(config, site_ids)
    if not sites:
        return [], [], "Нет включённых площадок. Вкладка «Сайты» → отметьте нужные → Сохранить."

    engine = _make_engine(config, settings)
    try:
        result = engine.search(
            query,
            sites,
            limit_per_site=40,
            pages=_int(settings.get("pages"), 1),
            min_price=_float_or_none(settings.get("min_price")),
            max_price=_float_or_none(settings.get("max_price")),
            exclude_keywords=_split_words(settings.get("exclude")),
            require_keyword=bool(settings.get("require_keyword")),
            in_stock_only=bool(settings.get("in_stock_only")),
        )
    finally:
        engine.fetcher.close()

    items = merge_same_offers(apply_ratio_filter(result.items, _float(settings.get("max_ratio"), 0.0)))
    if settings.get("save_history", True) and items:
        try:
            storage = Storage(paths.default_db_path())
            storage.save_items(items, query=query)
            storage.log_search(query, [s.name for s in sites], items, items[0])
            storage.close()
        except Exception:  # noqa: BLE001
            pass

    message = f"{len(items)} предложений за {result.elapsed:.1f} с · источников: {len(sites)}"
    if result.errors:
        message += f" · ошибок: {len(result.errors)}"
    return items, result.errors, message


def _select_sites(config: AppConfig, site_ids: list[str] | None) -> list[SiteConfig]:
    if not site_ids:
        return config.enabled()
    wanted = {str(s).strip().lower() for s in site_ids}
    chosen = [s for s in config.sites if s.id.lower() in wanted]
    return chosen or config.enabled()


def _make_engine(config: AppConfig, settings: dict[str, Any]) -> SearchEngine:
    currencies = dict(FALLBACK_RATES)
    currencies.update({str(k).upper(): float(v)
                       for k, v in ((config.settings.get("currencies") or {}).get("rates") or {}).items()})
    if settings.get("update_rates"):
        base = str((config.settings.get("currencies") or {}).get("base", "RUB")).upper()
        currencies.update(fetch_live_rates(base))

    fetcher_kwargs: dict[str, Any] = {
        "timeout": _float(settings.get("timeout"), 20.0),
        "retries": _int(settings.get("retries"), 2),
        "delay": _float(settings.get("delay"), 1.0),
        "respect_robots": bool(config.settings.get("respect_robots", True)),
        "user_agent": str(config.settings.get("user_agent") or ""),
        "proxy": str(config.settings.get("proxy") or ""),
    }
    engine = SearchEngine(
        config,
        Fetcher(**fetcher_kwargs),
        workers=4,
        force_js=True if settings.get("js_render") else None,
    )
    engine.converter = Converter(base=str((config.settings.get("currencies") or {}).get("base", "RUB")).upper(),
                                 rates=currencies)
    return engine


# Курсы-заглушки на случай отсутствия сети (совпадают с CLI)
FALLBACK_RATES = {
    "USD": 92.0, "EUR": 100.0, "CNY": 12.7, "KZT": 0.2, "BYN": 28.0, "UAH": 2.3,
    "GBP": 117.0, "TRY": 2.8, "GEL": 34.0, "AMD": 0.23, "AZN": 54.0, "PLN": 23.0,
    "JPY": 0.6, "UZS": 0.0073, "KGS": 1.05, "MDL": 5.2, "INR": 1.1,
}


# --- представление результатов --------------------------------------------


def currency_symbol(config_base: str = "RUB") -> str:
    return CURRENCY_CODES.get((config_base or "RUB").upper(), config_base)


def format_row(index: int, item: Item, base: str = "RUB", median: float | None = None) -> str:
    """Однострочное представление карточки для списка в интерфейсе."""
    price = item.normalized_price if item.normalized_price is not None else item.price
    sym = currency_symbol(base)
    gain = ""
    if median and price:
        diff = (median - price) / median * 100
        if abs(diff) >= 0.5:
            gain = f"  ({'−' if diff > 0 else '+'}{abs(diff):.0f}%)"
    site = item.site_name + (f" +{len(item.also_at)}" if item.also_at else "")
    stock = " · нет в наличии" if _out_of_stock(item.availability) else ""
    return f"{index}. {fmt(price, sym)}{gain}\n    {truncate(item.title, 90)}\n    {site}{stock}"


def _out_of_stock(availability: str) -> bool:
    text = (availability or "").lower()
    return bool(text) and ("нет" in text or "out" in text or "отсут" in text)


def truncate(text: str, width: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= width else text[: max(1, width - 1)] + "…"


def summary_line(items: list[Item], base: str = "RUB") -> str:
    from .parsers import summarize

    stats = summarize(items)
    if not stats.get("count"):
        return "Ничего не найдено"
    sym = currency_symbol(base)
    return (f"мин {fmt(stats['min'], sym)} · медиана {fmt(stats['median'], sym)} · "
            f"макс {fmt(stats['max'], sym)} · разброс {stats['spread_pct']}%")


def median_price(items: list[Item]) -> float | None:
    from .parsers import summarize

    stats = summarize(items)
    return stats.get("median")


# --- история ---------------------------------------------------------------


def history_rows(limit: int = 30, needle: str = "") -> list[dict[str, Any]]:
    """Позиции из базы истории цен, отсортированные по текущей цене."""
    db_path = paths.default_db_path()
    if not db_path.exists():
        return []
    storage = Storage(db_path)
    try:
        rows = storage.all_items(limit=limit * 3)
        needle = (needle or "").strip().lower()
        if needle:
            rows = [r for r in rows if needle in (r.get("title") or "").lower()
                    or needle in (r.get("site_name") or "").lower()]
        out: list[dict[str, Any]] = []
        for row in rows[:limit]:
            hist = storage.history(row["uid"], limit=40)
            prices = [h["price"] for h in reversed(hist) if h.get("price") is not None]
            out.append({
                "uid": row["uid"],
                "title": row.get("title") or "",
                "site": row.get("site_name") or "",
                "url": row.get("url") or "",
                "last": prices[-1] if prices else row.get("last_price"),
                "low": min(prices) if prices else None,
                "high": max(prices) if prices else None,
                "points": len(prices),
                "spark": spark(prices),
            })
        out.sort(key=lambda r: (r["last"] is None, r["last"] or 0))
        return out
    finally:
        storage.close()


SPARKS = "▁▂▃▄▅▆▇█"


def spark(values: list[float], width: int = 24) -> str:
    series = [v for v in values if v is not None][-width:]
    if not series:
        return ""
    lo, hi = min(series), max(series)
    if hi - lo < 1e-9:
        return SPARKS[3] * len(series)
    return "".join(SPARKS[int((v - lo) / (hi - lo) * (len(SPARKS) - 1))] for v in series)


# --- список товаров (queries.txt) ------------------------------------------


def queries_file() -> Path:
    return paths.queries_file()


def read_queries_text() -> str:
    path = queries_file()
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""
    return ""


def write_queries_text(text: str) -> Path:
    path = queries_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def query_entries(text: str | None = None) -> list[dict[str, Any]]:
    """Разбирает список товаров (тот же формат, что queries.txt)."""
    text = read_queries_text() if text is None else text
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[;|]", line)]
        parts = ["" if p in {"-", "—", "–"} else p for p in parts]
        entry: dict[str, Any] = {"query": parts[0], "target_price": None, "drop_pct": None, "sites": None}
        if len(parts) > 1 and parts[1]:
            try:
                entry["target_price"] = float(re.sub(r"[^\d.,]", "", parts[1]).replace(",", "."))
            except ValueError:
                pass
        if len(parts) > 2 and parts[2]:
            try:
                entry["drop_pct"] = float(parts[2].replace(",", "."))
            except ValueError:
                pass
        if len(parts) > 3 and parts[3]:
            entry["sites"] = parts[3]
        if entry["query"]:
            entries.append(entry)
    return entries


# --- диагностика одного источника (для вкладки «Сайты») ---------------------


def diagnose_site(site_id: str, query: str, settings: dict[str, Any], sample: int = 5) -> str:
    """Текстовый отчёт о том, что происходит с конкретным сайтом."""
    from .fetcher import Fetcher
    from .parsers import parse_items
    from .price import Converter
    from .reports import fmt
    from .sites import load_config

    config = load_config()
    site = config.by_id(site_id or "")
    if site is None:
        available = ", ".join(s.id for s in config.sites) or "пусто"
        return f"Сайт «{site_id}» не найден в конфиге.\nДоступные id: {available}"
    query = (query or "товар").strip()

    fetcher = Fetcher(
        timeout=_float(settings.get("timeout"), 20.0),
        retries=_int(settings.get("retries"), 2),
        delay=_float(settings.get("delay"), 1.0),
        respect_robots=bool(config.settings.get("respect_robots", True)),
    )
    converter = Converter(
        base=str((config.settings.get("currencies") or {}).get("base", "RUB")).upper(),
        rates={str(k).upper(): float(v)
               for k, v in ((config.settings.get("currencies") or {}).get("rates") or {}).items()},
    )
    lines = [f"Сайт: {site.name} ({site.id})", f"Запрос: {query}"]
    try:
        for url in site.build_page_urls(query, 1):
            lines.append(f"URL: {url}")
            result = fetcher.get(
                url,
                method=site.method,
                post_data=site.post_data or None,
                headers=site.headers or None,
                cookies=site.cookies or None,
                js_render=bool(settings.get("js_render") or site.js_render),
                render_wait=site.render_wait,
                wait_selector=site.wait_selector,
            )
            lines.append(f"Ответ: HTTP {result.status} · движок {result.engine} · "
                         f"{len(result.html)} байт · {result.elapsed:.1f} с")
            if result.error:
                lines.append(f"Ошибка: {result.error}")
            if not result.html:
                continue
            items, strategy = parse_items(
                result.html, site=site, page_url=result.url, query=query, converter=converter,
                min_price=site.min_price, max_price=site.max_price,
            )
            lines.append(f"Стратегия: {strategy} · карточек: {len(items)}")
            for item in items[:sample]:
                lines.append(f"  {fmt(item.price, converter.symbol(item.currency))} | "
                             f"{truncate(item.title, 60)} | {truncate(item.url, 60)}")
            if not items:
                lines.append("Подсказки:")
                lines.append("  • включите «JS-рендер сайтов» в настройках (нужен Playwright);")
                lines.append("  • проверьте селекторы: product_selector / fields в config/sites.yaml;")
                lines.append("  • HTTP 403/429 — сайт блокирует робота: нужны cookies/прокси.")
    finally:
        fetcher.close()
    return "\n".join(lines)


# --- управление сайтами -----------------------------------------------------


def list_sites(prefer_yamlite: bool = False) -> list[SiteConfig]:
    return load_config(prefer_yamlite=prefer_yamlite).sites


def set_sites_enabled(site_ids: list[str], enabled: bool = True) -> Path:
    """Правит enabled: true/false прямо в тексте sites.yaml (работает и без PyYAML)."""
    config = load_config(prefer_yamlite=True)
    path = next((p for p in paths.config_search_paths() if p.exists()), None)
    if path is None:
        raise FileNotFoundError("config/sites.yaml не найден — выполните init-config")
    wanted = {str(s).strip().lower() for s in site_ids}
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    current_id: str | None = None
    for line in lines:
        match = re.match(r"^(\s*)-\s+id:\s*(.+?)\s*$", line)
        if match:
            current_id = match.group(2).strip().strip("\"'").lower()
            out.append(line)
            continue
        enabled_match = re.match(r"^(\s+)enabled:\s*(true|false)\s*$", line)
        if enabled_match and current_id is not None:
            value = "true" if (current_id in wanted) == enabled else "false"
            out.append(f"{enabled_match.group(1)}enabled: {value}")
            continue
        out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    del config
    return path


# --- мониторинг -------------------------------------------------------------


@dataclass
class WatchTask:
    """Цикл мониторинга в фоновом потоке (для кнопки «Следить» в приложении)."""

    entries: list[dict[str, Any]]
    settings: dict[str, Any]
    on_status: Callable[[str], None]
    on_alert: Callable[[str, str], None]
    interval_seconds: float = 1800.0
    stop_flag: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    cycles: int = 0

    def start(self) -> None:
        self.stop_flag.clear()
        if not self.interval_seconds or self.interval_seconds < 60:
            self.interval_seconds = parse_interval(
                f"{int(self.settings.get('interval_minutes', 30))}m")
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_flag.set()

    def _loop(self) -> None:
        import time

        config = load_config(prefer_yamlite=False)
        notifier = Notifier.from_settings(config.settings or {})
        storage = Storage(paths.default_db_path())
        while not self.stop_flag.is_set():
            self.cycles += 1
            for entry in self.entries:
                if self.stop_flag.is_set():
                    break
                query = entry["query"]
                site_ids = entry.get("sites").split(",") if entry.get("sites") else None
                items, errors, message = run_search(query, site_ids, self.settings)
                self.on_status(f"[{self.cycles}] «{query}»: {message}")
                if not items:
                    continue
                events = storage.save_items(items, query=query)
                target_price = entry.get("target_price")
                drop_pct = entry.get("drop_pct") or self.settings.get("drop_pct")
                for event in events:
                    item: Item = event["item"]
                    price = item.normalized_price if item.normalized_price is not None else (item.price or 0)
                    reasons: list[str] = []
                    if target_price and price <= float(target_price):
                        reasons.append(f"цена ниже цели {target_price:g}")
                    if event.get("is_all_time_low"):
                        reasons.append("исторический минимум")
                    if drop_pct and event.get("drop_pct") is not None and event["drop_pct"] <= -abs(float(drop_pct)):
                        reasons.append(f"падение на {abs(event['drop_pct']):.1f}%")
                    if not reasons:
                        continue
                    if storage.alert_seen(item.uid, "gui", price, cooldown_hours=6.0):
                        continue
                    storage.log_alert(item.uid, query, "gui", price,
                                      {"reasons": reasons, "title": item.title, "url": item.url})
                    text = f"{fmt(price)} — {truncate(item.title, 70)} ({item.site_name})"
                    self.on_alert(", ".join(reasons), text)
                    notifier.send(f"pricefinder: {query}", text, text)
            # спим частями, чтобы быстро реагировать на остановку
            waited = 0.0
            while waited < self.interval_seconds and not self.stop_flag.is_set():
                time.sleep(min(1.0, self.interval_seconds - waited))
                waited += 1.0
        storage.close()


# --- утилиты ---------------------------------------------------------------


def open_url(url: str) -> bool:
    """Открывает ссылку в браузере (на Android — системным интентом)."""
    if not url:
        return False
    try:
        import webbrowser

        webbrowser.open(url)
        return True
    except Exception:  # noqa: BLE001
        return False


def set_wakelock(enabled: bool) -> bool:
    """Termux: не давать телефону усыплять процесс во время мониторинга."""
    import shutil
    import subprocess

    command = "termux-wake-lock" if enabled else "termux-wake-unlock"
    if shutil.which(command) is None:
        return False
    try:
        subprocess.run([command], check=False, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:  # noqa: BLE001
        return False


def _int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _split_words(value: Any) -> list[str] | None:
    if not value:
        return None
    if isinstance(value, (list, tuple)):
        return [str(v).strip().lower() for v in value if str(v).strip()]
    words = [w.strip().lower() for w in re.split(r"[,;\n]+", str(value)) if w.strip()]
    return words or None
