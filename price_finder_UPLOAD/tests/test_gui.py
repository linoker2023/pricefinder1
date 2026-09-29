#!/usr/bin/env python3
"""Тесты «мобильной» части: встроенный YAML-парсер, пути, логика GUI, Android-хуки.

Запуск:
    python tests/test_gui.py
    pytest tests/ -q
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pricefinder import gui_logic as logic                     # noqa: E402
from pricefinder import paths, yamlite                         # noqa: E402
from pricefinder.parsers import Item                           # noqa: E402
from pricefinder.sites import config_from_dict, parse_interval  # noqa: E402

CONFIG_TEXT = (ROOT / "config" / "sites.yaml").read_text(encoding="utf-8")


@contextmanager
def sandbox_home(config_text: str | None = None):
    """Временная «папка приложения» — как на Android, где проект только для чтения."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        env = {"PRICEFINDER_HOME": str(home)}
        if config_text is not None:
            cfg_dir = home / "config"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            (cfg_dir / "sites.yaml").write_text(config_text, encoding="utf-8")
            env["PRICEFINDER_CONFIG"] = str(cfg_dir / "sites.yaml")
        saved = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        try:
            yield home
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


# --- 1. Встроенный парсер YAML (на Android PyYAML может не быть) -------------

def test_yamlite_parses_real_config():
    data = yamlite.safe_load(CONFIG_TEXT)
    assert isinstance(data, dict)
    sites = data["sites"]
    assert isinstance(sites, list) and len(sites) >= 10
    demo = next(s for s in sites if s["id"] == "demo")
    assert demo["enabled"] is True
    assert demo["search_url"] == "http://127.0.0.1:8765/search?q={query}"
    assert demo["fields"]["title"] == ".product-card__title"
    assert demo["min_price"] == 1
    assert data["settings"]["currencies"]["base"] == "RUB"
    assert data["settings"]["currencies"]["rates"]["USD"] == 92.0
    assert data["settings"]["respect_robots"] is True


def test_yamlite_matches_pyyaml():
    """Если PyYAML есть — результаты обязаны совпасть полностью."""
    try:
        import yaml
    except ImportError:
        print("    (PyYAML не установлен — сравнение пропущено)")
        return
    assert yamlite.safe_load(CONFIG_TEXT) == yaml.safe_load(CONFIG_TEXT), \
        "yamlite разобрал конфиг не так, как PyYAML"


def test_yamlite_edge_cases():
    text = """
# комментарий
settings:
  timeout: 20
  empty:
  flag: false
  list: [a, b, "c,d"]
  inline: {x: 1, y: 2.5}
  block: |
    строка 1
    строка 2
sites:
  - id: one
    name: "Первый"
    enabled: true
    exclude_keywords: ["б/у", "витрина"]
  - id: two
    name: 'Второй'
    enabled: false
    fields:
      title: ".t"
      price: "min:.p"
"""
    data = yamlite.safe_load(text)
    assert data["settings"]["timeout"] == 20
    assert data["settings"]["empty"] is None
    assert data["settings"]["flag"] is False
    assert data["settings"]["list"] == ["a", "b", "c,d"]          # запятая в кавычках не режет
    assert data["settings"]["inline"] == {"x": 1, "y": 2.5}
    assert data["settings"]["block"].strip().splitlines() == ["строка 1", "строка 2"]
    assert data["sites"][0]["exclude_keywords"] == ["б/у", "витрина"]
    assert data["sites"][1]["fields"]["price"] == "min:.p"
    assert data["sites"][0]["name"] == "Первый"


def test_config_works_without_pyyaml():
    """Собираем конфиг через yamlite — и он превращается в рабочие SiteConfig."""
    cfg = config_from_dict(yamlite.safe_load(CONFIG_TEXT))
    assert cfg.by_id("demo") is not None
    assert cfg.by_id("demo").build_page_urls("ноутбук")[0].endswith(
        "search?q=%D0%BD%D0%BE%D1%83%D1%82%D0%B1%D1%83%D0%BA")
    assert [s.id for s in cfg.enabled()]
    assert cfg.settings["currencies"]["base"] == "RUB"


# --- 2. Пути и определение платформы ----------------------------------------

