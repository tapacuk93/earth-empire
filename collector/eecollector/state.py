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
create table if not exists timeline (id text primary key, taken_at real not null, kind text not null,
                                     json text not null, listed_at real not null, attempts int not null default 0,
                                     priority int not null default 0);
"""


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)
        cols = [r[1] for r in self.db.execute("pragma table_info(timeline)")]
        if "priority" not in cols:  # state from before new-items-first
            self.db.execute("alter table timeline add column priority int not null default 0")
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

    def count_posts(self) -> int:
        return self.db.execute("select count(*) from items where json_extract(json, '$.kind') != 'story' "
                               "and id not like 'ig_repost_%'").fetchone()[0]

    def count_items(self) -> int:
        return self.db.execute("select count(*) from items").fetchone()[0]

    # media
    def media(self, key: str) -> tuple[str | None, str, str | None] | None:
        return self.db.execute("select src_pk, url, thumb from media where key=?", (key,)).fetchone()

    def save_media(self, key: str, src_pk: str | None, url: str, thumb: str | None) -> None:
        self.db.execute("insert or replace into media values (?,?,?,?)", (key, src_pk, url, thumb))
        self.db.commit()

    # the merged timeline still to ingest, newest first
    def enqueue(self, item_id: str, taken_at: float, kind: str, raw: dict, priority: int = 0) -> bool:
        new = self.db.execute("select 1 from timeline where id=?", (item_id,)).fetchone() is None
        self.db.execute("""insert into timeline(id, taken_at, kind, json, listed_at, priority) values (?,?,?,?,?,?)
                           on conflict(id) do update set taken_at=excluded.taken_at, kind=excluded.kind,
                           json=excluded.json, listed_at=excluded.listed_at,
                           priority=max(timeline.priority, excluded.priority)""",
                        (item_id, taken_at, kind, json.dumps(raw), time.time(), priority))
        self.db.commit()
        return new

    def timeline_next(self, priority_only: bool = False, skip_reposts: bool = False) -> tuple[str, float, str, dict, int, int] | None:
        """New items first (priority), then the owner's own posts and stories, then reposts; newest
        first within each. `skip_reposts` once this hour's repost requests are used up."""
        cond = (["priority > 0"] if priority_only else []) + (["kind != 'repost'"] if skip_reposts else [])
        where = ("where " + " and ".join(cond) + " ") if cond else ""
        row = self.db.execute("select id, taken_at, kind, json, attempts, priority from timeline " + where +
                              "order by priority desc, kind = 'repost', taken_at desc limit 1").fetchone()
        return (row[0], row[1], row[2], json.loads(row[3]), row[4], row[5]) if row else None

    def timeline_priority_len(self) -> int:
        return self.db.execute("select count(*) from timeline where priority > 0").fetchone()[0]

    def timeline_done(self, item_id: str) -> None:
        self.db.execute("delete from timeline where id=?", (item_id,))
        self.db.commit()

    def timeline_failed(self, item_id: str) -> int:
        self.db.execute("update timeline set attempts=attempts+1, taken_at=taken_at-0.001 where id=?", (item_id,))
        self.db.commit()
        return self.db.execute("select attempts from timeline where id=?", (item_id,)).fetchone()[0]

    def timeline_len(self) -> int:
        return self.db.execute("select count(*) from timeline").fetchone()[0]

    def timeline_kinds(self) -> dict:
        return dict(self.db.execute("select kind, count(*) from timeline group by kind").fetchall())

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
