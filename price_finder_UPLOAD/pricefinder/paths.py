"""Пути и определение платформы.

Одна и та же программа должна работать:
  * на десктопе (Windows/Linux/macOS) — данные рядом с проектом;
  * в Termux на Android — данные в ~/pricefinder (папка проекта может быть read-only);
  * внутри APK (Kivy/buildozer) — данные во внутреннем хранилище приложения.

Все пути можно переопределить переменными окружения:
  PRICEFINDER_HOME — папка для БД, конфигов и отчётов;
  PRICEFINDER_CONFIG — конкретный файл конфига.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


# --- определение платформы ---------------------------------------------------

def is_android() -> bool:
    """True, если код выполняется на Android (Termux, Pydroid или собранный APK)."""
    if hasattr(sys, "getandroidapilevel"):
        return True
    if os.environ.get("ANDROID_ARGUMENT") or os.environ.get("ANDROID_ROOT"):
        return True
    if os.environ.get("PANTS_NO_PORTAL") or "termux" in (os.environ.get("PREFIX") or "").lower():
        return True
    return sys.platform == "android"


def is_termux() -> bool:
    """True внутри Termux (есть пакетный менеджер pkg и $PREFIX)."""
    prefix = os.environ.get("PREFIX") or ""
    if prefix and "com.termux" in prefix:
        return True
    return is_android() and shutil.which("termux-info") is not None


def is_apk() -> bool:
    """True внутри собранного APK (Kivy/bootstrap задаёт ANDROID_PRIVATE)."""
    return bool(os.environ.get("ANDROID_PRIVATE")) or hasattr(sys, "getandroidapilevel")


def is_windows() -> bool:
    return os.name == "nt"


def platform_name() -> str:
    if is_apk():
        return "android-apk"
    if is_termux():
        return "android-termux"
    if is_android():
        return "android"
    if is_windows():
        return "windows"
    return sys.platform


# --- папки ------------------------------------------------------------------

def is_writable(path: Path) -> bool:
    """Проверяет, можно ли писать в папку (на Android папка программы часто read-only)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def app_dir() -> Path:
    """Папка для пользовательских данных (БД, конфиг, отчёты)."""
    override = os.environ.get("PRICEFINDER_HOME")
    if override:
        path = Path(override).expanduser()
        if is_writable(path):
            return path

    candidates: list[Path] = []
    if is_apk():
        try:
            from android.storage import app_storage_dir  # type: ignore

            candidates.append(Path(app_storage_dir()) / "pricefinder")
        except Exception:
            private = os.environ.get("ANDROID_PRIVATE")
            if private:
                candidates.append(Path(private) / "pricefinder")
    if is_android():
        candidates.append(Path.home() / "pricefinder")
        home = os.environ.get("HOME")
        if home:
            candidates.append(Path(home) / "pricefinder")
    candidates.append(PROJECT_DIR)                      # обычный десктоп
    candidates.append(Path.home() / ".pricefinder")     # запасной вариант

    for candidate in candidates:
        if is_writable(candidate):
            return candidate
    return Path.cwd()


def config_search_paths() -> list[Path]:
    """Где искать sites.yaml (порядок важен)."""
    override = os.environ.get("PRICEFINDER_CONFIG")
    paths: list[Path] = []
    if override:
        paths.append(Path(override).expanduser())
    paths += [
        Path("config/sites.yaml"),
        PROJECT_DIR / "config" / "sites.yaml",
        app_dir() / "config" / "sites.yaml",
        app_dir() / "sites.yaml",
        Path.home() / ".config" / "pricefinder" / "sites.yaml",
        Path.home() / ".pricefinder" / "sites.yaml",
    ]
    # уникальные, с сохранением порядка
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def default_db_path() -> Path:
    """Файл базы истории цен."""
    override = os.environ.get("PRICEFINDER_DB")
    if override:
        return Path(override).expanduser()
    return app_dir() / "price_finder.db"


def out_dir() -> Path:
    """Папка для отчётов (CSV/XLSX/HTML/JSON)."""
    path = app_dir() / "out"
    path.mkdir(parents=True, exist_ok=True)
    return path


def queries_file() -> Path:
    """Список товаров для search/watch --queries-file."""
    override = os.environ.get("PRICEFINDER_QUERIES")
    if override:
        return Path(override).expanduser()
    home = app_dir() / "queries.txt"
    if os.environ.get("PRICEFINDER_HOME"):
        return home                     # явный выбор папки данных — важнее файла в проекте
    project = PROJECT_DIR / "queries.txt"
    if project.exists():
        return project
    if home.exists():
        return home
    return project if is_writable(PROJECT_DIR) else home


def resolve_output_path(value: str | os.PathLike) -> Path:
    """Относительные имена отчётов кладём в out/, абсолютные не трогаем."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    if str(path.parent) in (".", ""):
        return out_dir() / path
    return path


def copy_config_to_app_dir(force: bool = False) -> Path | None:
    """На Android папка с программой бывает только для чтения — копируем конфиг в app_dir()."""
    source = PROJECT_DIR / "config" / "sites.yaml"
    if not source.exists():
        return None
    target = app_dir() / "config" / "sites.yaml"
    if target.exists() and not force:
        return target
    if target.resolve() == source.resolve():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        return target
    except OSError:
        return None


def environment_report() -> str:
    """Короткая сводка об окружении — для диагностики на телефоне."""
    import platform

    lines = [
        f"Платформа: {platform_name()} ({sys.platform})",
        f"Python: {sys.version.split()[0]} ({platform.machine()})",
        f"Папка данных: {app_dir()}",
        f"База цен: {default_db_path()}",
        f"Отчёты: {out_dir()}",
    ]
    for name, module in (("requests", "requests"), ("beautifulsoup4", "bs4"), ("lxml", "lxml"),
                         ("PyYAML", "yaml"), ("openpyxl", "openpyxl"), ("kivy", "kivy")):
        try:
            mod = __import__(module)
            version = getattr(mod, "__version__", "?")
            lines.append(f"  ✓ {name} {version}")
        except ImportError:
            lines.append(f"  ✗ {name} не установлен")
    return "\n".join(lines)


# --- первый запуск: распаковка конфигов в доступную для записи папку ---------

def _bundled_files() -> list[tuple[Path, Path]]:
    """Файлы из пакета, которые нужно скопировать в папку данных.

    Внутри APK (python-for-android) папка программы доступна только для чтения,
    поэтому конфиг и список товаров копируются в app_dir() при первом запуске.
    """
    pairs: list[tuple[Path, Path]] = []
    candidates = [
        (PROJECT_DIR / "config" / "sites.yaml", app_dir() / "config" / "sites.yaml"),
        (PROJECT_DIR / "queries.txt", app_dir() / "queries.txt"),
    ]
    for source, target in candidates:
        if source.exists() and target.resolve() != source.resolve():
            pairs.append((source, target))
    return pairs


def ensure_user_files(verbose: bool = False) -> list[Path]:
    """Создаёт в папке данных конфиг и список товаров, если их там ещё нет."""
    created: list[Path] = []
    for source, target in _bundled_files():
        try:
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            created.append(target)
            if verbose:
                print(f"  создан файл: {target}")
        except OSError:
            continue
    try:
        out_dir()
    except OSError:
        pass
    return created
