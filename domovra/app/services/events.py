import json
from datetime import datetime, timezone
from ..db import _conn

def _ensure_events_table():
    with _conn() as c:
        c.execute("""
          CREATE TABLE IF NOT EXISTS events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            kind       TEXT NOT NULL,
            details    TEXT
          )
        """)
        c.commit()

def log_event(kind: str, details: dict):
    created_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(details or {}, ensure_ascii=False)
    with _conn() as c:
        c.execute("INSERT INTO events(created_at,kind,details) VALUES (?,?,?)",
                  (created_at, kind, payload))
        c.commit()

def list_events(limit: int = 200):
    with _conn() as c:
        rows = c.execute(
            "SELECT id, created_at, kind, details FROM events ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        items = []
        for r in rows:
            try:
                det = json.loads(r["details"] or "{}")
            except Exception:
                det = {}
            items.append({
                "id": r["id"],
                "created_at": r["created_at"],
                "kind": r["kind"],
                "details": det
            })
        return items