def test_paths_and_environment():
    assert paths.app_dir().exists()
    assert paths.is_writable(paths.out_dir())
    assert paths.default_db_path().name.endswith(".db")
    assert paths.platform_name() in ("linux", "darwin", "windows", "android",
                                     "android-termux", "android-apk")
    report = paths.environment_report()
    assert "Python:" in report and "requests" in report


def test_paths_respect_env_override():
    with sandbox_home() as home:
        assert paths.app_dir() == home
        assert paths.default_db_path() == home / "price_finder.db"
        assert paths.out_dir() == home / "out"
        assert paths.queries_file() == home / "queries.txt"


def test_resolve_output_path():
    with sandbox_home() as home:
        assert paths.resolve_output_path(str(home / "x.csv")) == home / "x.csv"
        assert paths.resolve_output_path("report.html") == home / "out" / "report.html"


def test_parse_interval():
    assert parse_interval("30m") == 1800.0
    assert parse_interval("2h") == 7200.0
    assert parse_interval("1d") == 86400.0
    assert parse_interval("900") == 900.0
    assert parse_interval(45) == 45.0
    assert parse_interval("3") == 3.0            # без суффикса — секунды
    assert parse_interval("3m") == 180.0
    assert parse_interval("0.5m") == 30.0
    try:
        parse_interval("полчаса")
    except ValueError:
        pass
    else:
        raise AssertionError("ожидали ValueError для «полчаса»")


# --- 3. Логика интерфейса ---------------------------------------------------

def test_gui_settings_roundtrip():
    with sandbox_home():
        defaults = logic.load_gui_settings()
        assert defaults["top"] == logic.DEFAULT_GUI_SETTINGS["top"]
        defaults["top"] = 7
        defaults["exclude"] = "б/у, витрина"
        defaults["in_stock_only"] = True
        path = logic.save_gui_settings(defaults)
        assert path.exists()
        again = logic.load_gui_settings()
        assert again["top"] == 7 and again["in_stock_only"] is True
        assert logic._split_words(again["exclude"]) == ["б/у", "витрина"]


def test_query_entries_and_file_io():
    entries = logic.query_entries(
        "# комментарий\niphone 15 ; 60000 ; 5 ; bookvoed\nноутбук\nнаушники | 5000 | 7\n"
        "пылесос ; - ; - ; demo\n\n   # ещё комментарий\n"
    )
    assert [e["query"] for e in entries] == ["iphone 15", "ноутбук", "наушники", "пылесос"]
    assert entries[0] == {"query": "iphone 15", "target_price": 60000.0,
                          "drop_pct": 5.0, "sites": "bookvoed"}
    assert entries[2]["drop_pct"] == 7.0
    assert entries[3]["target_price"] is None and entries[3]["sites"] == "demo"

    with sandbox_home():
        path = logic.write_queries_text("чайник ; 3000\n")
        assert path.exists() and logic.read_queries_text().startswith("чайник")
        assert logic.query_entries()[0]["target_price"] == 3000.0


def test_formatting_helpers():
    item = Item(site_id="a", site_name="Магазин", title="Товар X", price=100.0,
                currency="RUB", normalized_price=100.0)
    row = logic.format_row(1, item, "RUB", median=150.0)
    assert row.startswith("1. 100 ₽") and "−33%" in row and "Магазин" in row

    item.also_at = ["Другой"]
    assert "+1" in logic.format_row(1, item, "RUB")

    assert logic.summary_line([]).startswith("Ничего не найдено")
    assert "мин 100 ₽" in logic.summary_line([item])
    assert logic.median_price([item]) == 100.0
    assert logic.currency_symbol("USD") == "$"
    assert logic.truncate("абвгде", 3) == "аб…"


def test_spark():
    assert logic.spark([]) == ""
    assert logic.spark([5, 5, 5]) == "▄▄▄"
    line = logic.spark([100, 90, 95, 80, 85, 70])
    assert len(line) == 6 and line[-1] == "▁" and line[0] == "█"


def test_set_sites_enabled_edits_yaml():
    """Включение/выключение площадок правит текст конфига (работает и без PyYAML)."""
    with sandbox_home(CONFIG_TEXT) as home:
        logic.set_sites_enabled(["bookvoed", "demo"], enabled=True)
        data = yamlite.safe_load((home / "config" / "sites.yaml").read_text(encoding="utf-8"))
        by_id = {s["id"]: s for s in data["sites"]}
        assert by_id["bookvoed"]["enabled"] is True
        assert by_id["demo"]["enabled"] is True
        assert by_id["demo2"]["enabled"] is False
        assert by_id["ozon"]["enabled"] is False
        assert by_id["demo"]["fields"]["title"] == ".product-card__title"   # структура цела


