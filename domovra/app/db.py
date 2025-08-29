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

        # ----- Migration : products.barcode (+ index unique null-safe)
        if not _column_exists(c, "products", "barcode"):
            c.execute("ALTER TABLE products ADD COLUMN barcode TEXT")
        c.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_products_barcode_unique
            ON products(barcode) WHERE barcode IS NOT NULL
        """)

        # ----- Migration : stock_lots.created_on (+ backfill)
        if not _column_exists(c, "stock_lots", "created_on"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN created_on TEXT")
            c.execute("""
              UPDATE stock_lots
              SET created_on = (
                SELECT MIN(m.ts)
                FROM movements m
                WHERE m.lot_id = stock_lots.id AND m.type='IN'
              )
              WHERE created_on IS NULL
            """)

        # ----- Lots : colonnes issues des achats (si absentes)
        if not _column_exists(c, "stock_lots", "article_name"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN article_name TEXT")
        if not _column_exists(c, "stock_lots", "brand"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN brand TEXT")
        if not _column_exists(c, "stock_lots", "ean"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN ean TEXT")
        if not _column_exists(c, "stock_lots", "price_total"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN price_total REAL")
        if not _column_exists(c, "stock_lots", "store"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN store TEXT")
        if not _column_exists(c, "stock_lots", "qty_per_unit"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN qty_per_unit REAL")
        if not _column_exists(c, "stock_lots", "multiplier"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN multiplier INTEGER")
        if not _column_exists(c, "stock_lots", "unit_at_purchase"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN unit_at_purchase TEXT")
        # ✅ Nouveaux champs nécessaires à achats.py
        if not _column_exists(c, "stock_lots", "name"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN name TEXT")
        if not _column_exists(c, "stock_lots", "note"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN note TEXT")

        # ----- Locations : champs supplémentaires
        if not _column_exists(c, "locations", "is_freezer"):
            c.execute("ALTER TABLE locations ADD COLUMN is_freezer INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(c, "locations", "description"):
            c.execute("ALTER TABLE locations ADD COLUMN description TEXT")

        # ----- Products : nouvelles colonnes (idempotent)
        if not _column_exists(c, "products", "min_qty"):
            c.execute("ALTER TABLE products ADD COLUMN min_qty REAL")
        if not _column_exists(c, "products", "description"):
            c.execute("ALTER TABLE products ADD COLUMN description TEXT")
        if not _column_exists(c, "products", "default_location_id"):
            c.execute("ALTER TABLE products ADD COLUMN default_location_id INTEGER")
        if not _column_exists(c, "products", "low_stock_enabled"):
            c.execute("ALTER TABLE products ADD COLUMN low_stock_enabled INTEGER NOT NULL DEFAULT 1")
        if not _column_exists(c, "products", "expiry_kind"):
            c.execute("ALTER TABLE products ADD COLUMN expiry_kind TEXT DEFAULT 'DLC'")
        if not _column_exists(c, "products", "default_freeze_shelf_days"):
            c.execute("ALTER TABLE products ADD COLUMN default_freeze_shelf_days INTEGER")
        if not _column_exists(c, "products", "no_freeze"):
            c.execute("ALTER TABLE products ADD COLUMN no_freeze INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(c, "products", "category"):
            c.execute("ALTER TABLE products ADD COLUMN category TEXT")
        if not _column_exists(c, "products", "parent_id"):
            c.execute("ALTER TABLE products ADD COLUMN parent_id INTEGER")

        # ----- Historique complet (soft delete + conversions + raisons)
        if not _column_exists(c, "stock_lots", "status"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
        if not _column_exists(c, "stock_lots", "ended_on"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN ended_on TEXT")
        if not _column_exists(c, "stock_lots", "initial_qty"):
            c.execute("ALTER TABLE stock_lots ADD COLUMN initial_qty REAL")

        if not _column_exists(c, "products", "unit_pivot"):
            c.execute("ALTER TABLE products ADD COLUMN unit_pivot TEXT")

        if not _column_exists(c, "movements", "unit_input"):
            c.execute("ALTER TABLE movements ADD COLUMN unit_input TEXT")
        if not _column_exists(c, "movements", "factor_to_pivot"):
            c.execute("ALTER TABLE movements ADD COLUMN factor_to_pivot REAL DEFAULT 1")
        if not _column_exists(c, "movements", "reason_code"):
            c.execute("ALTER TABLE movements ADD COLUMN reason_code TEXT")
        if not _column_exists(c, "movements", "price_allocated"):
            c.execute("ALTER TABLE movements ADD COLUMN price_allocated REAL")
        if not _column_exists(c, "movements", "location_from_id"):
            c.execute("ALTER TABLE movements ADD COLUMN location_from_id INTEGER")
        if not _column_exists(c, "movements", "location_to_id"):
            c.execute("ALTER TABLE movements ADD COLUMN location_to_id INTEGER")

        # ----- Backfill utiles
        try:
            c.execute("UPDATE stock_lots SET initial_qty = qty WHERE initial_qty IS NULL")
        except Exception:
            pass
        try:
            c.execute("UPDATE products SET unit_pivot = unit WHERE unit_pivot IS NULL")
        except Exception:
            pass

        c.commit()


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
    Rétro-compat : tu peux appeler avec seulement (id, name).
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
def add_product(
    name: str,
    unit: str = 'pièce',
    shelf: int = 90,
    barcode: str | None = None,                 # compat
    min_qty: float | None = None,
    description: str | None = None,
    default_location_id: int | None = None,
    low_stock_enabled: int | None = 1,
    expiry_kind: str | None = 'DLC',
    default_freeze_shelf_days: int | None = None,
    no_freeze: int | None = 0,
    category: str | None = None,
    parent_id: int | None = None,
) -> int:
    name = name.strip()
    unit = (unit or 'pièce').strip()
    try:
        shelf = int(shelf)
    except Exception:
        shelf = 90

    barcode = (barcode.strip() or None) if isinstance(barcode, str) else None

    def _float_or_none(x):
        if x is None: return None
        s = str(x).strip()
        if not s: return None
        try:
            v = float(s)
            return 0.0 if v < 0 else v
        except Exception:
            return None

    min_qty = _float_or_none(min_qty)

    description = (description or "").strip() or None
    try:
        default_location_id = int(default_location_id) if default_location_id not in (None, "",) else None
    except Exception:
        default_location_id = None
    low_stock_enabled = 0 if str(low_stock_enabled).strip() in ("0","false","off","no") else 1
    expiry_kind = (expiry_kind or "DLC").upper()
    if expiry_kind not in ("DLC", "DDM"): expiry_kind = "DLC"
    try:
        default_freeze_shelf_days = int(default_freeze_shelf_days) if str(default_freeze_shelf_days or "").strip() else None
    except Exception:
        default_freeze_shelf_days = None
    no_freeze = 1 if str(no_freeze).strip() in ("1","true","on","yes") else 0
    category = (category or "").strip() or None
    try:
        parent_id = int(parent_id) if parent_id not in (None, "",) else None
    except Exception:
        parent_id = None

    with _conn() as c:
        try:
            cur = c.execute(
                """INSERT INTO products
                   (name, unit, default_shelf_life_days, barcode, min_qty,
                    description, default_location_id, low_stock_enabled,
                    expiry_kind, default_freeze_shelf_days, no_freeze, category, parent_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, unit, shelf, barcode, min_qty,
                 description, default_location_id, low_stock_enabled,
                 expiry_kind, default_freeze_shelf_days, no_freeze, category, parent_id)
            )
            c.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
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
            """
            SELECT
              id,
              name,
              unit,
              default_shelf_life_days,
              barcode,
              min_qty,
              default_location_id,
              COALESCE(low_stock_enabled,1) AS low_stock_enabled,
              COALESCE(expiry_kind,'DLC')   AS expiry_kind,
              default_freeze_shelf_days,
              COALESCE(no_freeze,0)         AS no_freeze,
              COALESCE(category,'')         AS category,
              parent_id
            FROM products
            ORDER BY name COLLATE NOCASE
            """
        )]



