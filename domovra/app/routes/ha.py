# domovra/app/routes/ha.py
from __future__ import annotations

from datetime import date
import sqlite3
from fastapi import APIRouter, HTTPException

from config import DB_PATH, get_retention_thresholds

router = APIRouter(prefix="/api/ha", tags=["home-assistant"])


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    )
    return cur.fetchone() is not None


@router.get("/summary")
def ha_summary():
    """
    Résume l'état pour Home Assistant (entête UI) :

    - products_count : COUNT(*) FROM products
    - lots_count     : COUNT(*) FROM lots (toutes les lignes)
    - urgent_count   : lots avec days_left <= crit_days
    - soon_count     : lots avec crit_days < days_left <= warn_days

    where days_left = julianday(best_before) - today
    """
    # Seuils depuis /data/settings.json (fallback via get_retention_thresholds)
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

        # --- PRODUCTS ---
        if _table_exists(conn, "products"):
            try:
                cur = conn.execute("SELECT COUNT(*) AS c FROM products")
                row = cur.fetchone()
                products_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                # En cas d'erreur de requête : on laisse 0
                products_count = 0

        # --- LOTS (toutes lignes, sans filtre qty) ---
        if _table_exists(conn, "lots"):
            try:
                cur = conn.execute("SELECT COUNT(*) AS c FROM lots")
                row = cur.fetchone()
                lots_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                lots_count = 0

            # --- URGENTS : days_left <= crit_days ---
            # days_left = julianday(best_before) - julianday(today)
            try:
                cur = conn.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM lots
                    WHERE best_before IS NOT NULL
                      AND (julianday(best_before) - julianday(?)) <= ?
                    """,
                    (today, crit_days),
                )
                row = cur.fetchone()
                urgent_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                urgent_count = 0

            # --- BIENTÔT : crit_days < days_left <= warn_days ---
            try:
                cur = conn.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM lots
                    WHERE best_before IS NOT NULL
                      AND (julianday(best_before) - julianday(?)) > ?
                      AND (julianday(best_before) - julianday(?)) <= ?
                    """,
                    (today, crit_days, today, warn_days),
                )
                row = cur.fetchone()
                soon_count = int(row["c"] if row and row["c"] is not None else 0)
            except sqlite3.Error:
                soon_count = 0

        # Si la table lots n'existe pas : lots_count/urgent/soon restent à 0

    except sqlite3.Error as e:
        # Erreur d'ouverture de DB : on expose une 500 propre
        # (Option : retourner des zéros avec 200, mais ici on préfère signaler)
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
        # Bonus utile pour debug/HA
        "thresholds": {"warn_days": warn_days, "crit_days": crit_days},
        "as_of": today,
    }
