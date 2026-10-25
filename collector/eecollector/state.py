"""The collector's own memory on the box: items sent, media uploaded, highlight membership, cursors.

SQLite in EE_STATE_DIR. It lets a backfill stop and continue, and lets an incremental run skip
media that is already on media.empire.earth.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
create table if not exists items (id text primary key, json text not null, updated real not null);
create table if not exists media (key text primary key, src_pk text, url text not null, thumb text);
create table if not exists membership (highlight_id text not null, item_id text not null, pos int not null,
                                       primary key (highlight_id, item_id));
create table if not exists highlights (id text primary key, json text not null, sig text);
create table if not exists kv (k text primary key, v text);
"""


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)
        self.db.commit()

    # kv
    def get(self, k: str, default: Any = None) -> Any:
        row = self.db.execute("select v from kv where k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, k: str, v: Any) -> None:
        self.db.execute("insert or replace into kv values (?,?)", (k, json.dumps(v)))
        self.db.commit()

    # items
    def item(self, item_id: str) -> dict | None:
        row = self.db.execute("select json from items where id=?", (item_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def has_item(self, item_id: str) -> bool:
        return self.db.execute("select 1 from items where id=?", (item_id,)).fetchone() is not None

    def save_item(self, item: dict) -> None:
        self.db.execute("insert or replace into items values (?,?,?)",
                        (item["id"], json.dumps(item), time.time()))
        self.db.commit()

    def count_items(self) -> int:
        return self.db.execute("select count(*) from items").fetchone()[0]

    # media
    def media(self, key: str) -> tuple[str | None, str, str | None] | None:
        return self.db.execute("select src_pk, url, thumb from media where key=?", (key,)).fetchone()

    def save_media(self, key: str, src_pk: str | None, url: str, thumb: str | None) -> None:
        self.db.execute("insert or replace into media values (?,?,?,?)", (key, src_pk, url, thumb))
        self.db.commit()

    # highlights
    def highlight(self, hid: str) -> tuple[dict, str | None] | None:
        row = self.db.execute("select json, sig from highlights where id=?", (hid,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def save_highlight(self, h: dict, sig: str | None) -> None:
        self.db.execute("insert or replace into highlights values (?,?,?)", (h["id"], json.dumps(h), sig))
        self.db.commit()

    def set_membership(self, hid: str, item_ids: list[str]) -> set[str]:
        """Replace a highlight's items; returns every item whose membership may have changed."""
        old = {r[0] for r in self.db.execute("select item_id from membership where highlight_id=?", (hid,))}
        self.db.execute("delete from membership where highlight_id=?", (hid,))
        self.db.executemany("insert or replace into membership values (?,?,?)",
                            [(hid, iid, i) for i, iid in enumerate(item_ids)])
        self.db.commit()
        return old | set(item_ids)

    def highlights_of(self, item_id: str) -> list[dict]:
        rows = self.db.execute(
            "select h.json from membership m join highlights h on h.id=m.highlight_id where m.item_id=?",
            (item_id,)).fetchall()
        out = []
        for (j,) in rows:
            h = json.loads(j)
            out.append({"id": h["id"], "title": h.get("title")})
        return sorted(out, key=lambda h: h["id"])