def list_products_with_stats():
    with _conn() as c:
        q = """
        WITH totals AS (
          SELECT product_id, COALESCE(SUM(qty),0) AS qty_total, COUNT(id) AS lots_count
          FROM stock_lots
          WHERE status='open'
          GROUP BY product_id
        )
        SELECT
          p.id, p.name, p.unit, p.default_shelf_life_days, p.barcode, p.min_qty,
          COALESCE(p.description,'') AS description,
          p.default_location_id,
          COALESCE(p.low_stock_enabled,1) AS low_stock_enabled,
          COALESCE(p.expiry_kind,'DLC') AS expiry_kind,
          p.default_freeze_shelf_days,
          COALESCE(p.no_freeze,0) AS no_freeze,
          COALESCE(p.category,'') AS category,
          p.parent_id,
          COALESCE(t.qty_total,0) AS qty_total,
          COALESCE(t.lots_count,0) AS lots_count,
          CASE WHEN p.min_qty IS NULL THEN NULL ELSE COALESCE(t.qty_total,0) - p.min_qty END AS delta
        FROM products p
        LEFT JOIN totals t ON t.product_id = p.id
        ORDER BY p.name
        """
        return [dict(r) for r in c.execute(q)]


def list_low_stock_products(limit: int = 8):
    with _conn() as c:
        q = """
        WITH totals AS (
          SELECT product_id, COALESCE(SUM(qty),0) AS qty_total
          FROM stock_lots
          WHERE status='open'
          GROUP BY product_id
        )
        SELECT
          p.id, p.name, p.unit, p.barcode, p.min_qty,
          COALESCE(t.qty_total,0) AS qty_total,
          (COALESCE(t.qty_total,0) - p.min_qty) AS delta
        FROM products p
        LEFT JOIN totals t ON t.product_id = p.id
        WHERE p.min_qty IS NOT NULL
          AND COALESCE(p.low_stock_enabled,1) != 0   -- ← respecter le suivi
          AND COALESCE(t.qty_total,0) <= p.min_qty
        ORDER BY delta ASC, qty_total ASC, p.name
        LIMIT ?
        """
        return [dict(r) for r in c.execute(q, (int(limit),))]


