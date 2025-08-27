# ===============================================
# FILE: domovra/app/routes/admin_db.py
# Admin DB — vue avancée façon phpMyAdmin (onglets, recherche, export)
# ===============================================
from __future__ import annotations

import csv
import io
import re
import sqlite3
from typing import Any, Dict, List, Optional

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
    # PK simple uniquement ; si composite → None
    pks = [col["name"] for col in columns if col.get("pk")]
    return pks[0] if len(pks) == 1 else None

def _fk_list(c: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    return [dict(r) for r in c.execute(f"PRAGMA foreign_key_list({table})").fetchall()]

def _index_list(c: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in c.execute(f"PRAGMA index_list({table})").fetchall():
        row = dict(r)
        cols = [dict(ci) for ci in c.execute(f"PRAGMA index_info({row['name']})").fetchall()]
        row["columns"] = cols
        out.append(row)
    return out

def _trigger_list(c: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    return [dict(r) for r in c.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=? ORDER BY name",
        (table,),
    ).fetchall()]

def _reverse_relations(c: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    # Tables qui pointent vers `table`
    out: List[Dict[str, Any]] = []
    for t in _list_tables(c):
        try:
            for fk in _fk_list(c, t):
                if fk.get("table") == table:
                    out.append({"from": t, **fk})
        except Exception:
            pass
    return out


# ----------------- Routes -----------------

@router.get("/admin/db", response_class=HTMLResponse)
async def admin_db_home(request: Request):
    with _conn() as c:
        tables = _list_tables(c)
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
    tab: str = Query("data"),  # data | schema | indexes | triggers | relations | console
    q: str | None = Query(None, description="Recherche globale LIKE"),
    page: int = Query(1, ge=1),
    page_size: int = Query(_DEF_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    order_by: str | None = Query(None),
    desc: bool = Query(True),
):
    allowed_tabs = {"data", "schema", "indexes", "triggers", "relations", "console"}
    if tab not in allowed_tabs:
        tab = "data"

    with _conn() as c:
        if table not in _list_tables(c):
            raise HTTPException(status_code=404, detail=f"Table '{table}' introuvable")

        cols_meta = _table_columns(c, table)
        columns = [col["name"] for col in cols_meta]
        pk_name = _table_pk_name(cols_meta)

        total = 0
        data: List[Dict[str, Any]] = []

        if tab == "data":
            # Tri
            order = order_by if (order_by in columns) else None
            order_sql = f" ORDER BY {order} {'DESC' if desc else 'ASC'}" if order else " ORDER BY rowid DESC"

            # Filtre
            where_sql = ""
            params: List[Any] = []
            if q:
                like = f"%{q}%"
                where_sql = " WHERE " + " OR ".join([f"CAST({cname} AS TEXT) LIKE ?" for cname in columns])
                params = [like] * len(columns)

            total = c.execute(f"SELECT COUNT(*) AS n FROM {table}{where_sql}", params).fetchone()["n"]
            offset = (page - 1) * page_size

            rows = c.execute(
                f"SELECT * FROM {table}{where_sql}{order_sql} LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
            data = [dict(r) for r in rows]

        # Autres onglets
        fks = _fk_list(c, table) if tab in ("schema", "relations") else []
        idx = _index_list(c, table) if tab == "indexes" else []
        trg = _trigger_list(c, table) if tab == "triggers" else []
        rev = _reverse_relations(c, table) if tab == "relations" else []

    return render_with_env(
        request.app.state.templates,
        "admin/db_table.html",
        request=request,
        BASE=ingress_base(request),
        table=table,
        tab=tab,
        q=q,
        columns=columns,
        rows=data,
        page=page,
        page_size=page_size,
        total=total,
        order_by=order_by if order_by in columns else None,
        desc=desc,
        pk_name=pk_name,
        cols_meta=cols_meta,
        fks=fks,
        idx=idx,
        trg=trg,
        rev=rev,
        title=f"Admin · {table}",
    )


# ----- Actions lignes: insert / update / delete -----

@router.post("/admin/db/table/{table}/insert")
async def admin_db_insert(table: str, request: Request):
    form = await request.form()
    fields = {k: v for k, v in form.items() if not k.startswith("_")}
    with _conn() as c:
        if table not in _list_tables(c):
            raise HTTPException(status_code=404, detail=f"Table '{table}' introuvable")
        cols = [col["name"] for col in _table_columns(c, table)]
        valid = {k: v for k, v in fields.items() if k in cols}
        if not valid:
            raise HTTPException(status_code=400, detail="Aucune colonne valide")
        keys = ", ".join(valid.keys())
        placeholders = ", ".join(["?"] * len(valid))
        c.execute(f"INSERT INTO {table} ({keys}) VALUES ({placeholders})", list(valid.values()))
        c.commit()
    return RedirectResponse(url=f"{ingress_base(request)}admin/db/table/{table}?tab=data", status_code=303)


@router.post("/admin/db/table/{table}/update")
async def admin_db_update(
    table: str,
    request: Request,
    _pk_name: str = Form(...),
    _pk_value: str = Form(...),
    _field: str = Form(...),
    _value: str = Form(None),
):
    with _conn() as c:
        cols = _table_columns(c, table)
        pk_name = _table_pk_name(cols)
        if not pk_name or pk_name != _pk_name:
            raise HTTPException(status_code=400, detail="Edition inline requiert une PK simple")
        if _field not in [col["name"] for col in cols]:
            raise HTTPException(status_code=400, detail="Colonne inconnue")
        sql = f"UPDATE {table} SET {_field}=? WHERE {_pk_name}=?"
        c.execute(sql, (_value, _pk_value))
        c.commit()
    return RedirectResponse(url=f"{ingress_base(request)}admin/db/table/{table}?tab=data", status_code=303)


@router.post("/admin/db/table/{table}/delete")
async def admin_db_delete(
    table: str,
    request: Request,
    _pk_name: str = Form(...),
    _pk_value: str = Form(...),
):
    with _conn() as c:
        cols = _table_columns(c, table)
        pk_name = _table_pk_name(cols)
        if not pk_name or pk_name != _pk_name:
            raise HTTPException(status_code=400, detail="Suppression requiert une PK simple")
        sql = f"DELETE FROM {table} WHERE {_pk_name}=?"
        c.execute(sql, (_pk_value,))
        c.commit()
    return RedirectResponse(url=f"{ingress_base(request)}admin/db/table/{table}?tab=data", status_code=303)


# ----- Export CSV (respecte filtre & tri) -----

@router.get("/admin/db/table/{table}/export.csv")
async def admin_db_export_csv(
    request: Request,
    table: str,
    q: str | None = Query(None),
    order_by: str | None = Query(None),
    desc: bool = Query(True),
):
    with _conn() as c:
        cols_rows = _table_columns(c, table)
        columns = [r["name"] for r in cols_rows]
        order = order_by if (order_by in columns) else None
        order_sql = f" ORDER BY {order} {'DESC' if desc else 'ASC'}" if order else " ORDER BY rowid DESC"
        where_sql = ""
        params: List[Any] = []
        if q:
            like = f"%{q}%"
            where_sql = " WHERE " + " OR ".join([f"CAST({cname} AS TEXT) LIKE ?" for cname in columns])
            params = [like] * len(columns)
        rows = c.execute(f"SELECT * FROM {table}{where_sql}{order_sql}", params).fetchall()

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


# ----- Console SQL (sécurisée) -----

@router.post("/admin/db/console/{table}", response_class=HTMLResponse)
async def admin_db_console_post(request: Request, table: str, sql: str = Form("")):
    sql = (sql or "").strip()
    if not _SQL_SAFE.match(sql):
        raise HTTPException(status_code=400, detail="Console limitée à SELECT/PRAGMA/EXPLAIN")
    with _conn() as c:
        try:
            rows = c.execute(sql).fetchall()
            cols = rows[0].keys() if rows else []
            data = [dict(r) for r in rows]
            err = None
        except Exception as e:
            cols, data, err = [], [], str(e)
    return render_with_env(
        request.app.state.templates,
        "admin/db_table.html",
        request=request,
        BASE=ingress_base(request),
        table=table,
        tab="console",
        console_sql=sql,
        console_cols=list(cols),
        console_rows=data,
        console_err=err,
        title=f"Admin · {table}",
    )
