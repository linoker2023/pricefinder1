#!/usr/bin/env python3
"""pricefinder — сенсорный интерфейс (Android/Termux, Pydroid, ПК).

Запуск:
    python price_finder.py gui              # из CLI (рекомендуется)
    python gui_app.py                       # напрямую
    python gui_app.py --selftest            # проверка логики БЕЗ окна и без kivy

Этот файл намеренно не импортирует Kivy на уровне модуля: в среде без дисплея
или OpenGL Kivy аварийно завершает процесс без понятного сообщения. Поэтому
сначала проверяется доступность графики (pricefinder.display.display_hint),
и только потом импортируются виджеты из pricefinder.gui_ui.

Точка входа для сборки APK (buildozer): функция main().
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Kivy разбирает sys.argv сам — отключаем, чтобы работали наши флаги (--selftest)
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")

from pricefinder import gui_logic as logic            # noqa: E402
from pricefinder import paths                         # noqa: E402
from pricefinder.display import display_hint          # noqa: E402


def setup_cyrillic_font() -> None:
    """Кириллица в Kivy: штатный Roboto не содержит русских букв.

    В комплекте Kivy есть DejaVuSans.ttf — регистрируем его как основной шрифт,
    на Android подходят системные DroidSans/NotoSans.
    """
    try:
        import kivy
        from kivy.core.text import LabelBase

        base = Path(kivy.__file__).resolve().parent / "data" / "fonts"
        candidates = [
            base / "DejaVuSans.ttf",
            Path("/system/fonts/DroidSans.ttf"),                       # Android
            Path("/system/fonts/NotoSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),   # Linux
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ]
        for path in candidates:
            if path.exists():
                LabelBase.register(name="Roboto", fn_regular=str(path))
                return
    except Exception:
        pass


def kivy_available() -> tuple[bool, str]:
    """Проверяет, импортируется ли Kivy (окно при этом не создаётся)."""
    try:
        import kivy  # noqa: F401

        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def kivy_install_hint(reason: str = "") -> str:
    """Инструкция по установке Kivy — показываем, если его нет."""
    return (
        "Для графического интерфейса нужен Kivy.\n\n"
        "  Termux (Android):\n"
        "      bash android/install_gui_termux.sh\n"
        "      termux-x11 :1 -ac &\n"
        "      export DISPLAY=:1\n"
        "      python price_finder.py gui\n\n"
        "  Pydroid 3: меню Pip → установить kivy\n"
        "  Компьютер: pip install kivy\n\n"
        + (f"  Причина здесь: {reason}\n\n" if reason else "")
        + "  Текстовый режим работает всегда и умеет то же самое:\n"
        '      python price_finder.py search "товар"\n'
        "      python price_finder.py search --queries-file\n"
        "      python price_finder.py gui --selftest   # проверка логики без окна"
    )


def main() -> int:
    """Создаёт и запускает окно. Возвращает код возврата."""
    ok, reason = kivy_available()
    if not ok:
        sys.stderr.write("\n" + kivy_install_hint(reason) + "\n\n")
        return 1
    hint = display_hint()
    if hint:
        sys.stderr.write("\n" + hint + "\n\n")
        return 2

    paths.ensure_user_files()
    setup_cyrillic_font()
    try:
        from kivy.config import Config

        Config.set("graphics", "width", "480")
        Config.set("graphics", "height", "900")
    except Exception:
        pass

    from pricefinder.gui_ui import PriceFinderApp

    PriceFinderApp().run()
    return 0


# =========================================================================
#  Самопроверка без графики (Termux без Termux:X11, CI, отладка)
# =========================================================================

def selftest() -> int:
    """Проверяет всю логику интерфейса, не создавая окно и не требуя Kivy."""
    import time

    def say(text: str = "") -> None:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()

    ok, reason = kivy_available()
    say("Самопроверка pricefinder (логика без графики)")
    say(f"  kivy: {'доступен' if ok else 'НЕ установлен — окно не запустится'}"
        + (f" ({reason})" if reason else ""))
    say(f"  платформа: {paths.platform_name()} · python {sys.version.split()[0]}")

    problems: list[str] = []

    settings = logic.load_gui_settings()
    say(f"  настройки: показывать {settings.get('top')} предложений, "
        f"период мониторинга {settings.get('interval_minutes')} мин")

    entries = logic.query_entries("iphone 15 ; 60000 ; 5\nноутбук\n# комментарий")
    if len(entries) != 2 or entries[0]["target_price"] != 60000.0:
        problems.append("список товаров разбирается неверно")
    say(f"  разбор списка товаров: {len(entries)} шт. — ok")

    qfile = logic.queries_file()
    say(f"  файл списка: {qfile}"
        + ("" if qfile.exists() else "  (не создан — python price_finder.py init-queries)"))
    if qfile.exists():
        say(f"  товаров в вашем списке: {len(logic.query_entries())}")

    sites = logic.list_sites()
    enabled = [site for site in sites if site.enabled]
    say(f"  площадок в конфиге: {len(sites)}, включено: {len(enabled)}"
        + (f" ({', '.join(site.id for site in enabled[:6])})" if enabled else ""))
    if not sites:
        problems.append("конфиг не найден — выполните python price_finder.py init-config")
    if not enabled:
        problems.append("нет включённых площадок — вкладка «Сайты» или config/sites.yaml")

    started = time.time()
    items, errors, message = logic.run_search("ноутбук", ["demo"], settings)
    say(f"  поиск на демо-площадке: {message} ({time.time() - started:.1f} с)")
    if items:
        for line in logic.format_row(1, items[0], "RUB", logic.median_price(items)).splitlines():
            say("    " + line)
        say("    сводка: " + logic.summary_line(items, "RUB"))
        say(f"    база истории: {paths.default_db_path()}")
        say(f"    отчёты: {paths.out_dir()}")
    else:
        say("  ⚠ демо-магазин не отвечает — поднимите его: python tests/demo_server.py")
        if errors:
            say(f"    ошибки: {errors[0].get('error', '')[:140]}")

    say(f"  история цен: {len(logic.history_rows(limit=3))} позиций в базе")

    say("  диагностика источника (demo):")
    for line in logic.diagnose_site("demo", "наушники", settings).splitlines()[:6]:
        say("    " + line)

    if not ok:
        say("")
        for line in kivy_install_hint(reason).splitlines():
            say("  " + line)

    say("")
    if problems:
        for problem in problems:
            say(f"  ✗ {problem}")
        return 1
    say("  Готово: логика работает."
        + (" Запуск окна — python price_finder.py gui" if ok else " Для окна поставьте kivy (см. выше)."))
    return 0


# Сборка APK (buildozer/python-for-android) выполняет main.py через exec с
# __name__ == "__main__0__", поэтому окно запускаем и в таком случае.
if __name__ == "__main__0__":
    main()

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(
            f"\nНе удалось создать окно интерфейса: {type(exc).__name__}: {exc}\n\n"
            "Что сделать:\n"
            "  • Termux: установите «Termux:X11», затем termux-x11 :1 -ac & export DISPLAY=:1\n"
            "  • kivy не установлен: bash android/install_gui_termux.sh (или pip install kivy)\n"
            "  • проверка логики без окна: python price_finder.py gui --selftest\n"
            '  • текстовый режим: python price_finder.py search "товар"\n'
        )
        raise SystemExit(1)
