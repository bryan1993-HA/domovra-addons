# domovra/app/routes/ha.py
from __future__ import annotations

from datetime import date
import sqlite3
from typing import Optional, Set
from fastapi import APIRouter, HTTPException

from config import DB_PATH, get_retention_thresholds

router = APIRouter(prefix="/api/ha", tags=["home-assistant"])


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    )
    return cur.fetchone() is not None


def _tables(conn: sqlite3.Connection) -> Set[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return {r[0] for r in cur.fetchall()}


def _columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    cols: Set[str] = set()
    for r in conn.execute(f"PRAGMA table_info('{table}')"):
        # r = (cid, name, type, notnull, dflt_value, pk)
        cols.add(str(r[1]))
    return cols


def _guess_lots_table(conn: sqlite3.Connection) -> Optional[str]:
    """
    Heuristique pour trouver la table 'lots' réelle :
    - doit avoir 'best_before'
    - doit avoir 'qty' OU 'quantity' (peu importe pour nos compteurs)
    On choisit la 1re qui matche, avec un petit bonus si son nom évoque lots/stock/batch.
    """
    candidates = []
    for t in _tables(conn):
        cols = _columns(conn, t)
        if "best_before" in cols and ("qty" in cols or "quantity" in cols):
            score = 0
            name = t.lower()
            if any(k in name for k in ("lot", "stock", "batch", "invent")):
                score += 1
            candidates.append((score, t))

    if not candidates:
        # fallback ultra pragmatique : si 'lots' existe même sans qty/quantity, on la tente
        if _table_exists(conn, "lots"):
            return "lots"
        return None

    # privilégie les noms qui ressemblent, sinon 1er trouvé
    candidates.sort(key=lambda x: (-x[0], x[1]))
    return candidates[0][1]


@router.get("/summary")
def ha_summary():
    """
    Compteurs pour Home Assistant :
    - products    : COUNT(*) FROM products
    - lots        : COUNT(*) FROM <table des lots détectée>
    - urgent      : days_left <= crit_days
    - soon        : crit_days < days_left <= warn_days
    days_left = julianday(best_before) - julianday(today)
    """
    warn_days, crit_days = get_retention_thresholds()
    today = date.today().isoformat()  # YYYY-MM-DD

    products_count = 0
    lots_count = 0
    urgent_count = 0
    soon_count = 0

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        # PRODUCTS
        if _table_exists(conn, "products"):
            try:
                row = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()
                products_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                products_count = 0

        # LOTS — détection de la bonne table
        lots_table = None
        try:
            lots_table = _guess_lots_table(conn)
        except sqlite3.Error:
            lots_table = None

        if lots_table:
            # total lignes (même logique que lots|length : aucune condition sur qty)
            try:
                row = conn.execute(f"SELECT COUNT(*) AS c FROM {lots_table}").fetchone()
                lots_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                lots_count = 0

            # URGENTS: days_left <= crit_days
            try:
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS c
                    FROM {lots_table}
                    WHERE best_before IS NOT NULL
                      AND best_before <> ''
                      AND (julianday(best_before) - julianday(?)) <= ?
                    """,
                    (today, crit_days),
                ).fetchone()
                urgent_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                urgent_count = 0

            # BIENTÔT: crit_days < days_left <= warn_days
            try:
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS c
                    FROM {lots_table}
                    WHERE best_before IS NOT NULL
                      AND best_before <> ''
                      AND (julianday(best_before) - julianday(?)) > ?
                      AND (julianday(best_before) - julianday(?)) <= ?
                    """,
                    (today, crit_days, today, warn_days),
                ).fetchone()
                soon_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                soon_count = 0
        else:
            # Si aucune table de lots plausible n'existe, on renvoie 0 (comportement tolérant)
            lots_count = 0
            urgent_count = 0
            soon_count = 0

    except sqlite3.Error as e:
        # Base inaccessible/corrompue : 500 explicite
        raise HTTPException(status_code=500, detail=f"SQLite error: {e}") from e
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {
        "products": products_count,
        "lots": lots_count,
        "soon": soon_count,
        "urgent": urgent_count,
        "thresholds": {"warn_days": warn_days, "crit_days": crit_days},
        "as_of": today,
    }
