"""Виджеты сенсорного интерфейса pricefinder (Kivy).

Модуль намеренно отделён от gui_app.py: он импортирует Kivy, а Kivy в среде без
дисплея/OpenGL аварийно завершает процесс. Поэтому:

  * `gui_app.py --selftest` и текстовые команды НЕ импортируют этот модуль;
  * окно создаётся только после проверки pricefinder.display.display_hint().

Классы: SearchScreen, ListScreen, WatchScreen, HistoryScreen, SitesScreen,
SettingsScreen, PriceFinderApp.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import sp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from . import gui_logic as logic
from . import paths
from .parsers import Item

ACCENT = (0.12, 0.44, 0.75, 1)
GOOD = (0.06, 0.55, 0.25, 1)
MUTED = (0.45, 0.47, 0.5, 1)


#  Мелкие строительные блоки
# =========================================================================

def make_button(text: str, on_press, height: int = 52, bold: bool = False,
                color=ACCENT, font_size: int = 15) -> Button:
    button = Button(
        text=text,
        size_hint_y=None,
        height=height,
        bold=bold,
        font_size=sp(font_size),
        background_color=color,
        background_normal="",
        markup=False,
    )
    button.bind(on_press=on_press)
    return button


def make_label(text: str = "", size: int = 14, color=(1, 1, 1, 1), bold: bool = False,
               halign: str = "left", valign: str = "middle") -> Label:
    label = Label(
        text=text,
        font_size=sp(size),
        color=color,
        bold=bold,
        halign=halign,
        valign=valign,
        text_size=(0, None),
        markup=False,
        shorten=False,
    )
    label.bind(width=lambda inst, value: setattr(inst, "text_size", (value, None)))
    return label


def make_field(hint: str, text: str = "", multiline: bool = False, password: bool = False,
               input_filter: str | None = None) -> TextInput:
    return TextInput(
        text=text,
        hint_text=hint,
        multiline=multiline,
        password=password,
        input_filter=input_filter,
        font_size=sp(15),
        size_hint_y=None,
        height=110 if multiline else 46,
        padding=[10, 8],
    )


def make_scroll(content: Widget) -> ScrollView:
    view = ScrollView(do_scroll_x=False, bar_width=3)
    content.size_hint_y = None
    content.bind(minimum_height=lambda inst, value: setattr(inst, "height", max(value, 100)))
    view.add_widget(content)
    return view


def show_popup(title: str, text: str, buttons: dict[str, callable] | None = None) -> Popup:
    box = BoxLayout(orientation="vertical", spacing=10, padding=12)
    view = make_scroll(make_label(text, size=14))
    box.add_widget(view)
    popup = Popup(title=title, content=box, size_hint=(0.92, 0.8), auto_dismiss=True)
    row = BoxLayout(size_hint_y=None, height=52, spacing=8)
    row.add_widget(make_button("Закрыть", lambda *_: popup.dismiss(), color=MUTED))
    for label, action in (buttons or {}).items():
        row.add_widget(make_button(label, action, color=ACCENT))
    box.add_widget(row)
    popup.open()
    return popup


# =========================================================================
#  Вкладка «Поиск»
# =========================================================================


class SearchScreen(BoxLayout):
    busy = BooleanProperty(False)
    status = StringProperty("Введите товар и нажмите «Найти цены»")

    def __init__(self, app: "PriceFinderApp", **kw):
        super().__init__(orientation="vertical", spacing=8, padding=10, **kw)
        self.app_ref = app
        self.items: list[Item] = []
        self.task = None

        field_row = BoxLayout(size_hint_y=None, height=54, spacing=8)
        self.query = make_field("Например: iphone 15 128gb")
        self.query.bind(on_text_validate=lambda *_: self.do_search())
        self.find_button = make_button("Найти цены", lambda *_: self.do_search(), height=54, bold=True)
        field_row.add_widget(self.query)
        field_row.add_widget(self.find_button)
        self.add_widget(field_row)

        quick = BoxLayout(size_hint_y=None, height=40, spacing=6)
        for text, action in (
            ("⚙ фильтры", self.show_filters),
            ("📊 сводка", self.show_summary),
            ("💾 сохранить", self.save_results),
            ("⚠ ошибки", self.show_errors),
        ):
            quick.add_widget(make_button(text, action, height=40, color=MUTED, font_size=13))
        self.add_widget(quick)

        self.status_label = make_label("", size=13, color=(0.75, 0.85, 1, 1))
        self.bind(status=lambda inst, value: setattr(self.status_label, "text", value))
        self.add_widget(self.status_label)

        self.results_box = GridLayout(cols=1, spacing=6, padding=(0, 4))
        self.add_widget(make_scroll(self.results_box))

    # --- действия ---------------------------------------------------------
    def do_search(self) -> None:
        query = self.query.text.strip()
        if not query:
            self.status = "Введите название товара"
            return
        if self.busy:
            return
        self.busy = True
        self.find_button.text = "Ищу…"
        self.find_button.disabled = True
        self.status = f"Ищу «{query}»…"
        self.results_box.clear_widgets()
        settings = self.app_ref.settings
        site_ids = self.app_ref.selected_site_ids()
        self.last_errors: list[dict] = []

        def done(items, errors, message):
            Clock.schedule_once(lambda *_: self._on_done(items, errors, message), 0)

        self.task = logic.SearchTask(query=query, site_ids=site_ids, settings=settings, on_done=done)
        self.task.start()

    def _on_done(self, items: list[Item], errors: list[dict], message: str) -> None:
        self.busy = False
        self.find_button.text = "Найти цены"
        self.find_button.disabled = False
        self.items = items
        self.last_errors = errors
        base = self.app_ref.base_currency()
        median = logic.median_price(items)
        self.results_box.clear_widgets()
        for index, item in enumerate(items[: int(self.app_ref.settings.get("top", 20))], 1):
            self.results_box.add_widget(self._result_row(index, item, base, median))
        if not items:
            self.results_box.add_widget(make_label(
                "Ничего не найдено.\n\nПроверьте:\n"
                "• включены ли площадки (вкладка «Сайты»);\n"
                "• не слишком ли узкий запрос;\n"
                "• возможно, сайт требует браузерный рендер (вкладка «Настройки» → JS-рендер).\n\n"
                "Подробности — кнопка «⚠ ошибки».", size=14, color=(1, 0.8, 0.6, 1)))
        self.status = message

    def _result_row(self, index: int, item: Item, base: str, median: float | None) -> Widget:
        price = item.normalized_price if item.normalized_price is not None else item.price
        from pricefinder.reports import fmt

        sym = logic.currency_symbol(base)
        left = BoxLayout(orientation="vertical", spacing=2, size_hint_x=None, width=130)
        left.add_widget(make_label(fmt(price, sym), size=17, color=(0.4, 1, 0.6, 1), bold=True))
        if median and price:
            diff = (median - price) / median * 100
            if abs(diff) >= 0.5:
                left.add_widget(make_label(f"{'−' if diff > 0 else '+'}{abs(diff):.0f}% к медиане",
                                           size=11, color=MUTED))
        right = BoxLayout(orientation="vertical", spacing=2)
        right.add_widget(make_label(item.title, size=14))
        site_text = item.site_name + (f" +{len(item.also_at)}" if item.also_at else "")
        if item.seller:
            site_text += f" · {item.seller}"
        right.add_widget(make_label(site_text, size=12, color=(0.7, 0.8, 0.95, 1)))
        if item.rating:
            right.add_widget(make_label(
                f"рейтинг {item.rating:.1f}" + (f" ({item.reviews})" if item.reviews else ""),
                size=11, color=MUTED))

        row = BoxLayout(size_hint_y=None, height=92, spacing=8, padding=(6, 4))
        row.add_widget(left)
        row.add_widget(right)
        open_button = make_button("Открыть", lambda *_, url=item.url, title=item.title: self.open_item(url, title),
                                  height=44, color=ACCENT, font_size=13)
        open_button.size_hint_x = None
        open_button.width = 100
        row.add_widget(open_button)
        return row

    def open_item(self, url: str, title: str) -> None:
        if not url:
            show_popup("Ссылки нет", f"{title}\n\nДля этой карточки сайт не отдал ссылку.")
            return
        if logic.open_url(url):
            self.status = f"Открываю в браузере: {title[:40]}"
        else:
            show_popup("Не удалось открыть браузер", url, {"Скопировать": lambda *_: self.copy(url)})

    def copy(self, text: str) -> None:
        # Clipboard импортируем здесь: на версиях Kivy без оконного бэкенда
        # его импорт на верхнем уровне роняет процесс.
        try:
            from kivy.core.clipboard import Clipboard

            Clipboard.copy(text)
            self.status = "Скопировано в буфер обмена"
        except Exception:
            self.status = text

    def show_summary(self, *_args) -> None:
        if not self.items:
            show_popup("Сводка", "Сначала выполните поиск.")
            return
        base = self.app_ref.base_currency()
        lines = [logic.summary_line(self.items, base), ""]
        by_site: dict[str, list[float]] = {}
        for item in self.items:
            by_site.setdefault(item.site_name, []).append(item.normalized_price or item.price or 0)
        for name, prices in sorted(by_site.items(), key=lambda kv: min(kv[1])):
            from pricefinder.reports import fmt

            sym = logic.currency_symbol(base)
            lines.append(f"{name}: {len(prices)} шт., от {fmt(min(prices), sym)} до {fmt(max(prices), sym)}")
        show_popup("Сводка по результатам", "\n".join(lines))

    def show_errors(self, *_args) -> None:
        errors = getattr(self, "last_errors", [])
        if not errors:
            show_popup("Ошибки источников", "Ошибок нет — все выбранные площадки ответили.")
            return
        text = "\n".join(f"• {e.get('site', '?')}: {e.get('error', '')}\n  {e.get('url', '')}" for e in errors)
        show_popup("Что не сработало", text + "\n\nПодсказки:\n"
                                       "• HTTP 403/429 — сайт видит робота: включите JS-рендер и увеличьте задержку;\n"
                                       "• «карточки не распознаны» — обновите селекторы в config/sites.yaml.")

    def show_filters(self, *_args) -> None:
        self.app_ref.sm.current = "settings"

    def save_results(self, *_args) -> None:
        if not self.items:
            show_popup("Сохранение", "Нет результатов для сохранения.")
            return
        saved = self.app_ref.save_results(self.items, self.query.text.strip())
        show_popup("Сохранено", "\n".join(str(p) for p in saved) or "Ничего не сохранено")


# =========================================================================
#  Вкладка «Список товаров» (queries.txt)
# =========================================================================

class ListScreen(BoxLayout):
    status = StringProperty("")

    def __init__(self, app: "PriceFinderApp", **kw):
        super().__init__(orientation="vertical", spacing=8, padding=10, **kw)
        self.app_ref = app
        self.add_widget(make_label(
            "Файл queries.txt — товар ; желаемая цена ; падение % ; сайты\n"
            "(строки с # считаются комментарием)", size=12, color=MUTED))
        self.editor = make_field("", text=logic.read_queries_text(), multiline=True)
        self.add_widget(self.editor)

        row = BoxLayout(size_hint_y=None, height=48, spacing=6)
        row.add_widget(make_button("Сохранить", self.save, height=48))
        row.add_widget(make_button("Найти по всем", self.search_all, height=48, bold=True))
        row.add_widget(make_button("Следить", self.watch_all, height=48, color=GOOD))
        self.add_widget(row)
        self.status_label = make_label("", size=13)
        self.add_widget(self.status_label)

    def save(self, *_args) -> None:
        path = logic.write_queries_text(self.editor.text)
        entries = logic.query_entries(self.editor.text)
        self.status_label.text = f"Сохранено {path} · товаров: {len(entries)}"

    def search_all(self, *_args) -> None:
        entries = logic.query_entries(self.editor.text)
        if not entries:
            self.status_label.text = "Список пуст"
            return
        self.save()
        self.app_ref.search_entries(entries, source_label="Список товаров")

    def watch_all(self, *_args) -> None:
        entries = logic.query_entries(self.editor.text)
        if not entries:
            self.status_label.text = "Список пуст"
            return
        self.save()
        self.app_ref.start_watch(entries)
        self.app_ref.sm.current = "watch"


# =========================================================================
#  Вкладка «Мониторинг»
# =========================================================================

class WatchScreen(BoxLayout):
    def __init__(self, app: "PriceFinderApp", **kw):
        super().__init__(orientation="vertical", spacing=8, padding=10, **kw)
        self.app_ref = app
        self.log_box = GridLayout(cols=1, spacing=4, padding=(0, 4))
        self.add_widget(make_label("Мониторинг цен из списка товаров (вкладка «Список» → «Следить»)",
                                   size=13, color=MUTED))
        self.status_label = make_label("Остановлен", size=14, color=(0.75, 0.85, 1, 1))
        self.add_widget(self.status_label)
        row = BoxLayout(size_hint_y=None, height=48, spacing=6)
        self.start_button = make_button("Запустить", lambda *_: self.app_ref.start_watch_from_list(),
                                        height=48, color=GOOD)
        self.stop_button = make_button("Остановить", lambda *_: self.app_ref.stop_watch(), height=48,
                                       color=MUTED)
        row.add_widget(self.start_button)
        row.add_widget(self.stop_button)
        self.add_widget(row)
        self.add_widget(make_scroll(self.log_box))

    def push(self, text: str, color=(1, 1, 1, 1)) -> None:
        self.log_box.add_widget(make_label(text, size=13, color=color))
        # держим последние 200 строк
        while len(self.log_box.children) > 200:
            self.log_box.remove_widget(self.log_box.children[-1])

    def set_status(self, text: str) -> None:
        self.status_label.text = text


# =========================================================================
#  Вкладка «История»
# =========================================================================

class HistoryScreen(BoxLayout):
    def __init__(self, app: "PriceFinderApp", **kw):
        super().__init__(orientation="vertical", spacing=8, padding=10, **kw)
        self.app_ref = app
        row = BoxLayout(size_hint_y=None, height=48, spacing=6)
        self.filter_field = make_field("фильтр по названию")
        row.add_widget(self.filter_field)
        row.add_widget(make_button("Показать", lambda *_: self.refresh(), height=48))
        self.add_widget(row)
        self.info = make_label("", size=13, color=MUTED)
        self.add_widget(self.info)
        self.box = GridLayout(cols=1, spacing=6, padding=(0, 4))
        self.add_widget(make_scroll(self.box))

    def on_enter(self, *_args) -> None:
        self.refresh()

    def refresh(self) -> None:
        from pricefinder.reports import fmt

        rows = logic.history_rows(limit=40, needle=self.filter_field.text)
        self.box.clear_widgets()
        base = self.app_ref.base_currency()
        sym = logic.currency_symbol(base)
        for row in rows:
            text = (f"{row['title']}\n"
                    f"{row['site']} · сейчас {fmt(row['last'], sym)} · мин {fmt(row['low'], sym)} · "
                    f"макс {fmt(row['high'], sym)} · точек {row['points']}\n"
                    f"{row['spark']}")
            label = make_label(text, size=13)
            self.box.add_widget(label)
            if row["url"]:
                button = make_button("Открыть предложение", lambda *_, u=row["url"]: logic.open_url(u),
                                     height=40, color=MUTED, font_size=12)
                self.box.add_widget(button)
        self.info.text = (f"Позиций: {len(rows)} · база: {paths.default_db_path()}"
                          if rows else "История пуста — выполните поиск (он пишется в базу автоматически)")


# =========================================================================
#  Вкладка «Сайты»
# =========================================================================

class SitesScreen(BoxLayout):
    def __init__(self, app: "PriceFinderApp", **kw):
        super().__init__(orientation="vertical", spacing=8, padding=10, **kw)
        self.app_ref = app
        self.add_widget(make_label("Отметьте площадки для поиска и нажмите «Сохранить»",
                                   size=13, color=MUTED))
        self.box = GridLayout(cols=1, spacing=4, padding=(0, 4))
        self.checks: dict[str, CheckBox] = {}
        self.add_widget(make_scroll(self.box))

        row = BoxLayout(size_hint_y=None, height=48, spacing=6)
        row.add_widget(make_button("Сохранить", self.save, height=48, bold=True))
        row.add_widget(make_button("Диагностика сайта", self.diagnose, height=48, color=MUTED))
        self.add_widget(row)

    def on_enter(self, *_args) -> None:
        self.rebuild()

    def rebuild(self) -> None:
        self.box.clear_widgets()
        self.checks.clear()
        for site in logic.list_sites():
            line = BoxLayout(size_hint_y=None, height=56, spacing=8)
            check = CheckBox(active=bool(site.enabled), size_hint_x=None, width=44)
            self.checks[site.id] = check
            text = f"{site.name}  ({site.id})\n{logic.truncate(site.notes or site.search_url, 70)}"
            line.add_widget(check)
            line.add_widget(make_label(text, size=12))
            self.box.add_widget(line)

    def save(self, *_args) -> None:
        enabled = [site_id for site_id, check in self.checks.items() if check.active]
        try:
            path = logic.set_sites_enabled(enabled)
            self.app_ref.reload_config()
            show_popup("Сохранено", f"Включено площадок: {len(enabled)}\nФайл: {path}")
        except Exception as exc:  # noqa: BLE001
            show_popup("Ошибка", f"Не удалось сохранить: {exc}")

    def diagnose(self, *_args) -> None:
        enabled = [site_id for site_id, check in self.checks.items() if check.active]
        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        site_field = make_field("id сайта", text=enabled[0] if enabled else "demo")
        query_field = make_field("запрос", text="товар")
        output = make_field("", text="", multiline=True)
        content.add_widget(make_label("Проверка одного источника (HTTP-код, стратегия, карточки)", size=13))
        content.add_widget(site_field)
        content.add_widget(query_field)
        content.add_widget(output)
        popup = Popup(title="Диагностика сайта", content=content, size_hint=(0.94, 0.85))

        def run(*_args):
            output.text = "Выполняю…"

            def worker():
                text = logic.diagnose_site(site_field.text.strip(), query_field.text.strip(),
                                           self.app_ref.settings)
                Clock.schedule_once(lambda *_: setattr(output, "text", text), 0)

            import threading

            threading.Thread(target=worker, daemon=True).start()

        row = BoxLayout(size_hint_y=None, height=48, spacing=8)
        row.add_widget(make_button("Запустить", run, height=48))
        row.add_widget(make_button("Закрыть", lambda *_: popup.dismiss(), height=48, color=MUTED))
        content.add_widget(row)
        popup.open()


# =========================================================================
#  Вкладка «Настройки»
# =========================================================================

class SettingsScreen(BoxLayout):
    def __init__(self, app: "PriceFinderApp", **kw):
        super().__init__(orientation="vertical", spacing=8, padding=10, **kw)
        self.app_ref = app
        settings = app.settings
        self.fields: dict[str, TextInput] = {}
        self.switches: dict[str, CheckBox] = {}

        form = GridLayout(cols=1, spacing=6, padding=(0, 4))

        def add_field(key: str, title: str, value, hint: str = "") -> None:
            form.add_widget(make_label(title, size=12, color=MUTED))
            field = make_field(hint or title, text="" if value is None else str(value))
            self.fields[key] = field
            form.add_widget(field)

        def add_switch(key: str, title: str, value: bool) -> None:
            line = BoxLayout(size_hint_y=None, height=44, spacing=8)
            check = CheckBox(active=bool(value), size_hint_x=None, width=44)
            self.switches[key] = check
            line.add_widget(check)
            line.add_widget(make_label(title, size=13))
            form.add_widget(line)

        add_field("top", "Показывать предложений", settings.get("top", 20))
        add_field("pages", "Страниц выдачи на сайт", settings.get("pages", 1))
        add_field("min_price", "Цена не ниже (пусто = без ограничения)", settings.get("min_price") or "", "0")
        add_field("max_price", "Цена не выше", settings.get("max_price") or "", "например 50000")
        add_field("max_ratio", "Не дороже «минимум × N» (0 = выкл.)", settings.get("max_ratio", 0), "1.5")
        add_field("exclude", "Исключить слова (через запятую)", settings.get("exclude", ""), "б/у, витрина")
        add_switch("in_stock_only", "Только товары в наличии", settings.get("in_stock_only", False))
        add_switch("require_keyword", "Требовать слова запроса в названии", settings.get("require_keyword", False))
        add_switch("update_rates", "Живые курсы валют (нужен интернет)", settings.get("update_rates", False))
        add_switch("js_render", "JS-рендер сайтов (нужен Playwright)", settings.get("js_render", False))
        add_switch("save_history", "Писать историю цен в базу", settings.get("save_history", True))
        add_field("delay", "Пауза между запросами, сек", settings.get("delay", 1.0), "1.5")
        add_field("timeout", "Таймаут запроса, сек", settings.get("timeout", 20))
        add_field("retries", "Повторов при ошибках", settings.get("retries", 2))
        add_field("interval_minutes", "Период мониторинга, минут", settings.get("interval_minutes", 30))
        add_field("drop_pct", "Сигнал при падении цены на %", settings.get("drop_pct", 3), "5")
        add_switch("wakelock", "Не давать телефону уснуть (Termux)", settings.get("wakelock", False))

        self.add_widget(make_scroll(form))

        row = BoxLayout(size_hint_y=None, height=48, spacing=6)
        row.add_widget(make_button("Сохранить", self.save, height=48, bold=True))
        row.add_widget(make_button("О системе", self.show_env, height=48, color=MUTED))
        row.add_widget(make_button("Тест уведомлений", self.notify_test, height=48, color=MUTED))
        self.add_widget(row)

    def save(self, *_args) -> None:
        settings = dict(self.app_ref.settings)
        for key, field in self.fields.items():
            raw = field.text.strip()
            if key in ("top", "pages", "retries", "timeout"):
                settings[key] = logic._int(raw or 0, logic.DEFAULT_GUI_SETTINGS[key])
            elif key in ("min_price", "max_price", "max_ratio", "delay", "interval_minutes", "drop_pct"):
                settings[key] = logic._float_or_none(raw) if key in ("min_price", "max_price") \
                    else logic._float(raw or 0, logic.DEFAULT_GUI_SETTINGS[key])
            else:
                settings[key] = raw
        for key, check in self.switches.items():
            settings[key] = bool(check.active)
        if settings.get("max_ratio") in (None, 0):
            settings["max_ratio"] = 0.0
        path = logic.save_gui_settings(settings)
        self.app_ref.settings = settings
        if settings.get("wakelock"):
            logic.set_wakelock(True)
        show_popup("Сохранено", f"Настройки записаны:\n{path}")

    def show_env(self, *_args) -> None:
        show_popup("Окружение", paths.environment_report() +
                   f"\nКонфиг: {next((p for p in paths.config_search_paths() if p.exists()), 'не найден')}"
                   f"\nБаза: {paths.default_db_path()}"
                   f"\nОтчёты: {paths.out_dir()}")

    def notify_test(self, *_args) -> None:
        from pricefinder.notify import Notifier
        from pricefinder.sites import load_config

        notifier = Notifier.from_settings(load_config().settings or {})
        status = notifier.test()
        channels = [
            f"Android-уведомление: {'доступно' if notifier.termux_available() else 'нет (нужен Termux:API)'}",
            f"Telegram: {'настроен' if notifier.telegram_token and notifier.telegram_chat else 'не настроен'}",
            f"E-mail: {'настроен' if notifier.smtp_host and notifier.smtp_to else 'не настроен'}",
        ]
        show_popup("Проверка уведомлений", "\n".join(channels) + f"\n\nРезультат: {status or 'нечего отправлять'}")


# =========================================================================
#  Приложение
# =========================================================================

class PriceFinderApp(App):
    title = "Цены — поиск самых низких"

    def build(self):
        self.settings = logic.load_gui_settings()
        self.config_obj = None
        self.watch_task = None
        self.reload_config()
        if self.settings.get("wakelock"):
            logic.set_wakelock(True)

        self.sm = ScreenManager()
        self.search_screen = SearchScreen(self)
        self.list_screen = ListScreen(self)
        self.watch_screen = WatchScreen(self)
        self.history_screen = HistoryScreen(self)
        self.sites_screen = SitesScreen(self)
        self.settings_screen = SettingsScreen(self)

        for name, widget in (
            ("search", self.search_screen),
            ("list", self.list_screen),
            ("watch", self.watch_screen),
            ("history", self.history_screen),
            ("sites", self.sites_screen),
            ("settings", self.settings_screen),
        ):
            screen = Screen(name=name)
            screen.add_widget(widget)
            self.sm.add_widget(screen)

        self.sm.get_screen("history").bind(on_pre_enter=lambda *_: self.history_screen.on_enter())
        self.sm.get_screen("sites").bind(on_pre_enter=lambda *_: self.sites_screen.on_enter())

        tabs = TabbedPanel(do_default_tab=False, tab_height=52, background_color=(0.08, 0.09, 0.11, 1))
        for title, screen_name in (
            ("Поиск", "search"),
            ("Список", "list"),
            ("Слежка", "watch"),
            ("История", "history"),
            ("Сайты", "sites"),
            ("Настройки", "settings"),
        ):
            item = TabbedPanelItem(text=title)
            button = make_button(title, lambda *_, s=screen_name: self.sm_switch(s),
                                 height=48, color=(0, 0, 0, 0), font_size=13)
            item.content = Widget()
            item.add_widget(button)
            tabs.add_widget(item)

        root = BoxLayout(orientation="vertical")
        root.add_widget(tabs)
        root.add_widget(self.sm)
        if tabs.tab_list:
            tabs.switch_to(tabs.tab_list[-1])
        self.tabs = tabs
        return root

    def sm_switch(self, screen_name: str) -> None:
        self.sm.current = screen_name

    # --- конфиг -----------------------------------------------------------
    def reload_config(self) -> None:
        from pricefinder.sites import load_config

        self.config_obj = load_config()

    def base_currency(self) -> str:
        settings = (self.config_obj.settings if self.config_obj else {}) or {}
        return str((settings.get("currencies") or {}).get("base", "RUB")).upper()

    def selected_site_ids(self) -> list[str]:
        return [site.id for site in (self.config_obj.enabled() if self.config_obj else [])]

    # --- поиск по списку -------------------------------------------------
    def search_entries(self, entries: list[dict], source_label: str = "") -> None:
        """Последовательно ищет все товары из списка (в фоне)."""
        total = len(entries)
        self.watch_screen.set_status(f"{source_label}: ищу {total} товаров…")
        self.sm.current = "watch"
        self.watch_screen.log_box.clear_widgets()

        def worker():
            import time

            for index, entry in enumerate(entries, 1):
                query = entry["query"]
                items, errors, message = logic.run_search(
                    query, entry.get("sites").split(",") if entry.get("sites") else None, self.settings)
                base = self.base_currency()
                from pricefinder.reports import fmt

                lines = [f"[{index}/{total}] «{query}» — {message}"]
                for position, item in enumerate(items[: int(self.settings.get("top", 5))], 1):
                    price = item.normalized_price if item.normalized_price is not None else item.price
                    lines.append(f"   {position}. {fmt(price, logic.currency_symbol(base))} · "
                                 f"{logic.truncate(item.title, 60)} · {item.site_name}")
                target = entry.get("target_price")
                if target and items and (items[0].normalized_price or items[0].price) <= float(target):
                    lines.append(f"   🔔 ниже цели {target:g}!")
                Clock.schedule_once(lambda text="\n".join(lines): self.watch_screen.push(text), 0)
                time.sleep(float(self.settings.get("delay", 1.0)))
            Clock.schedule_once(lambda *_: self.watch_screen.set_status(f"{source_label}: готово"), 0)

        import threading

        threading.Thread(target=worker, daemon=True).start()

    # --- мониторинг --------------------------------------------------------
    def start_watch_from_list(self) -> None:
        entries = logic.query_entries()
        if not entries:
            show_popup("Мониторинг", "Список товаров пуст.\nОткройте вкладку «Список» и впишите товары.")
            return
        self.start_watch(entries)

    def start_watch(self, entries: list[dict]) -> None:
        if self.watch_task and self.watch_task.thread and self.watch_task.thread.is_alive():
            show_popup("Мониторинг", "Уже запущен — сначала остановите.")
            return
        interval = logic.parse_interval(f"{int(self.settings.get('interval_minutes', 30))}m")
        self.watch_screen.log_box.clear_widgets()
        self.watch_screen.set_status(
            f"Слежу за {len(entries)} товарами каждые {int(interval // 60)} мин. "
            f"Держите приложение открытым.")
        self.watch_task = logic.WatchTask(
            entries=entries,
            settings=self.settings,
            on_status=lambda text: Clock.schedule_once(lambda *_: self.watch_screen.push(text, MUTED), 0),
            on_alert=lambda kind, text: Clock.schedule_once(
                lambda *_: self.watch_screen.push(f"🔔 {kind}: {text}", (0.4, 1, 0.6, 1)), 0),
            interval_seconds=interval,
        )
        if paths.is_android():
            logic.set_wakelock(True)
        self.watch_task.start()

    def stop_watch(self) -> None:
        if self.watch_task:
            self.watch_task.stop()
            self.watch_task = None
        if paths.is_android():
            logic.set_wakelock(False)
        self.watch_screen.set_status("Остановлен")

    def on_stop(self) -> None:
        self.stop_watch()
        logic.set_wakelock(False)

    # --- поведение на Android ---------------------------------------------
    def on_start(self) -> None:
        """Перехват системной кнопки «Назад» (Android) и паузы приложения."""
        from kivy import platform

        if platform != "android":
            return
        try:
            from android import mActivity  # type: ignore
            from jnius import autoclass, cast  # type: ignore

            mActivity.setOnKeyListener(self._android_back_listener())
            self._mActivity = mActivity
            self._autoclass = autoclass
            self._cast = cast
        except Exception:
            pass

    def _android_back_listener(self):
        from jnius import JavaCallback, autoclass  # type: ignore

        KeyEvent = autoclass("android.view.KeyEvent")

        class BackListener(JavaCallback):
            def onKey(self, listener, keyCode, event):  # noqa: N802
                if keyCode == KeyEvent.KEYCODE_BACK:
                    Clock.schedule_once(lambda *_: self.on_back_pressed(), 0)
                    return True
                return False

        return BackListener()

    def on_back_pressed(self) -> None:
        """Кнопка «Назад»: с вкладки «Поиск» — выход по двойному нажатию, иначе — на «Поиск»."""
        if self.sm.current != "search":
            self.sm.current = "search"
            return
        now = datetime.now()
        last = getattr(self, "_last_back", None)
        self._last_back = now
        if last and (now - last).total_seconds() < 2.0:
            self.stop()
            return
        self.toast("Нажмите «Назад» ещё раз, чтобы выйти")

    def on_pause(self) -> bool:
        """Приложение сворачивают (звонок/домой) — разрешаем Android уйти в паузу."""
        return True

    def on_resume(self) -> None:
        pass

    @staticmethod
    def toast(text: str) -> None:
        """Короткое всплывающее сообщение Android (на ПК — в консоль)."""
        try:
            from jnius import autoclass  # type: ignore

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Toast = autoclass("android.widget.Toast")
            context = PythonActivity.mActivity
            Toast.makeText(context, text, Toast.LENGTH_SHORT).show()
        except Exception:
            print(text)

    # --- сохранение результатов -------------------------------------------
    def save_results(self, items: list[Item], query: str) -> list[Path]:
        from pricefinder import reports

        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        safe = "".join(ch if ch.isalnum() else "_" for ch in (query or "results"))[:40]
        saved: list[Path] = []
        base = self.base_currency()
        for suffix, saver in ((".csv", reports.save_csv), (".json", lambda i, p: reports.save_json(i, p, query)),
                              (".html", lambda i, p: reports.save_html(i, p, query, (), base))):
            try:
                saved.append(saver(items, paths.out_dir() / f"{safe}_{stamp}{suffix}"))
            except Exception:  # noqa: BLE001
                continue
        try:
            saved.append(reports.save_xlsx(items, paths.out_dir() / f"{safe}_{stamp}.xlsx", query))
        except Exception:  # noqa: BLE001
            pass
        return saved
