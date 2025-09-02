# domovra/app/routes/ha.py
from __future__ import annotations

from datetime import date
import sqlite3
from typing import Optional, Set, Tuple, List
from fastapi import APIRouter, HTTPException

from config import DB_PATH, get_retention_thresholds

router = APIRouter(prefix="/api/ha", tags=["home-assistant"])


# --------- Utils introspection SQLite ----------------------------------------
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
        cols.add(str(r[1]))
    return cols


def _find_activation_column(cols: Set[str]) -> Optional[str]:
    # Reconnaît diverses conventions pour le flag d’activation
    for c in ("active", "enabled", "is_active"):
        if c in cols:
            return c
    return None


def _guess_lots_table(conn: sqlite3.Connection) -> Optional[str]:
    """
    Heuristique pour trouver la table des "lots".
    Critères principaux :
      - colonne best_before
      - colonne qty OU quantity
    Bonus si le nom évoque lot/stock/batch/invent…
    """
    candidates: List[Tuple[int, str]] = []
    for t in _tables(conn):
        cols = _columns(conn, t)
        if "best_before" in cols and ("qty" in cols or "quantity" in cols):
            score = 0
            name = t.lower()
            if any(k in name for k in ("lot", "stock", "batch", "invent")):
                score += 1
            candidates.append((score, t))

    if not candidates:
        # Fallback minimaliste : tenter 'lots' si existante
        if _table_exists(conn, "lots"):
            return "lots"
        return None

    candidates.sort(key=lambda x: (-x[0], x[1]))
    return candidates[0][1]


# --------- Construction dynamique des requêtes lots --------------------------
def _build_from_where_for_lots(
    conn: sqlite3.Connection, lots_table: str
) -> Tuple[str, str, Tuple]:
    """
    Construit dynamiquement la clause FROM/WHERE pour compter les lots en
    respectant les flags d’activation s’ils existent.

    - Filtre lots.<active>=1 si dispo.
    - Joint products si possible pour exiger products.<active>=1.
    """
    pcols = _columns(conn, "products") if _table_exists(conn, "products") else set()
    lcols = _columns(conn, lots_table)

    p_has_id = "id" in pcols
    l_has_product_id = "product_id" in lcols

    p_active_col = _find_activation_column(pcols) if pcols else None
    l_active_col = _find_activation_column(lcols)

    params: List[object] = []
    from_clause = f"{lots_table} AS L"
    where_parts: List[str] = []

    # Activation côté lots
    if l_active_col:
        where_parts.append(f"L.{l_active_col} = 1")

    # Activation côté produit (via jointure)
    if p_has_id and l_has_product_id and p_active_col:
        from_clause += " JOIN products AS P ON P.id = L.product_id"
        where_parts.append(f"P.{p_active_col} = 1")

    where_clause = " AND ".join(where_parts) if where_parts else "1=1"
    return from_clause, where_clause, tuple(params)


@router.get("/summary")
def ha_summary():
    """
    Compteurs Home Assistant (version 'actifs uniquement' si colonnes dispos) :
      - products : COUNT(*) FROM products [WHERE active=1 si dispo]
      - lots     : COUNT(*) FROM <lots> [WHERE L.active=1] [AND P.active=1 via JOIN products]
      - urgent   : lots avec days_left <= crit_days (actifs uniquement)
      - soon     : crit_days < days_left <= warn_days (actifs uniquement)

    days_left = julianday(best_before) - julianday(today)
    """
    warn_days, crit_days = get_retention_thresholds()
    today = date.today().isoformat()

    products_count = 0
    lots_count = 0
    urgent_count = 0
    soon_count = 0

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        # ---------------- PRODUCTS (avec filtre 'active' si dispo) ------------
        if _table_exists(conn, "products"):
            pcols = _columns(conn, "products")
            p_active_col = _find_activation_column(pcols)
            try:
                if p_active_col:
                    row = conn.execute(
                        f"SELECT COUNT(*) AS c FROM products WHERE {p_active_col} = 1"
                    ).fetchone()
                else:
                    row = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()
                products_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                products_count = 0

        # ---------------- LOTS (détection + filtres d’activation) --------------
        lots_table = None
        try:
            lots_table = _guess_lots_table(conn)
        except sqlite3.Error:
            lots_table = None

        if lots_table:
            try:
                from_clause, where_clause, params = _build_from_where_for_lots(conn, lots_table)

                # Total lots (sans condition qty, même logique que lots|length)
                row = conn.execute(
                    f"SELECT COUNT(*) AS c FROM {from_clause} WHERE {where_clause}",
                    params,
                ).fetchone()
                lots_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                lots_count = 0

            # URGENTS : days_left <= crit_days (actifs uniquement)
            try:
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS c
                    FROM {from_clause}
                    WHERE {where_clause}
                      AND L.best_before IS NOT NULL
                      AND L.best_before <> ''
                      AND (julianday(L.best_before) - julianday(?)) <= ?
                    """,
                    params + (today, crit_days),
                ).fetchone()
                urgent_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                urgent_count = 0

            # BIENTÔT : crit_days < days_left <= warn_days (actifs uniquement)
            try:
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS c
                    FROM {from_clause}
                    WHERE {where_clause}
                      AND L.best_before IS NOT NULL
                      AND L.best_before <> ''
                      AND (julianday(L.best_before) - julianday(?)) > ?
                      AND (julianday(L.best_before) - julianday(?)) <= ?
                    """,
                    params + (today, crit_days, today, warn_days),
                ).fetchone()
                soon_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                soon_count = 0
        # sinon : pas de table lots plausible → compteurs à 0 (tolérant)

    except sqlite3.Error as e:
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
