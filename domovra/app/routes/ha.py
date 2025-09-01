# domovra/app/routes/ha.py
from __future__ import annotations
from fastapi import APIRouter
import sqlite3

from config import DB_PATH, get_retention_thresholds

router = APIRouter(prefix="/api/ha", tags=["home-assistant"])

@router.get("/summary")
def ha_summary():
    warn_days, crit_days = get_retention_thresholds()

    products_count = 0
    lots_count = 0
    soon_count = 0
    urgent_count = 0

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # 1) Produits = COUNT(*)
        try:
            cur.execute("SELECT COUNT(*) FROM products")
            products_count = int(cur.fetchone()[0] or 0)
        except Exception:
            products_count = 0  # tolérant (premier démarrage / table absente)

        # 2) Lots / Urgents / Bientôt
        # On compte TOUTES les lignes de lots (comme {{ lots|length }}).
        # days_left = julianday(best_before) - aujourd'hui (timezone locale)
        sql = """
        WITH dated AS (
          SELECT
            best_before,
            CASE
              WHEN best_before IS NULL OR TRIM(best_before) = '' THEN NULL
              ELSE CAST(ROUND(julianday(best_before) - julianday('now','localtime')) AS INTEGER)
            END AS days_left
          FROM lots
        )
        SELECT
          (SELECT COUNT(*) FROM lots) AS lots_count,
          (SELECT COUNT(*) FROM dated WHERE days_left IS NOT NULL AND days_left <= ?) AS urgent_count,
          (SELECT COUNT(*) FROM dated WHERE days_left IS NOT NULL AND days_left > ? AND days_left <= ?) AS soon_count
        """
        try:
            cur.execute(sql, (crit_days, crit_days, warn_days))
            row = cur.fetchone()
            if row:
                lots_count   = int(row[0] or 0)
                urgent_count = int(row[1] or 0)
                soon_count   = int(row[2] or 0)
        except sqlite3.OperationalError:
            # Table lots absente : on renvoie 0 proprement
            lots_count = soon_count = urgent_count = 0

    finally:
        if conn is not None:
            conn.close()

    return {
        "products_count": products_count,
        "lots_count": lots_count,     # == {{ lots|length }}
        "soon_count":    soon_count,  # == {{ soon|length }}
        "urgent_count":  urgent_count # == {{ urg|length }}
    }
