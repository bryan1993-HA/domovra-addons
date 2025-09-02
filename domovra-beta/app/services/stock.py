# domovra/app/services/stock.py
import sqlite3
from settings_store import load_settings
from db import _conn

def get_low_stock_products(limit: int = 8):
    dflt = 1
    try:
        dflt = int(load_settings().get("low_stock_default", 1))
    except Exception:
        dflt = 1

    with _conn() as c:
        try:
            q = """
            SELECT
              p.id, p.name, p.unit,
              COALESCE(p.min_qty, ?) AS min_qty,
              COALESCE(SUM(l.qty), 0) AS qty_total
            FROM products p
            LEFT JOIN stock_lots l ON l.product_id = p.id
            GROUP BY p.id
            HAVING qty_total <= COALESCE(p.min_qty, ?) AND COALESCE(p.min_qty, ?) > 0
            ORDER BY (qty_total - COALESCE(p.min_qty, ?)) ASC, p.name
            LIMIT ?
            """
            rows = c.execute(q, (dflt, dflt, dflt, dflt, limit)).fetchall()
        except sqlite3.OperationalError:
            q = """
            SELECT
              p.id, p.name, p.unit,
              ? AS min_qty,
              COALESCE(SUM(l.qty), 0) AS qty_total
            FROM products p
            LEFT JOIN stock_lots l ON l.product_id = p.id
            GROUP BY p.id
            HAVING qty_total <= ? AND ? > 0
            ORDER BY (qty_total - ?) ASC, p.name
            LIMIT ?
            """
            rows = c.execute(q, (dflt, dflt, dflt, dflt, limit)).fetchall()

        items = []
        for r in rows:
            min_qty = float(r["min_qty"] or 0)
            qty_total = float(r["qty_total"] or 0)
            items.append({
                "id": r["id"],
                "name": r["name"],
                "unit": r["unit"],
                "min_qty": min_qty,
                "qty_total": qty_total,
                "delta": qty_total - min_qty,
            })
        return items
