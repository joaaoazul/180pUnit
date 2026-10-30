from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    price REAL,
    area_m2 REAL,
    rooms INTEGER,
    property_type TEXT,
    transaction_type TEXT NOT NULL DEFAULT 'sale',
    district TEXT,
    municipality TEXT,
    description TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (source, source_id)
);
CREATE TABLE IF NOT EXISTS price_history (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    price REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history ON price_history (source, source_id, seen_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str = "achados.db"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def upsert(self, l: Listing, seen_at: str | None = None) -> str:
        """Grava o anúncio. Devolve 'new', 'price_change' ou 'seen'."""
        seen_at = seen_at or now_iso()
        row = self.conn.execute(
            "SELECT price FROM listings WHERE source=? AND source_id=?",
            (l.source, l.source_id),
        ).fetchone()
        if row is None:
            self.conn.execute(
                """INSERT INTO listings (source, source_id, url, title, price, area_m2, rooms,
                   property_type, transaction_type, district, municipality, description,
                   first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (l.source, l.source_id, l.url, l.title, l.price, l.area_m2, l.rooms,
                 l.property_type, l.transaction, l.district, l.municipality,
                 l.description, seen_at, seen_at),
            )
            outcome = "new"
        else:
            self.conn.execute(
                """UPDATE listings SET url=?, title=?, price=?, area_m2=?, rooms=?,
                   property_type=?, transaction_type=?, district=?, municipality=?,
                   description=?, last_seen=?, active=1 WHERE source=? AND source_id=?""",
                (l.url, l.title, l.price, l.area_m2, l.rooms, l.property_type,
                 l.transaction, l.district, l.municipality, l.description, seen_at,
                 l.source, l.source_id),
            )
            outcome = "price_change" if row["price"] != l.price else "seen"
        if l.price is not None and outcome in ("new", "price_change"):
            self.conn.execute(
                "INSERT INTO price_history (source, source_id, seen_at, price) VALUES (?,?,?,?)",
                (l.source, l.source_id, seen_at, l.price),
            )
        self.conn.commit()
        return outcome

    def mark_inactive(self, source: str, run_started: str) -> int:
        """Anúncios da fonte não vistos nesta execução passam a inativos."""
        cur = self.conn.execute(
            "UPDATE listings SET active=0 WHERE source=? AND last_seen < ? AND active=1",
            (source, run_started),
        )
        self.conn.commit()
        return cur.rowcount

    def active_listings(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM listings WHERE active=1").fetchall()

    def price_history(self, source: str, source_id: str) -> list[float]:
        rows = self.conn.execute(
            "SELECT price FROM price_history WHERE source=? AND source_id=? ORDER BY seen_at",
            (source, source_id),
        ).fetchall()
        return [r["price"] for r in rows]
