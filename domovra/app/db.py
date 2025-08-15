import os, sqlite3, datetime
DB_PATH = os.environ.get("DB_PATH", "/data/domovra.sqlite3")

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def _column_exists(c: sqlite3.Connection, table: str, column: str) -> bool:
    rows = c.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)

def init_db():
    with _conn() as c:
        # ----- Tables de base
        c.execute("""CREATE TABLE IF NOT EXISTS locations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            unit TEXT DEFAULT 'pièce',
            default_shelf_life_days INTEGER DEFAULT 90
            -- colonne barcode ajoutée plus bas si manquante (migration)
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

        # ----- Migration : ajout de la colonne barcode si absente
        if not _column_exists(c, "products", "barcode"):
            c.execute("ALTER TABLE products ADD COLUMN barcode TEXT")
        # Index d'unicité (en tenant compte des NULL)
        c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_products_barcode_unique
                     ON products(barcode) WHERE barcode IS NOT NULL""")
        c.commit()

# ---------- Locations
def add_location(name: str) -> int:
    name = name.strip()
    with _conn() as c:
        try:
            cur = c.execute("INSERT INTO locations(name) VALUES(?)", (name,))
            c.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            row = c.execute("SELECT id FROM locations WHERE name=?", (name,)).fetchone()
            return int(row["id"]) if row else 0

def list_locations():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM locations ORDER BY name")]

def list_locations_with_counts():
    """
    Renvoie la liste des emplacements avec le nombre de lots rattachés.
    Retour: [{id, name, lot_count}]
    """
    with _conn() as c:
        try:
            q = """
                SELECT l.id, l.name, COALESCE(COUNT(s.id), 0) AS lot_count
                FROM locations l
                LEFT JOIN stock_lots s ON s.location_id = l.id
                GROUP BY l.id, l.name
                ORDER BY l.name
            """
            return [dict(r) for r in c.execute(q)]
        except sqlite3.OperationalError:
            # Si la table stock_lots n'existe pas encore, on retourne 0
            q = "SELECT id, name, 0 AS lot_count FROM locations ORDER BY name"
            return [dict(r) for r in c.execute(q)]

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
def add_product(name: str, unit: str = 'pièce', shelf: int = 90, barcode: str | None = None) -> int:
    """
    Ajoute un produit. Unicité sur name (héritée) et sur barcode (si non NULL).
    Si conflit, renvoie l'id existant (par name ou barcode).
    """
    name = name.strip()
    unit = (unit.strip() or 'pièce')
    shelf = int(shelf)
    barcode = (barcode.strip() or None) if isinstance(barcode, str) else None

    with _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO products(name,unit,default_shelf_life_days,barcode) VALUES (?,?,?,?)",
                (name, unit, shelf, barcode)
            )
            c.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # Conflit : on tente par name, puis par barcode
            row = c.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()
            if row:
                return int(row["id"])
            if barcode:
                row = c.execute("SELECT id FROM products WHERE barcode=?", (barcode,)).fetchone()
                if row:
                    return int(row["id"])
            return 0

def list_products():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT id, name, unit, default_shelf_life_days, barcode FROM products ORDER BY name")]

def list_products_with_stats():
    with _conn() as c:
        q = """
        SELECT
          p.id, p.name, p.unit, p.default_shelf_life_days, p.barcode,
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
