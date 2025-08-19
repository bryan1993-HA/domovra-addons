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
            -- colonnes ajoutées plus bas si manquantes (migrations)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS stock_lots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            qty REAL NOT NULL,
            frozen_on TEXT,
            best_before TEXT,
            -- colonne created_on ajoutée plus bas si manquante (migration)
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

        # ----- Migration : ajout de created_on dans stock_lots (+ backfill)
        if not _column_exists(c, "stock_lots", "created_on"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN created_on TEXT")
            # Backfill depuis le premier mouvement IN (date d'ajout)
            c.execute("""
              UPDATE stock_lots
              SET created_on = (
                SELECT MIN(m.ts)
                FROM movements m
                WHERE m.lot_id = stock_lots.id AND m.type='IN'
              )
              WHERE created_on IS NULL
            """)

        # ----- 🚀 Nouvelle migration : seuil mini par produit
        if not _column_exists(c, "products", "min_qty"):
            c.execute("ALTER TABLE products ADD COLUMN min_qty REAL")  # nullable

                # ----- Migration : champs supplémentaires pour locations
        if not _column_exists(c, "locations", "is_freezer"):
            c.execute("ALTER TABLE locations ADD COLUMN is_freezer INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(c, "locations", "description"):
            c.execute("ALTER TABLE locations ADD COLUMN description TEXT")


        c.commit()

# ---------- Locations
# ---------- Locations
def add_location(name: str, is_freezer: int = 0, description: str | None = None) -> int:
    name = name.strip()
    is_freezer = 1 if is_freezer else 0
    desc = (description or "").strip() or None
    with _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO locations(name, is_freezer, description) VALUES(?, ?, ?)",
                (name, is_freezer, desc)
            )
            c.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            row = c.execute("SELECT id FROM locations WHERE name=?", (name,)).fetchone()
            return int(row["id"]) if row else 0

def list_locations():
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, name, COALESCE(is_freezer,0) AS is_freezer, COALESCE(description,'') AS description "
            "FROM locations ORDER BY name"
        )]

def update_location(location_id: int, name: str, is_freezer: int | None = None, description: str | None = None):
    """
    Rétro‑compat : tu peux appeler avec seulement (id, name).
    Si is_freezer/description sont fournis (non None), on les met à jour aussi.
    """
    sets = ["name=?"]
    params: list = [name.strip()]
    if is_freezer is not None:
        sets.append("is_freezer=?")
        params.append(1 if is_freezer else 0)
    if description is not None:
        sets.append("description=?")
        params.append((description or "").strip() or None)
    params.append(int(location_id))
    with _conn() as c:
        c.execute(f"UPDATE locations SET {', '.join(sets)} WHERE id=?", params)
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

def move_lots_from_location(src_location_id: int, dest_location_id: int):
    """Déplace tous les lots d'un emplacement vers un autre (sans toucher aux mouvements)."""
    if int(src_location_id) == int(dest_location_id):
        return
    with _conn() as c:
        c.execute("UPDATE stock_lots SET location_id=? WHERE location_id=?", (int(dest_location_id), int(src_location_id)))
        c.commit()

# ---------- Products
def add_product(name: str, unit: str = 'pièce', shelf: int = 90,
                barcode: str | None = None,
                min_qty: float | None = None) -> int:
    """
    Ajoute un produit. Unicité sur name (héritée) et sur barcode (si non NULL).
    Si conflit, renvoie l'id existant (par name ou barcode).
    """
    name = name.strip()
    unit = (unit.strip() or 'pièce')
    shelf = int(shelf)
    barcode = (barcode.strip() or None) if isinstance(barcode, str) else None
    min_qty = float(min_qty) if (min_qty is not None and str(min_qty).strip() != "") else None
    if min_qty is not None and min_qty < 0: min_qty = 0.0

    with _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO products(name,unit,default_shelf_life_days,barcode,min_qty) VALUES (?,?,?,?,?)",
                (name, unit, shelf, barcode, min_qty)
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
        return [dict(r) for r in c.execute(
            "SELECT id, name, unit, default_shelf_life_days, barcode, min_qty FROM products ORDER BY name"
        )]

