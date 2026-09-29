"""Мини-парсер YAML для конфига pricefinder.

Зачем: на Android (Termux/Pydroid) и в других «бедных» окружениях PyYAML может
быть недоступен или не собираться. Этот модуль понимает ровно тот подмножество
YAML, которое используется в config/sites.yaml:

* отображения и списки с отступами;
* строки (в кавычках и без), числа, true/false/null;
* потоковые списки [a, b] и отображения {a: 1, b: 2};
* комментарии `#` и пустые строки;
* многострочные блоки `|` и `>`.

Если PyYAML установлен — используется он (sites.py пробует его первым).
"""

from __future__ import annotations

import re
from typing import Any

_INLINE_LIST = re.compile(r"^\[(.*)\]$", re.DOTALL)
_INLINE_MAP = re.compile(r"^\{(.*)\}$", re.DOTALL)
_QUOTED = re.compile(r"""^(?P<q>['"])(?P<body>.*)(?P=q)$""", re.DOTALL)


class YamliteError(ValueError):
    pass


def safe_load(text: str) -> Any:
    """Разбирает YAML-текст в словари/списки/скаляры Python."""
    lines = _prepare_lines(text)
    if not lines:
        return None
    value, index = _parse_block(lines, 0, lines[0][0])
    return value


# ---------------------------------------------------------------------------


def _prepare_lines(text: str) -> list[tuple[int, str]]:
    """Убирает комментарии и пустые строки, возвращает (отступ, содержимое)."""
    out: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if raw.lstrip().startswith("#") or not raw.strip():
            # внутри блочного скаляра пустые строки значимы, но для конфига — нет
            continue
        stripped = raw.lstrip("\t")      # табуляции в YAML запрещены — считаем пробелами
        indent = len(raw) - len(raw.lstrip(" "))
        body = stripped.rstrip()
        body = _strip_comment(body)
        if not body.strip():
            continue
        out.append((indent, body.strip()))
    return out


def _strip_comment(body: str) -> str:
    """Убирает хвостовой комментарий, не трогая # внутри кавычек."""
    quote: str | None = None
    for i, ch in enumerate(body):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or body[i - 1] in " \t"):
            return body[:i].rstrip()
    return body


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return None, index
    if lines[index][1].startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(lines):
        cur_indent, body = lines[index]
        if cur_indent < indent or not body.startswith("-"):
            break
        if cur_indent > indent:
            raise YamliteError(f"неожиданный отступ в списке: {body!r}")
        content = body[1:].strip()
        index += 1
        if not content:
            # значение — вложенный блок на следующих строках
            if index < len(lines) and lines[index][0] > indent:
                value, index = _parse_block(lines, index, lines[index][0])
                items.append(value)
            else:
                items.append(None)
            continue

        if _looks_like_key(content):
            # элемент-словарь: «- id: demo» плюс следующие ключи того же элемента
            item_indent = indent + 2          # ключи элемента стоят на 2 пробела правее «-»
            result: dict[str, Any] = {}
            key, value = _split_key(content)
            index = _fill_value(result, key, value, lines, index, item_indent)
            while index < len(lines):
                cur_indent, cur_body = lines[index]
                if cur_indent != item_indent or cur_body.startswith("- ") or not _looks_like_key(cur_body):
                    break
                key, value = _split_key(cur_body)
                index += 1
                index = _fill_value(result, key, value, lines, index, item_indent)
            items.append(result)
        else:
            items.append(_scalar(content))
    return items, index


def _looks_like_key(text: str) -> bool:
    """True, если строка похожа на «ключ: значение» (а не на «http://...» или список)."""
    if text.startswith(("[", "{", "-", "&", "*")):
        return False
    key, value = _split_key(text)
    return bool(key) and (key != text.strip())


def _fill_value(
    result: dict[str, Any],
    key: str,
    value: str,
    lines: list[tuple[int, str]],
    index: int,
    item_indent: int,
) -> int:
    """Кладёт значение ключа в словарь, при необходимости читая вложенный блок."""
    if value in ("|", ">", "|-", ">-"):
        text, index = _parse_block_scalar(lines, index, item_indent)
        result[key] = text
        return index
    if value:
        result[key] = _scalar(value)
        return index
    # пустое значение: либо вложенный блок, либо None
    if index < len(lines) and lines[index][0] > item_indent:
        nested, index = _parse_block(lines, index, lines[index][0])
        result[key] = nested
    else:
        result[key] = None
    return index


def _parse_map(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        cur_indent, body = lines[index]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise YamliteError(f"лишний отступ (проверьте выравнивание) около: {body!r}")
        if body.startswith("- "):
            break
        if ":" not in body:
            raise YamliteError(f"ожидался «ключ: значение», получено: {body!r}")
        key, value = _split_key(body)
        index += 1
        if value in ("|", ">", "|-", ">-"):
            text, index = _parse_block_scalar(lines, index, indent)
            result[key] = text
        elif value == "":
            if index < len(lines) and lines[index][0] > indent:
                nested, index = _parse_block(lines, index, lines[index][0])
                result[key] = nested
            else:
                result[key] = None
        else:
            result[key] = _scalar(value)
    return result, index


def _parse_block_scalar(lines: list[tuple[int, str]], index: int, parent_indent: int) -> tuple[str, int]:
    parts: list[str] = []
    while index < len(lines) and lines[index][0] > parent_indent:
        parts.append(lines[index][1])
        index += 1
    return "\n".join(parts), index


def _split_key(body: str) -> tuple[str, str]:
    """'name: value' -> ('name', 'value'); учитывает кавычки и потоковые скобки."""
    quote: str | None = None
    depth = 0
    for i, ch in enumerate(body):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == ":" and depth == 0:
            if i + 1 >= len(body) or body[i + 1] == " ":
                key = body[:i].strip().strip("\"'")
                return key, body[i + 1 :].strip()
    return body.strip(), ""


def _is_quoted_or_flow(text: str) -> bool:
    return text[:1] in "\"'[{|"


def _scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    quoted = _QUOTED.match(text)
    if quoted:
        return quoted.group("body")
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part) for part in _split_flow(inner)]
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        result: dict[str, Any] = {}
        if not inner:
            return result
        for part in _split_flow(inner):
            key, _, value = part.partition(":")
            result[_scalar(key.strip())] = _scalar(value.strip())
        return result
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text.replace("_", ""))
    except ValueError:
        return text


def _split_flow(inner: str) -> list[str]:
    """Режет потоковую последовательность по запятым вне кавычек/скобок."""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current = ""
    for ch in inner:
        if quote:
            current += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            current += ch
        elif ch in "[{":
            depth += 1
            current += ch
        elif ch in "]}":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    return parts