def update_product(
    product_id: int,
    name: str,
    unit: str,
    default_shelf_life_days: int,
    min_qty: float | None = None,
    barcode: str | None = None,
    description: str | None = None,
    default_location_id: int | None = None,
    low_stock_enabled: int | None = None,
    expiry_kind: str | None = None,
    default_freeze_shelf_days: int | None = None,
    no_freeze: int | None = None,
    category: str | None = None,
    parent_id: int | None = None,
):
    name = name.strip()
    unit = (unit or 'pièce').strip()
    try:
        default_shelf_life_days = int(default_shelf_life_days)
    except Exception:
        default_shelf_life_days = 90

    def _float_or_none(x):
        if x is None: return None
        s = str(x).strip()
        if not s: return None
        try:
            v = float(s)
            return 0.0 if v < 0 else v
        except Exception:
            return None

    min_qty = _float_or_none(min_qty)

    payload = {
        "name": name,
        "unit": unit,
        "default_shelf_life_days": default_shelf_life_days,
        "min_qty": min_qty,
        "description": (description or "").strip() or None,
        "category": (category or "").strip() or None,
    }

    if barcode is not None:
        payload["barcode"] = (barcode.strip() or None)

    try:
        payload["default_location_id"] = int(default_location_id) if default_location_id not in (None,"") else None
    except Exception:
        payload["default_location_id"] = None

    if low_stock_enabled is not None:
        payload["low_stock_enabled"] = 0 if str(low_stock_enabled).lower() in ("0","false","off","no") else 1

    if expiry_kind is not None:
        ek = (expiry_kind or "DLC").upper()
        payload["expiry_kind"] = ek if ek in ("DLC","DDM") else "DLC"

    try:
        payload["default_freeze_shelf_days"] = int(default_freeze_shelf_days) if str(default_freeze_shelf_days or "").strip() else None
    except Exception:
        payload["default_freeze_shelf_days"] = None

    if no_freeze is not None:
        payload["no_freeze"] = 1 if str(no_freeze).lower() in ("1","true","on","yes") else 0

    try:
        payload["parent_id"] = int(parent_id) if parent_id not in (None,"") else None
    except Exception:
        payload["parent_id"] = None

    sets = []
    params = []
    for k, v in payload.items():
        sets.append(f"{k}=?")
        params.append(v)
    params.append(int(product_id))

    with _conn() as c:
        c.execute(f"UPDATE products SET {', '.join(sets)} WHERE id=?", params)
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
            """INSERT INTO stock_lots(product_id,location_id,qty,frozen_on,best_before,created_on,initial_qty,status)
               VALUES(?,?,?,?,?,?,?,?)""",
            (product_id, location_id, qty, frozen_on, best_before, today, qty, 'open')
        )
        lot_id = cur.lastrowid
        c.execute(
            """INSERT INTO movements(lot_id,type,qty,ts,note)
               VALUES(?,?,?,?,?)""",
            (lot_id, 'IN', qty, today, None)
        )
        c.commit()
    return lot_id