def list_products_with_stats():
    """
    Retourne les produits avec:
      - qty_total (somme des lots)
      - lots_count
      - min_qty
      - delta = qty_total - min_qty (NULL si min_qty NULL)
    """
    with _conn() as c:
        q = """
        WITH totals AS (
          SELECT product_id, COALESCE(SUM(qty),0) AS qty_total, COUNT(id) AS lots_count
          FROM stock_lots
          GROUP BY product_id
        )
        SELECT
          p.id, p.name, p.unit, p.default_shelf_life_days, p.barcode, p.min_qty,
          COALESCE(t.qty_total,0) AS qty_total,
          COALESCE(t.lots_count,0) AS lots_count,
          CASE WHEN p.min_qty IS NULL THEN NULL ELSE COALESCE(t.qty_total,0) - p.min_qty END AS delta
        FROM products p
        LEFT JOIN totals t ON t.product_id = p.id
        ORDER BY p.name
        """
        return [dict(r) for r in c.execute(q)]

def list_low_stock_products(limit: int = 8):
    """
    Produits FAIBLES : min_qty défini ET qty_total <= min_qty.
    Tri par criticité (delta croissant), puis qty_total croissant, puis nom.
    """
    with _conn() as c:
        q = """
        WITH totals AS (
          SELECT product_id, COALESCE(SUM(qty),0) AS qty_total
          FROM stock_lots
          GROUP BY product_id
        )
        SELECT
          p.id, p.name, p.unit, p.barcode, p.min_qty,
          COALESCE(t.qty_total,0) AS qty_total,
          (COALESCE(t.qty_total,0) - p.min_qty) AS delta
        FROM products p
        LEFT JOIN totals t ON t.product_id = p.id
        WHERE p.min_qty IS NOT NULL
          AND COALESCE(t.qty_total,0) <= p.min_qty
        ORDER BY delta ASC, qty_total ASC, p.name
        LIMIT ?
        """
        return [dict(r) for r in c.execute(q, (int(limit),))]

def update_product(product_id: int, name: str, unit: str,
                   default_shelf_life_days: int,
                   min_qty: float | None = None,
                   barcode: str | None = None):
    """
    Mise à jour produit. Les anciens appels continuent de marcher
    (min_qty/barcode sont optionnels).
    """
    name = name.strip()
    unit = unit.strip() or 'pièce'
    default_shelf_life_days = int(default_shelf_life_days)
    if min_qty is not None and str(min_qty).strip() != "":
        try:
            min_qty = float(min_qty)
            if min_qty < 0: min_qty = 0.0
        except ValueError:
            min_qty = None
    else:
        # On respecte 'None' = pas de seuil
        min_qty = None

    with _conn() as c:
        # Si barcode est fourni, on l’inclut ; sinon on ne le touche pas
        if barcode is not None:
            barcode = (barcode.strip() or None)
            c.execute(
                "UPDATE products SET name=?, unit=?, default_shelf_life_days=?, barcode=?, min_qty=? WHERE id=?",
                (name, unit, default_shelf_life_days, barcode, min_qty, product_id)
            )
        else:
            c.execute(
                "UPDATE products SET name=?, unit=?, default_shelf_life_days=?, min_qty=? WHERE id=?",
                (name, unit, default_shelf_life_days, min_qty, product_id)
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
        today = _today()
        cur = c.execute(
            """INSERT INTO stock_lots(product_id,location_id,qty,frozen_on,best_before,created_on)
               VALUES(?,?,?,?,?,?)""",
            (product_id, location_id, qty, frozen_on, best_before, today)
        )
        lot_id = cur.lastrowid
        c.execute(
            """INSERT INTO movements(lot_id,type,qty,ts,note)
               VALUES(?,?,?,?,?)""",
            (lot_id, 'IN', qty, today, None)
        )
        c.commit()
    return lot_id

def list_lots():
    with _conn() as c:
        q = """SELECT
                 l.id,
                 l.product_id,
                 l.location_id,
                 p.name        AS product,
                 p.unit        AS unit,
                 COALESCE(p.barcode,'') AS barcode,
                 loc.name      AS location,
                 l.qty,
                 l.frozen_on,
                 l.best_before,
                 l.created_on  AS created_on
               FROM stock_lots l
               JOIN products  p   ON p.id  = l.product_id
               JOIN locations loc ON loc.id = l.location_id
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
