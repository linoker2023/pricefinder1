"""Проверка доступности графики до импорта Kivy.

Kivy при создании окна падает «намертво» (без трассировки), если нет
дисплея или OpenGL, поэтому проверяем окружение заранее и выдаём понятную
инструкцию — особенно это актуально для Termux на Android.
"""

from __future__ import annotations

import os
import platform

from . import paths


def display_hint() -> str | None:
    """Возвращает текст подсказки, если окно в этом окружении создать нельзя."""
    system = platform.system()
    if system in ("Windows", "Darwin"):
        return None
    if paths.is_apk():                      # внутри APK окно создаёт сам Android
        return None
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return None
    if system == "Linux":
        if paths.is_termux():
            return (
                "Termux без графики. Чтобы окно открылось:\n"
                "  1) установите приложение «Termux:X11» из F-Droid;\n"
                "  2) в Termux выполните:\n"
                "       termux-x11 :1 -ac &\n"
                "       export DISPLAY=:1\n"
                "       python price_finder.py gui\n\n"
                "Текстовый режим работает всегда:\n"
                "  python price_finder.py search \"товар\"\n"
                "  python price_finder.py search --queries-file\n"
                "Проверка логики интерфейса без окна: python price_finder.py gui --selftest"
            )
        return (
            "Нет дисплея (переменная DISPLAY не задана).\n"
            "  • на сервере: подключитесь с пробросом X11 — ssh -X user@host;\n"
            "  • проверка логики без окна: python price_finder.py gui --selftest;\n"
            "  • текстовый режим: python price_finder.py search \"товар\""
        )
    return None
