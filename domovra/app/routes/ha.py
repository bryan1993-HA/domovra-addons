# domovra/app/routes/ha.py
from __future__ import annotations
from fastapi import APIRouter
from datetime import date
import sqlite3

from config import DB_PATH, get_retention_thresholds

router = APIRouter(prefix="/api/ha", tags=["home-assistant"])

@router.get("/summary")
def ha_summary():
    # Seuils depuis /data/settings.json (fallback configuré dans get_retention_thresholds)
    warn_days, crit_days = get_retention_thresholds()
    today = date.today()

    products_count = 0
    lots_count = 0
    soon_count = 0
    urgent_count = 0

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1) Compte produits
        try:
            cur.execute("SELECT COUNT(*) AS c FROM products")
            products_count = int(cur.fetchone()["c"] or 0)
        except Exception:
            products_count = 0  # tolérant si la table n'existe pas encore

        # 2) Lots (on considère qty>0 si présent ; sinon on compte tout)
        rows = []
        try:
            # schéma avec 'qty'
            cur.execute("""
                SELECT id, best_before, qty AS quantity
                FROM lots
                WHERE qty IS NULL OR qty > 0
            """)
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            # fallback schéma avec 'quantity'
            cur.execute("""
                SELECT id, best_before, quantity
                FROM lots
                WHERE quantity IS NULL OR quantity > 0
            """)
            rows = cur.fetchall()

        lots_count = len(rows)

        # 3) Classement Soon / Urgent selon jours restants
        for r in rows:
            bb = r["best_before"]
            if not bb:
                continue
            # bb attendu en ISO (YYYY-MM-DD[ ...])
            try:
                d = date.fromisoformat(str(bb)[:10])
            except Exception:
                continue

            days_left = (d - today).days
            if days_left <= crit_days:
                urgent_count += 1
            elif days_left <= warn_days:
                soon_count += 1

    except Exception:
        # on renvoie des valeurs tolérantes si la DB n'est pas dispo
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {
        "products_count": int(products_count),
        "lots_count": int(lots_count),
        "soon_count": int(soon_count),
        "urgent_count": int(urgent_count),
    }
