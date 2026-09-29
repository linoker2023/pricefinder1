"""Хранилище истории цен — SQLite (без внешних зависимостей)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .parsers import Item

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
    uid         TEXT PRIMARY KEY,
    site_id     TEXT NOT NULL,
    site_name   TEXT,
    title       TEXT,
    url         TEXT,
    image       TEXT,
    currency    TEXT,
    first_seen  TEXT,
    last_seen   TEXT
);
CREATE TABLE IF NOT EXISTS prices(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uid         TEXT NOT NULL REFERENCES items(uid) ON DELETE CASCADE,
    ts          TEXT NOT NULL,
    price       REAL NOT NULL,
    normalized  REAL,
    old_price   REAL,
    availability TEXT,
    query       TEXT,
    source_url  TEXT
);
CREATE INDEX IF NOT EXISTS idx_prices_uid_ts ON prices(uid, ts);
CREATE TABLE IF NOT EXISTS searches(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    query   TEXT,
    sites   TEXT,
    found   INTEGER,
    min_price REAL,
    best_uid  TEXT,
    best_url  TEXT
);
CREATE TABLE IF NOT EXISTS targets(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query       TEXT NOT NULL,
    sites       TEXT,
    target_price REAL,
    drop_pct    REAL,
    notify      TEXT,
    created     TEXT,
    active      INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS alerts(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    uid     TEXT,
    query   TEXT,
    kind    TEXT,
    price   REAL,
    payload TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


class Storage:
    def __init__(self, path: str | Path = "price_finder.db") -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --- запись результатов ---------------------------------------------
    def save_items(self, items: Iterable[Item], query: str = "") -> list[dict[str, Any]]:
        """Сохраняет карточки и возвращает события изменения цены для каждого товара."""
        events: list[dict[str, Any]] = []
        ts = _now()
        for it in items:
            row = self.conn.execute("SELECT * FROM items WHERE uid=?", (it.uid,)).fetchone()
            prev = None
            if row:
                prev = self.conn.execute(
                    "SELECT price, ts FROM prices WHERE uid=? ORDER BY ts DESC, id DESC LIMIT 1",
                    (it.uid,),
                ).fetchone()
                self.conn.execute(
                    "UPDATE items SET last_seen=?, title=?, url=?, image=?, site_name=? WHERE uid=?",
                    (ts, it.title, it.url, it.image, it.site_name, it.uid),
                )
            else:
                self.conn.execute(
                    "INSERT INTO items(uid, site_id, site_name, title, url, image, currency, first_seen, last_seen)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (it.uid, it.site_id, it.site_name, it.title, it.url, it.image, it.currency, ts, ts),
                )

            price_changed = prev is None or abs(float(prev["price"]) - float(it.price or 0)) > 1e-9
            if price_changed:
                self.conn.execute(
                    "INSERT INTO prices(uid, ts, price, normalized, old_price, availability, query, source_url)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (it.uid, ts, it.price, it.normalized_price, it.old_price, it.availability, query, it.source_url),
                )

            history = self.history(it.uid)
            prices = [h["price"] for h in history if h["price"] is not None]
            all_time_low = min(prices) if prices else None
            is_new = prev is None
            # «исторический минимум» — только если цена реально изменилась и стала
            # ниже всех предыдущих наблюдений (иначе алерт срабатывал бы каждый цикл)
            is_low = bool(
                price_changed
                and not is_new
                and all_time_low is not None
                and abs(float(it.price or 0) - float(all_time_low)) < 1e-9
            )
            event = {
                "item": it,
                "is_new": is_new,
                "prev_price": float(prev["price"]) if prev else None,
                "prev_ts": prev["ts"] if prev else None,
                "all_time_low": all_time_low,
                "is_all_time_low": is_low,
                "history": history,
                "price_changed": price_changed,
            }
            if prev and price_changed and prev["price"]:
                event["drop_pct"] = round((float(it.price or 0) - float(prev["price"])) / float(prev["price"]) * 100, 2)
            events.append(event)
        self.conn.commit()
        return events

    def log_search(self, query: str, sites: list[str], items: Sequence[Item], best: Item | None) -> None:
        self.conn.execute(
            "INSERT INTO searches(ts, query, sites, found, min_price, best_uid, best_url) VALUES(?,?,?,?,?,?,?)",
            (
                _now(),
                query,
                ",".join(sites),
                len(items),
                min((i.normalized_price or i.price or 0 for i in items), default=None),
                best.uid if best else None,
                best.url if best else None,
            ),
        )
        self.conn.commit()

    # --- чтение ------------------------------------------------------------
    def history(self, uid: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT ts, price, normalized, availability, query FROM prices WHERE uid=? ORDER BY ts DESC, id DESC LIMIT ?",
            (uid, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def all_items(self, query: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        sql = (
            "SELECT i.*, (SELECT price FROM prices p WHERE p.uid=i.uid ORDER BY p.ts DESC, p.id DESC LIMIT 1) AS last_price, "
            "(SELECT ts FROM prices p WHERE p.uid=i.uid ORDER BY p.ts DESC, p.id DESC LIMIT 1) AS last_ts, "
            "(SELECT MIN(price) FROM prices p WHERE p.uid=i.uid) AS min_price, "
            "(SELECT MAX(price) FROM prices p WHERE p.uid=i.uid) AS max_price, "
            "(SELECT COUNT(*) FROM prices p WHERE p.uid=i.uid) AS points "
            "FROM items i "
        )
        params: list[Any] = []
        if query:
            sql += "JOIN prices p2 ON p2.uid=i.uid AND p2.query=? "
            params.append(query)
            sql += "GROUP BY i.uid "
        sql += "ORDER BY last_price IS NULL, last_price ASC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def searches(self, limit: int = 30) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM searches ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def log_alert(self, uid: str, query: str, kind: str, price: float, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO alerts(ts, uid, query, kind, price, payload) VALUES(?,?,?,?,?,?)",
            (_now(), uid, query, kind, price, json.dumps(payload, ensure_ascii=False)[:4000]),
        )
        self.conn.commit()

    def alert_seen(self, uid: str, kind: str, price: float, cooldown_hours: float = 0.0) -> bool:
        """True, если такое уведомление уже отправляли.

        По умолчанию — если совпадают товар, тип события и цена.
        С cooldown_hours>0 для типа «target» достаточно того, что уведомление
        уже было в последние N часов (иначе письмо приходит каждый цикл).
        """
        if cooldown_hours > 0 and kind == "target":
            row = self.conn.execute(
                "SELECT id FROM alerts WHERE uid=? AND kind=? "
                "AND ts >= datetime('now', ?) LIMIT 1",
                (uid, kind, f"-{float(cooldown_hours)} hours"),
            ).fetchone()
            if row is not None:
                return True
        row = self.conn.execute(
            "SELECT id FROM alerts WHERE uid=? AND kind=? AND abs(price-?)<1e-9 LIMIT 1",
            (uid, kind, price),
        ).fetchone()
        return row is not None

    # --- цели мониторинга ---------------------------------------------------
    def add_target(self, query: str, sites: str | None, target_price: float | None, drop_pct: float | None,
                   notify: str = "telegram,email") -> int:
        cur = self.conn.execute(
            "INSERT INTO targets(query, sites, target_price, drop_pct, notify, created) VALUES(?,?,?,?,?,?)",
            (query, sites, target_price, drop_pct, notify, _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def targets(self, only_active: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM targets" + (" WHERE active=1" if only_active else "")
        return [dict(r) for r in self.conn.execute(sql).fetchall()]

    def set_target_active(self, target_id: int, active: bool) -> None:
        self.conn.execute("UPDATE targets SET active=? WHERE id=?", (1 if active else 0, target_id))
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
