from __future__ import annotations
from fastapi import APIRouter
import sqlite3
from config import DB_PATH, get_retention_thresholds

router = APIRouter(prefix="/api/ha", tags=["home-assistant"])

@router.get("/summary")
def ha_summary():
    warn_days, crit_days = get_retention_thresholds()

    # NB: on compte TOUTES les lignes de lots (aucun filtre sur qty),
    # exactement comme {{ lots|length }} dans le template.
    sql_counts = f"""
    WITH dated AS (
      SELECT
        id,
        best_before,
        CASE
          WHEN best_before IS NULL OR TRIM(best_before) = '' THEN NULL
          ELSE CAST(ROUND(julianday(best_before) - julianday('now','localtime')) AS INTEGER)
        END AS days_left
      FROM lots
    )
    SELECT
      (SELECT COUNT(*) FROM lots) AS lots_count, -- <== pas de filtre
      (SELECT COUNT(*) FROM dated WHERE days_left IS NOT NULL AND days_left <= {crit_days}) AS urgent_count,
      (SELECT COUNT(*) FROM dated WHERE days_left IS NOT NULL AND days_left > {crit_days} AND days_left <= {warn_days}) AS soon_count
    ;
    """

    products_count = 0
    lots_count = 0
    soon_count = 0
    urgent_count = 0

    conn = sqlite3.connect(DB_PATH)
    try:
      cur = conn.cursor()

      # Produits = COUNT(*)
      try:
        cur.execute("SELECT COUNT(*) FROM products")
        products_count = int(cur.fetchone()[0] or 0)
      except Exception:
        products_count = 0  # tolérant si table absente (premier boot)

      # Lots / Soon / Urgent selon J-*
      cur.execute(sql_counts)
      row = cur.fetchone()
      if row:
        lots_count   = int(row[0] or 0)
        urgent_count = int(row[1] or 0)
        soon_count   = int(row[2] or 0)
    finally:
      conn.close()

    return {
      "products_count": products_count,
      "lots_count": lots_count,     # ⇦ doit matcher {{ lots|length }}
      "soon_count":    soon_count,  # ⇦ doit matcher {{ soon|length }}
      "urgent_count":  urgent_count # ⇦ doit matcher {{ urg|length }}
    }
