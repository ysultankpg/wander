"""SQLite storage — replaces Firestore (catalog, bookmarks) and Memory Bank.

One local file, no server, no billing. Three concerns live here:
  * destinations  — the curated catalog the agent recommends from
  * bookmarks     — saved trips, scoped to a user id
  * memories      — durable traveller preferences across sessions

Security note carried over from the review: user_id is NEVER a model-supplied
argument. It is injected by the server from the signed session cookie, so the
model cannot read or write another visitor's data by inventing an id.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "wander.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS destinations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    region TEXT,
    summary TEXT,
    best_months TEXT,
    daily_budget_usd INTEGER,
    tags TEXT
);
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    destination TEXT NOT NULL,
    travel_dates TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, kind, value)
);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------- destinations

def search_destinations(
    region: str = "",
    max_budget_usd: int = 0,
    tag: str = "",
    limit: int = 6,
) -> dict:
    """Filter the catalog in SQL rather than scanning it in Python.

    If a filter combination matches nothing, the unmatched filter is relaxed and
    the nearest real entries are returned instead — labelled as relaxed. An empty
    result is an open invitation for the model to invent destinations, which is
    exactly the failure we are engineering against.
    """
    def query(region_f: str, budget_f: int, tag_f: str) -> list[dict]:
        sql = "SELECT * FROM destinations WHERE 1=1"
        args: list = []
        if region_f:
            sql += " AND LOWER(region) = LOWER(?)"
            args.append(region_f.strip())
        if budget_f and int(budget_f) > 0:
            sql += " AND daily_budget_usd <= ?"
            args.append(int(budget_f))
        if tag_f:
            sql += " AND LOWER(tags) LIKE ?"
            args.append(f"%{tag_f.strip().lower()}%")
        sql += " ORDER BY daily_budget_usd ASC LIMIT ?"
        args.append(max(1, min(int(limit or 6), 20)))
        with connect() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    note = ""
    rows = query(region, max_budget_usd, tag)
    if not rows and tag:
        rows = query(region, max_budget_usd, "")
        note = f"No catalog entry is tagged {tag!r}; showing the closest matches on region and budget instead."
    if not rows and max_budget_usd:
        rows = query(region, 0, "")
        note = f"Nothing in the catalog fits under ${int(max_budget_usd)}/day; these are the cheapest available."
    if not rows:
        rows = query("", 0, "")
        note = "Those filters matched nothing; showing the cheapest catalog entries."

    if not rows:
        return {"count": 0, "destinations": [],
                "note": "The catalog is empty. Do not invent destinations."}
    for r in rows:
        r["tags"] = [t for t in (r.get("tags") or "").split(",") if t]
    result = {"count": len(rows), "destinations": rows}
    if note:
        result["note"] = note
        result["relaxed"] = True
    return result


def get_destination(destination_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM destinations WHERE id = ?",
                           (destination_id,)).fetchone()
    if not row:
        return {"error": f"No destination with id {destination_id!r}."}
    out = dict(row)
    out["tags"] = [t for t in (out.get("tags") or "").split(",") if t]
    return out


# ------------------------------------------------------------------ bookmarks

def save_bookmark(user_id: str, destination: str, travel_dates: str = "",
                  notes: str = "") -> dict:
    if not destination or not destination.strip():
        return {"error": "A destination name is required."}
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO bookmarks (user_id, destination, travel_dates, notes)"
            " VALUES (?,?,?,?)",
            (user_id, destination.strip(), travel_dates.strip(), notes.strip()),
        )
        return {"saved": True, "bookmark_id": cur.lastrowid,
                "destination": destination.strip()}


def list_bookmarks(user_id: str, limit: int = 20) -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, destination, travel_dates, notes, created_at FROM bookmarks"
            " WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, max(1, min(int(limit or 20), 50))),
        ).fetchall()
    return {"count": len(rows), "bookmarks": [dict(r) for r in rows]}


def delete_bookmark(user_id: str, bookmark_id: int) -> dict:
    """Ownership is enforced in the WHERE clause, not checked after the fact."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM bookmarks WHERE id = ? AND user_id = ?",
                           (int(bookmark_id), user_id))
        if cur.rowcount == 0:
            return {"error": "No such bookmark for this traveller."}
    return {"deleted": True, "bookmark_id": int(bookmark_id)}


# ------------------------------------------------------------------- memories

def remember(user_id: str, kind: str, value: str) -> dict:
    """Store a durable preference. Duplicates collapse via the UNIQUE index."""
    if not kind or not value:
        return {"error": "Both kind and value are required."}
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO memories (user_id, kind, value) VALUES (?,?,?)",
            (user_id, kind.strip().lower(), value.strip()),
        )
    return {"remembered": True, "kind": kind.strip().lower(), "value": value.strip()}


def recall(user_id: str) -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT kind, value FROM memories WHERE user_id = ? ORDER BY kind",
            (user_id,),
        ).fetchall()
    grouped: dict[str, list[str]] = {}
    for r in rows:
        grouped.setdefault(r["kind"], []).append(r["value"])
    return {"memories": grouped}


def forget(user_id: str, kind: str = "", value: str = "") -> dict:
    sql, args = "DELETE FROM memories WHERE user_id = ?", [user_id]
    if kind:
        sql += " AND kind = ?"
        args.append(kind.strip().lower())
    if value:
        sql += " AND value = ?"
        args.append(value.strip())
    with connect() as conn:
        cur = conn.execute(sql, args)
    return {"forgotten": cur.rowcount}


def memory_context(user_id: str) -> str:
    """Compact preference summary injected into the system prompt each turn."""
    mems = recall(user_id).get("memories") or {}
    if not mems:
        return ""
    parts = [f"{k}: {', '.join(v)}" for k, v in mems.items()]
    return "Known traveller preferences — " + "; ".join(parts)