def add_lot_purchase(
    product_id: int,
    location_id: int,
    qty_total: float,                 # quantité totale (qty * multiplier)
    frozen_on: str | None,
    best_before: str | None,
    *,
    article_name: str | None = None,  # ← “Nutella”
    brand: str | None = None,
    ean: str | None = None,
    price_total: float | None = None,
    qty_per_unit: float | None = None,
    multiplier: int | None = None,
    unit_at_purchase: str | None = None,
) -> int:
    """Insertion d’un lot depuis la page Achats, en enregistrant les méta-infos d’article."""
    with _conn() as c:
        today = _today()
        cur = c.execute(
            """
            INSERT INTO stock_lots(
              product_id, location_id, qty, frozen_on, best_before, created_on,
              article_name, brand, ean, price_total, qty_per_unit, multiplier, unit_at_purchase,
              initial_qty, status
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                int(product_id), int(location_id), float(qty_total),
                frozen_on, best_before, today,
                (article_name or None),
                (brand or None),
                (ean or None),
                (float(price_total) if price_total not in (None, "",) else None),
                (float(qty_per_unit) if qty_per_unit not in (None, "",) else None),
                (int(multiplier) if multiplier not in (None, "",) else None),
                (unit_at_purchase or None),
                float(qty_total), 'open'
            )
        )
        lot_id = cur.lastrowid

        # Mouvement IN (comme add_lot)
        c.execute(
            """INSERT INTO movements(lot_id,type,qty,ts,note)
               VALUES(?,?,?,?,?)""",
            (lot_id, 'IN', float(qty_total), today, None)
        )
        c.commit()
    return lot_id



def list_lots():
    with _conn() as c:
        # 1) Essaie avec l.name (cas où tu stockes "Nutella" dans stock_lots.name)
        q1 = """
        SELECT
            l.id,
            l.product_id,
            l.location_id,

            -- Catégorie (nom de la fiche produit)
            p.name AS product,

            -- Nom affiché prioritaire : l.name > l.article_name > p.name
            COALESCE(NULLIF(l.name, ''), NULLIF(l.article_name, ''), p.name) AS name,

            p.unit AS unit,
            COALESCE(p.barcode, '') AS barcode,
            loc.name AS location,

            l.qty,
            l.frozen_on,
            l.best_before,
            l.created_on AS created_on,

            -- Champs achat (on renvoie aussi les originaux)
            COALESCE(l.article_name, '')    AS article_name,
            COALESCE(l.brand, '')           AS brand,
            COALESCE(l.ean, '')             AS ean,
            l.price_total                   AS price_total,
            COALESCE(l.store, '')           AS store,
            l.qty_per_unit                  AS qty_per_unit,
            l.multiplier                    AS multiplier,
            COALESCE(l.unit_at_purchase,'') AS unit_at_purchase

        FROM stock_lots l
        JOIN products  p   ON p.id  = l.product_id
        JOIN locations loc ON loc.id = l.location_id
        WHERE l.status = 'open'
        ORDER BY COALESCE(l.best_before, '9999-12-31') ASC,
                 COALESCE(NULLIF(l.name, ''), NULLIF(l.article_name, ''), p.name)
        """
        try:
            return [dict(r) for r in c.execute(q1)]
        except Exception:
            # 2) Fallback si la colonne l.name n’existe pas (ancien schéma)
            q2 = """
            SELECT
                l.id,
                l.product_id,
                l.location_id,
                p.name AS product,
                COALESCE(NULLIF(l.article_name, ''), p.name) AS name,
                p.unit AS unit,
                COALESCE(p.barcode, '') AS barcode,
                loc.name AS location,
                l.qty,
                l.frozen_on,
                l.best_before,
                l.created_on AS created_on,
                COALESCE(l.article_name, '')    AS article_name,
                COALESCE(l.brand, '')           AS brand,
                COALESCE(l.ean, '')             AS ean,
                l.price_total                   AS price_total,
                COALESCE(l.store, '')           AS store,
                l.qty_per_unit                  AS qty_per_unit,
                l.multiplier                    AS multiplier,
                COALESCE(l.unit_at_purchase,'') AS unit_at_purchase
            FROM stock_lots l
            JOIN products  p   ON p.id  = l.product_id
            JOIN locations loc ON loc.id = l.location_id
            WHERE l.status = 'open'
            ORDER BY COALESCE(l.best_before, '9999-12-31') ASC,
                     COALESCE(NULLIF(l.article_name, ''), p.name)
            """
            return [dict(r) for r in c.execute(q2)]

def get_product_info(product_id: int) -> dict | None:
    """
    Retourne:
    {
      "product_id": int,
      "unit": str,
      "brand": str|None,           # si dispo sur le premier lot
      "total_qty": float,
      "lots_count": int,
      "fifo": {
        "lot_id": int|None,
        "article_name": str|None,  # <-- injecté
        "best_before": str|None,
        "location": str|None,
        "location_id": int|None
      },
      "lots": [ ... mêmes champs utiles pour le front ... ]
    }
    """
    with _conn() as c:
        # Produit (unité)
        p = c.execute("SELECT id, name, unit FROM products WHERE id=?", (int(product_id),)).fetchone()
        if not p:
            return None

        # Tous les lots 'open' de ce produit (mêmes alias que list_lots)
        rows = c.execute("""
            SELECT
              l.id               AS lot_id,
              l.qty              AS qty,
              p.unit             AS unit,
              l.best_before      AS best_before,
              loc.name           AS location,
              l.location_id      AS location_id,

              -- Champs "identité" de lot (priorité: l.name > l.article_name > p.name)
              COALESCE(NULLIF(l.name,''), NULLIF(l.article_name,''), p.name) AS article_name,

              -- Quelques métadonnées utiles
              COALESCE(l.brand,'') AS brand,
              COALESCE(l.ean,'')   AS ean,
              l.frozen_on,
              l.created_on

            FROM stock_lots l
            JOIN products  p   ON p.id  = l.product_id
            JOIN locations loc ON loc.id = l.location_id
            WHERE l.status='open' AND l.product_id=?
            ORDER BY COALESCE(l.best_before,'9999-12-31') ASC, l.id ASC
        """, (int(product_id),)).fetchall()

        lots = [dict(r) for r in rows]
        total_qty = sum(float(r["qty"] or 0) for r in rows)
        lots_count = len(lots)

        # FIFO = premier de la liste ordonnée
        fifo = None
        if lots:
            first = lots[0]
            fifo = {
                "lot_id": int(first["lot_id"]),
                "article_name": first.get("article_name"),
                "best_before": first.get("best_before"),
                "location": first.get("location"),
                "location_id": first.get("location_id"),
            }

        # Marque: on prend la 1ère non vide trouvée
        brand = None
        for r in lots:
            b = (r.get("brand") or "").strip()
            if b:
                brand = b
                break

        return {
            "product_id": int(p["id"]),
            "unit": (p["unit"] or "").strip(),
            "brand": brand,
            "total_qty": float(total_qty),
            "lots_count": lots_count,
            "fifo": fifo,
            "lots": lots,
        }


def consume_lot(lot_id: int, qty: float, reason: str | None = None):
    with _conn() as c:
        row = c.execute("SELECT qty, price_total, qty_per_unit, multiplier FROM stock_lots WHERE id=?", (lot_id,)).fetchone()
        if not row:
            return
        old_qty = float(row["qty"])
        qty = float(qty)
        new_qty = old_qty - qty

        # coût alloué (si prix dispo)
        price_alloc = None
        try:
            if row["price_total"] and row["qty_per_unit"] and row["multiplier"]:
                total_initial = float(row["qty_per_unit"]) * float(row["multiplier"])
                if total_initial > 0:
                    price_alloc = float(row["price_total"]) * (min(qty, old_qty) / total_initial)
        except Exception:
            price_alloc = None

        if new_qty <= 0:
            # Clôture du lot (soft delete)
            c.execute(
                "UPDATE stock_lots SET qty=0, status='empty', ended_on=DATE('now') WHERE id=?",
                (lot_id,)
            )
            c.execute(
                """INSERT INTO movements(lot_id,type,qty,ts,note,reason_code,price_allocated)
                   VALUES(?,?,?,?,?,?,?)""",
                (lot_id, 'OUT', old_qty, datetime.date.today().isoformat(),
                 'lot terminé', reason, price_alloc)
            )
        else:
            c.execute("UPDATE stock_lots SET qty=? WHERE id=?", (new_qty, lot_id))
            c.execute(
                """INSERT INTO movements(lot_id,type,qty,ts,note,reason_code,price_allocated)
                   VALUES(?,?,?,?,?,?,?)""",
                (lot_id, 'OUT', qty, datetime.date.today().isoformat(),
                 None, reason, price_alloc)
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

def list_product_insights():
    """
    { product_id: {
        'last_in': 'YYYY-MM-DD'|None,
        'last_out': 'YYYY-MM-DD'|None,
        'avg_shelf_days': float|None,
        'expired_rate': float|None  # 0..100
    } }
    """
    with _conn() as c:
        q = """
        SELECT
          p.id AS product_id,
          (SELECT MAX(m.ts)
             FROM movements m
             JOIN stock_lots l ON l.id = m.lot_id
            WHERE l.product_id = p.id AND m.type='IN')  AS last_in,
          (SELECT MAX(m.ts)
             FROM movements m
             JOIN stock_lots l ON l.id = m.lot_id
            WHERE l.product_id = p.id AND m.type='OUT') AS last_out,
          (SELECT AVG(julianday(l.best_before) - julianday(l.created_on))
             FROM stock_lots l
            WHERE l.product_id = p.id
              AND l.best_before IS NOT NULL
              AND l.created_on  IS NOT NULL)            AS avg_shelf_days,
          (SELECT CASE WHEN COUNT(*)=0 THEN NULL
                       ELSE 100.0 * SUM(CASE WHEN l.best_before IS NOT NULL AND l.best_before < DATE('now') THEN 1 ELSE 0 END) / COUNT(*)
                  END
             FROM stock_lots l
            WHERE l.product_id = p.id)                  AS expired_rate
        FROM products p
        """
        rows = c.execute(q).fetchall()
        out = {}
        for r in rows:
            out[int(r["product_id"])] = {
                "last_in": r["last_in"],
                "last_out": r["last_out"],
                "avg_shelf_days": float(r["avg_shelf_days"]) if r["avg_shelf_days"] is not None else None,
                "expired_rate": float(r["expired_rate"]) if r["expired_rate"] is not None else None,
            }
        return out

# APRÈS — À AJOUTER dans db.py
def list_price_history_for_product(product_id: int, limit: int = 10):
    """
    Renvoie les dernières lignes de prix pour un produit à partir des lots saisis.
    Chaque ligne : {date, price, qty, unit, source}
    """
    with _conn() as c:
        rows = c.execute(
            """
            SELECT
              COALESCE(created_on, date('now')) AS date,
              price_total AS price,
              qty_per_unit AS qty,
              unit_at_purchase AS unit,
              store AS source
            FROM stock_lots
            WHERE product_id = ? AND price_total IS NOT NULL
            ORDER BY COALESCE(created_on, '0000-00-00') DESC
            LIMIT ?
            """,
            (int(product_id), int(limit))
        ).fetchall()
        return [dict(r) for r in rows]

def current_stock_value_by_product():
    """
    Retourne un dict {product_id: valeur_en_euros_du_stock_courant}.
    On calcule la valeur restante par lot :
      price_total * (qty_restante / (qty_per_unit * multiplier))
    On ignore les lots sans prix/quantité valides.
    """
    with _conn() as c:
        rows = c.execute("""
            SELECT
              l.product_id AS product_id,
              SUM(
                CASE
                  WHEN l.price_total IS NULL
                    OR l.qty_per_unit IS NULL
                    OR l.multiplier IS NULL
                    OR (l.qty_per_unit * l.multiplier) <= 0
                  THEN NULL
                  ELSE l.price_total * (l.qty / (l.qty_per_unit * l.multiplier))
                END
              ) AS value
            FROM stock_lots l
            WHERE l.qty > 0 AND l.status='open'
            GROUP BY l.product_id
        """).fetchall()
        out = {}
        for r in rows:
            v = r["value"]
            out[int(r["product_id"])] = float(v) if v is not None else 0.0
        return out
