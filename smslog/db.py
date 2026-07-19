"""SMS Logger — database layer (logging only, no assistant tables).

Owns: messages, observed_messages, contacts, archive_messages, settings.
Assistant data (memories/nudges/reminders/...) belongs to whatever assistant
consumes the API — not here. A database inherited from an older combined
deployment may still contain those dormant legacy tables; they are ignored.
"""
import os
import json
import sqlite3
import logging
import urllib.parse
from datetime import datetime
from typing import Generator
from contextlib import contextmanager

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "conversations.db"))
PROFILES_DIR = os.getenv("PROFILES_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles"))


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that opens a DB connection, commits on success, rolls back on error."""
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _relative_time(ts_iso: str, now: datetime) -> str:
    try:
        dt = datetime.fromisoformat(ts_iso)
        seconds = (now - dt).total_seconds()
        if seconds < 3600: return "just now"
        if seconds < 86400: return "today"
        return f"{int(seconds // 86400)} days ago"
    except Exception:
        return ""


def _phone_enc(phone: str) -> str:
    return urllib.parse.quote(phone, safe="")


def _phone_dec(enc: str) -> str:
    return urllib.parse.unquote(enc)


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            phone     TEXT    NOT NULL,
            role      TEXT    NOT NULL,
            content   TEXT    NOT NULL,
            timestamp TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS observed_messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            phone     TEXT    NOT NULL,
            content   TEXT    NOT NULL,
            timestamp TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            phone TEXT PRIMARY KEY,
            name  TEXT,
            notes TEXT
        )
    """)
    # Historical SMS import (schema captured from the live NAS DB 2026-07-07).
    # ts = epoch milliseconds; readable_date is display-only ("Jun 4, 2024 10:41:14 AM")
    # and NOT sortable — always order archive rows by ts.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS archive_messages (
            dedup_key     TEXT PRIMARY KEY,
            phone         TEXT NOT NULL,
            direction     TEXT,
            body          TEXT,
            ts            INTEGER,
            readable_date TEXT,
            has_media     INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_archive_msg_phone ON archive_messages(phone)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_archive_msg_ts    ON archive_messages(ts)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Schema updates: extra contact columns
    for ddl in ("ALTER TABLE contacts ADD COLUMN aliases TEXT",
                "ALTER TABLE contacts ADD COLUMN updated_at TEXT",
                "ALTER TABLE contacts ADD COLUMN data TEXT"):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


# ── Profile & Contact Management ──────────────────────────────────────────────

def _index_path():
    return os.path.join(PROFILES_DIR, "index.json")


def _profile_key(phone: str) -> str:
    return phone.replace("+", "").replace(" ", "").replace("-", "")