def test_diagnose_site_reports_unknown_id():
    text = logic.diagnose_site("такого_сайта_нет", "товар", logic.DEFAULT_GUI_SETTINGS)
    assert "не найден в конфиге" in text and "demo" in text


# --- 4. Живой поиск через логику GUI (демо-сервер) ---------------------------

def test_gui_run_search_with_demo_server():
    import socket
    import time

    port = 8897
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "tests" / "demo_server.py"), "--port", str(port), "--quiet"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("демо-сервер не поднялся")

        with sandbox_home(CONFIG_TEXT.replace("8765", str(port))) as home:
            settings = dict(logic.DEFAULT_GUI_SETTINGS)
            items, errors, message = logic.run_search("ноутбук", ["demo"], settings)
            assert errors == [], errors
            assert len(items) == 4, message
            prices = [i.price for i in items]
            assert prices == sorted(prices) and prices[0] == 24990.0
            assert "4 предложений" in message

            # история пишется в базу приложения (на Android — в ~/pricefinder)
            rows = logic.history_rows(limit=5)
            assert rows and rows[0]["last"] == 24990.0 and rows[0]["spark"]

            # диагностика источника
            report = logic.diagnose_site("demo", "наушники", settings)
            assert "HTTP 200" in report and "карточек: 2" in report

            # сохранение отчётов в папку приложения
            from pricefinder import reports

            saved = reports.save_csv(items, paths.out_dir() / "r.csv")
            assert saved.exists() and home in saved.parents
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


# --- 5. Android-специфика ----------------------------------------------------

def test_wakelock_and_open_url_are_safe_off_android():
    """На обычном компьютере Android-хуки не должны падать."""
    assert logic.set_wakelock(True) in (True, False)
    assert logic.set_wakelock(False) in (True, False)
    assert logic.open_url("") is False


def test_notify_detects_termux():
    from pricefinder.notify import Notifier

    notifier = Notifier()
    assert notifier.termux_available() in (True, False)
    notifier.termux = False
    assert notifier.termux_available() is False
    status = Notifier().send("тема", "<b>текст</b>", "текст")
    assert isinstance(status, dict)


def test_android_scripts_are_valid_bash():
    if subprocess.run(["bash", "--version"], capture_output=True).returncode != 0:
        print("    (bash недоступен — проверка скриптов пропущена)")
        return
    scripts = sorted((ROOT / "android").glob("*.sh")) + [
        ROOT / "run_demo.sh", ROOT / "setup.sh", ROOT / "search.sh", ROOT / "watch.sh"]
    assert scripts, "скрипты не найдены"
    for script in scripts:
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script.name}: {result.stderr}"


def test_buildozer_spec_is_sane():
    spec = (ROOT / "android" / "buildozer.spec").read_text(encoding="utf-8")
    assert "source.main = gui_app.py" in spec
    assert "INTERNET" in spec
    assert "WAKE_LOCK" in spec

    # анализируем только строку requirements, без комментариев
    requirements = [line for line in spec.splitlines()
                    if line.startswith("requirements =")]
    assert requirements, "в spec нет строки requirements"
    deps = {d.strip().lower() for d in requirements[0].split("=", 1)[1].split(",")}
    for required in ("python3", "kivy", "requests", "beautifulsoup4"):
        assert any(d.startswith(required) for d in deps), f"в APK не хватает {required}"
    # тяжёлые/ненужные зависимости не должны попадать в сборку
    for unwanted in ("pyyaml", "yaml", "openpyxl", "playwright"):
        assert not any(d.startswith(unwanted) for d in deps), f"{unwanted} не нужен в APK"


def test_gui_module_compiles_and_selftest_runs():
    import py_compile

    py_compile.compile(str(ROOT / "gui_app.py"), doraise=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "gui_app.py"), "--selftest"],
        capture_output=True, text=True, timeout=240, cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "площадок в конфиге" in result.stdout


# --- runner ------------------------------------------------------------------

def main() -> int:
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
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
