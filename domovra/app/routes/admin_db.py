# =============================================================
# FILE: domovra/app/routes/admin_db.py (v1.1 "Admin DB Pro")
# Ultra-visu façon phpMyAdmin : Data, Schéma, Index, Triggers, Relations, Console
# — Vanilla JS + Jinja, sans lib externe
# — Sécurité: console limitée aux SELECT/PRAGMA/EXPLAIN; FK ON; transactions
# =============================================================
from __future__ import annotations


import csv
import io
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple


from fastapi import APIRouter, Request, Query, HTTPException, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse


from config import DB_PATH
from utils.http import ingress_base, render as render_with_env


router = APIRouter()


# ----------------- Helpers -----------------


def _conn() -> sqlite3.Connection:
c = sqlite3.connect(DB_PATH)
c.row_factory = sqlite3.Row
c.execute("PRAGMA foreign_keys=ON")
return c


_DEF_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 500


_SQL_SAFE = re.compile(r"^(\s*(SELECT|PRAGMA|EXPLAIN))", re.IGNORECASE | re.DOTALL)




def _list_tables(c: sqlite3.Connection) -> List[str]:
rows = c.execute(
"""
SELECT name FROM sqlite_master
WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'
ORDER BY name
"""
).fetchall()
return [r["name"] for r in rows]




def _table_columns(c: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
return [dict(r) for r in c.execute(f"PRAGMA table_info({table})").fetchall()]




def _table_pk_name(columns: List[Dict[str, Any]]) -> Optional[str]:
# Gère PK simple. Si composite → on désactive les actions inline.
pks = [col["name"] for col in columns if col.get("pk")]
return pks[0] if len(pks) == 1 else None




def _fk_list(c: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
return [dict(r) for r in c.execute(f"PRAGMA foreign_key_list({table})").fetchall()]




def _index_list(c: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
idx = []
for r in c.execute(f"PRAGMA index_list({table})").fetchall():
row = dict(r)
cols = [dict(ci) for ci in c.execute(f"PRAGMA index_info({row['name']})").fetchall()]
row["columns"] = cols
idx.append(row)
return idx




def _trigger_list(c: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
return [dict(r) for r in c.execute(
"SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=? ORDER BY name",
(table,),
).fetchall()]


)