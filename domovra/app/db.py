import os, sqlite3, datetime
DB_PATH = os.environ.get("DB_PATH", "/data/domovra.sqlite3")

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS locations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            unit TEXT DEFAULT 'pièce',
            default_shelf_life_days INTEGER DEFAULT 90
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS stock_lots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            qty REAL NOT NULL,
            frozen_on TEXT,
            best_before TEXT,
            FOREIGN KEY(product_id) REFERENCES products(id),
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS movements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lot_id INTEGER NOT NULL,
            type TEXT CHECK(type IN ('IN','OUT')) NOT NULL,
            qty REAL NOT NULL,
            ts TEXT NOT NULL,
            note TEXT,
            FOREIGN KEY(lot_id) REFERENCES stock_lots(id)
        )""")

# ---------- Locations
def add_location(name: str) -> int:
    name = name.strip()
    with _conn() as c:
        try:
            cur = c.execute("INSERT INTO locations(name) VALUES(?)", (name,))
            c.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # existe déjà → renvoyer l'id existant
            row = c.execute("SELECT id FROM locations WHERE name=?", (name,)).fetchone()
            return int(row["id"]) if row else 0  # 0 si vraiment introuvable (cas rare)

def list_locations():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM locations ORDER BY name")]

def update_location(location_id: int, name: str):
    with _conn() as c:
        c.execute("UPDATE locations SET name=? WHERE id=?", (name.strip(), location_id))
        c.commit()

def delete_location(location_id: int):
    """Supprime un emplacement + ses lots + mouvements liés."""
    with _conn() as c:
        lot_ids = [r["id"] for r in c.execute("SELECT id FROM stock_lots WHERE location_id=?", (location_id,))]
        if lot_ids:
            ph = ",".join("?" * len(lot_ids))
            c.execute(f"DELETE FROM movements WHERE lot_id IN ({ph})", lot_ids)
            c.execute(f"DELETE FROM stock_lots WHERE id IN ({ph})", lot_ids)
        c.execute("DELETE FROM locations WHERE id=?", (location_id,))
        c.commit()

# ---------- Products
def add_product(name: str, unit: str = 'pièce', shelf: int = 90) -> int:
    name = name.strip()
    unit = (unit.strip() or 'pièce')
    shelf = int(shelf)
    with _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO products(name,unit,default_shelf_life_days) VALUES (?,?,?)",
                (name, unit, shelf)
            )
            c.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # existe déjà → renvoyer l'id existant
            row = c.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()
            return int(row["id"]) if row else 0

def list_products():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM products ORDER BY name")]

def list_products_with_stats():
    with _conn() as c:
        q = """
        SELECT
          p.id, p.name, p.unit, p.default_shelf_life_days,
          COALESCE(SUM(l.qty),0) AS qty_total,
          COUNT(l.id) AS lots_count
        FROM products p
        LEFT JOIN stock_lots l ON l.product_id = p.id
        GROUP BY p.id
        ORDER BY p.name
        """
        return [dict(r) for r in c.execute(q)]

def update_product(product_id: int, name: str, unit: str, default_shelf_life_days: int):
    with _conn() as c:
        c.execute(
            "UPDATE products SET name=?, unit=?, default_shelf_life_days=? WHERE id=?",
            (name.strip(), unit.strip() or 'pièce', int(default_shelf_life_days), product_id)
        )
        c.commit()

def delete_product(product_id: int):
    """Supprime un produit + lots + mouvements liés."""
    with _conn() as c:
        lot_ids = [r["id"] for r in c.execute("SELECT id FROM stock_lots WHERE product_id=?", (product_id,))]
        if lot_ids:
            ph = ",".join("?" * len(lot_ids))
            c.execute(f"DELETE FROM movements WHERE lot_id IN ({ph})", lot_ids)
            c.execute(f"DELETE FROM stock_lots WHERE id IN ({ph})", lot_ids)
        c.execute("DELETE FROM products WHERE id=?", (product_id,))
        c.commit()

# ---------- Lots
def _today():
    return datetime.date.today().isoformat()

def add_lot(product_id: int, location_id: int, qty: float, frozen_on: str | None, best_before: str | None) -> int:
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO stock_lots(product_id,location_id,qty,frozen_on,best_before)
               VALUES(?,?,?,?,?)""",
            (product_id, location_id, qty, frozen_on, best_before)
        )
        lot_id = cur.lastrowid
        c.execute(
            """INSERT INTO movements(lot_id,type,qty,ts,note)
               VALUES(?,?,?,?,?)""",
            (lot_id, 'IN', qty, _today(), None)
        )
        c.commit()
    return lot_id

def list_lots():
    with _conn() as c:
        q = """SELECT l.id, l.product_id, l.location_id, p.name AS product, p.unit,
                      loc.name AS location, l.qty, l.frozen_on, l.best_before
               FROM stock_lots l
               JOIN products p ON p.id=l.product_id
               JOIN locations loc ON loc.id=l.location_id
               ORDER BY COALESCE(l.best_before, '9999-12-31') ASC, p.name"""
        return [dict(r) for r in c.execute(q)]

def consume_lot(lot_id: int, qty: float):
    with _conn() as c:
        row = c.execute("SELECT qty FROM stock_lots WHERE id=?", (lot_id,)).fetchone()
        if not row:
            return
        new_qty = float(row["qty"]) - float(qty)
        if new_qty <= 0:
            c.execute("DELETE FROM stock_lots WHERE id=?", (lot_id,))
            c.execute(
                """INSERT INTO movements(lot_id,type,qty,ts,note)
                   VALUES(?,?,?,DATE('now'),?)""",
                (lot_id, 'OUT', float(row["qty"]), 'delete lot')
            )
        else:
            c.execute("UPDATE stock_lots SET qty=? WHERE id=?", (new_qty, lot_id))
            c.execute(
                """INSERT INTO movements(lot_id,type,qty,ts,note)
                   VALUES(?,?,?,DATE('now'),?)""",
                (lot_id, 'OUT', qty, None)
            )
        c.commit()

def update_lot(lot_id: int, qty: float, location_id: int, frozen_on: str | None, best_before: str | None):
    with _conn() as c:
        c.execute(
            """UPDATE stock_lots
               SET qty=?, location_id=?, frozen_on=?, best_before=?
               WHERE id=?""",
            (float(qty), int(location_id), frozen_on, best_before, int(lot_id))
        )
        c.commit()

def delete_lot(lot_id: int):
    with _conn() as c:
        c.execute("DELETE FROM movements WHERE lot_id=?", (lot_id,))
        c.execute("DELETE FROM stock_lots WHERE id=?", (lot_id,))
        c.commit()

# ---------- Helpers
def status_for(best_before: str | None, warn_days: int, crit_days: int):
    if not best_before:
        return "unknown"
    try:
        days = (datetime.date.fromisoformat(best_before) - datetime.date.today()).days
    except ValueError:
        return "unknown"
    if days <= crit_days:
        return "red"
    if days <= warn_days:
        return "yellow"
    return "green"
