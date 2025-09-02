# ===============================================
# Admin DB — version simple (list, view, export)
# ===============================================
from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any, List

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from config import DB_PATH
from utils.http import ingress_base, render as render_with_env

router = APIRouter()

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

@router.get("/admin/db", response_class=HTMLResponse)
async def admin_db_home(request: Request):
    with _conn() as c:
        rows = c.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """).fetchall()
        tables = [r["name"] for r in rows]

    return render_with_env(
        request.app.state.templates,
        "admin/db_list.html",
        request=request,
        BASE=ingress_base(request),
        tables=tables,
        db_path=DB_PATH,
        title="Admin · Base de données",
    )

@router.get("/admin/db/table/{table}", response_class=HTMLResponse)
async def admin_db_table(
    request: Request,
    table: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    order_by: str | None = Query(None),
    desc: bool = Query(True),
):
    with _conn() as c:
        # existence
        exists = c.execute(
            "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()["n"]
        if not exists:
            raise HTTPException(status_code=404, detail=f"Table '{table}' introuvable")

        # colonnes
        cols_rows = c.execute(f"PRAGMA table_info({table})").fetchall()
        columns = [r["name"] for r in cols_rows]

        # tri (fallback sur rowid)
        order = order_by if (order_by in columns) else None
        order_sql = f" ORDER BY {order} {'DESC' if desc else 'ASC'}" if order else " ORDER BY rowid DESC"

        # pagination
        total = c.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        offset = (page - 1) * page_size

        rows = c.execute(
            f"SELECT * FROM {table}{order_sql} LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        data: List[dict[str, Any]] = [dict(r) for r in rows]

    return render_with_env(
        request.app.state.templates,
        "admin/db_table.html",
        request=request,
        BASE=ingress_base(request),
        table=table,
        columns=columns,
        rows=data,
        page=page,
        page_size=page_size,
        total=total,
        order_by=order,
        desc=desc,
        title=f"Admin · {table}",
    )

@router.get("/admin/db/table/{table}/export.csv")
async def admin_db_export_csv(
    request: Request,
    table: str,
    order_by: str | None = Query(None),
    desc: bool = Query(True),
):
    with _conn() as c:
        exists = c.execute(
            "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()["n"]
        if not exists:
            raise HTTPException(status_code=404, detail=f"Table '{table}' introuvable")

        cols_rows = c.execute(f"PRAGMA table_info({table})").fetchall()
        columns = [r["name"] for r in cols_rows]

        order = order_by if (order_by in columns) else None
        order_sql = f" ORDER BY {order} {'DESC' if desc else 'ASC'}" if order else " ORDER BY rowid DESC"

        rows = c.execute(f"SELECT * FROM {table}{order_sql}").fetchall()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    for r in rows:
        writer.writerow(dict(r))
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={table}.csv"},
    )
