"""SQLite storage (stdlib sqlite3). Schema is created on startup."""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone


def db_path() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    return url.split("sqlite:///", 1)[1] if "sqlite:///" in url else url


def connect() -> sqlite3.Connection:
    p = db_path()
    if os.path.dirname(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with closing(connect()) as c, c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, system_prompt TEXT)"
        )


def ping() -> bool:
    try:
        with closing(connect()) as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


def get_history(session_id: str) -> list[dict]:
    with closing(connect()) as c:
        rows = c.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
    out = []
    for r in rows:
        m = {"role": r["role"], "content": r["content"]}
        if r["metadata"]:
            m["metadata"] = json.loads(r["metadata"])
        out.append(m)
    return out


def get_system_prompt(session_id: str) -> str | None:
    with closing(connect()) as c:
        r = c.execute("SELECT system_prompt FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    return r["system_prompt"] if r else None


def save_turn(session_id: str, user_msg: str, reply: str, metadata: dict, system_prompt: str | None) -> None:
    """Persist both messages atomically; only called after a successful LLM call."""
    now = datetime.now(timezone.utc).isoformat()
    with closing(connect()) as c, c:
        if system_prompt is not None:
            c.execute(
                "INSERT INTO sessions(session_id, system_prompt) VALUES(?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET system_prompt=excluded.system_prompt",
                (session_id, system_prompt),
            )
        c.execute(
            "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
            (session_id, "user", user_msg, None, now),
        )
        c.execute(
            "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
            (session_id, "assistant", reply, json.dumps(metadata), now),
        )