def load_index() -> dict:
    """Load index from DB, fallback to file during migration."""
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT phone, name, aliases FROM contacts").fetchall()
            if rows:
                return {r[0]: {"name": r[1], "aliases": json.loads(r[2] or "[]")} for r in rows}
    except Exception as e:
        logging.error(f"DB load_index failed: {e}")

    path = _index_path()
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_profile(phone: str) -> dict:
    """Load profile from DB, fallback to JSON shard."""
    try:
        with get_db() as conn:
            row = conn.execute("SELECT name, aliases, notes, updated_at, data FROM contacts WHERE phone=?", (phone,)).fetchone()
            if row:
                res = {
                    "phone": phone,
                    "name": row[0],
                    "aliases": json.loads(row[1] or "[]"),
                    "notes": row[2],
                    "updated_at": row[3],
                }
                if row[4]:
                    try:
                        res.update(json.loads(row[4]))
                    except Exception:
                        pass
                return res
    except Exception as e:
        logging.error(f"DB load_profile failed: {e}")

    key = _profile_key(phone)
    path = os.path.join(PROFILES_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_profile(phone: str, data: dict) -> None:
    """Save profile to DB (and legacy file shard for now)."""
    name = data.get("name")
    aliases = json.dumps(data.get("aliases", []))
    notes = data.get("notes")
    updated_at = datetime.utcnow().isoformat()

    extra = {k: v for k, v in data.items() if k not in ("phone", "name", "aliases", "notes", "updated_at")}
    extra_json = json.dumps(extra)

    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO contacts (phone, name, aliases, notes, updated_at, data)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET
                    name=excluded.name,
                    aliases=excluded.aliases,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at,
                    data=excluded.data
            """, (phone, name, aliases, notes, updated_at, extra_json))
    except Exception as e:
        logging.error(f"DB save_profile failed: {e}")

    try:
        os.makedirs(PROFILES_DIR, exist_ok=True)
        key = _profile_key(phone)
        data["phone"] = phone
        data["updated_at"] = updated_at
        path = os.path.join(PROFILES_DIR, f"{key}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Legacy save_profile failed: {e}")


def get_contact_name(phone: str):
    with get_db() as conn:
        row = conn.execute("SELECT name FROM contacts WHERE phone = ?", (phone,)).fetchone()
    return row[0] if row and row[0] else None


def save_contact_name(phone: str, name: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO contacts (phone, name) VALUES (?, ?) ON CONFLICT(phone) DO UPDATE SET name=excluded.name",
            (phone, name),
        )


def get_contact_notes(phone: str):
    return load_profile(phone).get("notes")


def save_contact_notes(phone: str, notes: str) -> None:
    profile = load_profile(phone)
    profile["notes"] = notes
    save_profile(phone, profile)


# ── Message writes ────────────────────────────────────────────────────────────

def save_message(phone: str, role: str, content: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (phone, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (phone, role, content, datetime.utcnow().isoformat()),
        )


def save_observed(phone: str, content: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO observed_messages (phone, content, timestamp) VALUES (?, ?, ?)",
            (phone, content, datetime.utcnow().isoformat()),
        )


# ── Reads: history, contacts, search ─────────────────────────────────────────

# Union of all three message stores. Archive rows: order by ts (epoch ms);
# expose an ISO timestamp derived from ts so everything sorts consistently.
_UNION_SQL = """
    SELECT 'sms' AS source, phone, role, content, timestamp FROM messages
    UNION ALL
    SELECT 'observed' AS source, phone, 'incoming' AS role, content, timestamp FROM observed_messages
    UNION ALL
    SELECT 'archive' AS source, phone,
           CASE WHEN direction='incoming' THEN 'incoming' ELSE 'outgoing' END AS role,
           body AS content,
           datetime(ts/1000, 'unixepoch') AS timestamp
    FROM archive_messages
"""


def get_message_history(phone: str, query=None, limit: int = 100) -> list:
    """Fetch messages, observed_messages, and archive rows for a contact,
    optionally filtered by a text query. Oldest first."""
    with get_db() as conn:
        if query:
            q = f"%{query.lower()}%"
            rows = conn.execute(
                f"SELECT * FROM ({_UNION_SQL}) WHERE phone=? AND lower(content) LIKE ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (phone, q, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM ({_UNION_SQL}) WHERE phone=? ORDER BY timestamp DESC LIMIT ?",
                (phone, limit),
            ).fetchall()

    result = [
        {"source": source, "role": role, "content": content, "timestamp": timestamp}
        for source, _phone, role, content, timestamp in rows
    ]
    result.reverse()  # oldest first
    return result


def get_all_contacts() -> list:
    """One row per contact across all message stores: key, name, message_count,
    last_seen (ISO). Sorted by last_seen DESC. Contacts with a saved name but no
    messages are included with zero counts."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT phone, SUM(cnt) AS message_count, MAX(last_ts) AS last_ts
            FROM (
                SELECT phone, COUNT(*) AS cnt, MAX(timestamp) AS last_ts FROM observed_messages GROUP BY phone
                UNION ALL
                SELECT phone, COUNT(*), MAX(timestamp) FROM messages GROUP BY phone
                UNION ALL
                SELECT phone, COUNT(*), MAX(datetime(ts/1000, 'unixepoch')) FROM archive_messages GROUP BY phone
            ) GROUP BY phone
        """).fetchall()

    index = load_index()  # one query, avoids N+1 lookups
    seen = set()
    contacts = []
    for phone, count, last_ts in rows:
        seen.add(phone)
        name = (index.get(phone) or {}).get("name") or phone
        contacts.append({"key": phone, "name": name, "message_count": count or 0, "last_seen": last_ts})
    # Named contacts with zero messages still show up
    for phone, entry in index.items():
        if phone not in seen and entry.get("name"):
            contacts.append({"key": phone, "name": entry["name"], "message_count": 0, "last_seen": None})
    contacts.sort(key=lambda c: c["last_seen"] or "", reverse=True)
    return contacts


def search_messages(q: str, phone=None, limit: int = 50) -> list:
    """Plain-text search across all message stores, newest first."""
    like = f"%{q.lower()}%"
    sql = f"SELECT * FROM ({_UNION_SQL}) WHERE lower(content) LIKE ?"
    params = [like]
    if phone:
        sql += " AND phone = ?"
        params.append(phone)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {"source": source, "phone": p, "role": role, "content": content, "timestamp": timestamp}
        for source, p, role, content, timestamp in rows
    ]


def merge_contact(from_phone: str, into_phone: str) -> None:
    """Move all message data from one contact to another, then delete the source contact."""
    with get_db() as conn:
        conn.execute("UPDATE messages SET phone=? WHERE phone=?", (into_phone, from_phone))
        conn.execute("UPDATE observed_messages SET phone=? WHERE phone=?", (into_phone, from_phone))
        conn.execute("UPDATE archive_messages SET phone=? WHERE phone=?", (into_phone, from_phone))
        conn.execute("DELETE FROM contacts WHERE phone=?", (from_phone,))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
