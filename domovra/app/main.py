import os, logging, sqlite3, time, json
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles  # ← NEW
from jinja2 import Environment, FileSystemLoader, select_autoescape
from urllib.parse import urlencode

from db import (
    init_db,
    # Locations
    add_location, list_locations, update_location, delete_location, move_lots_from_location,
    # Products
    add_product, list_products, update_product, delete_product,
    list_products_with_stats, list_low_stock_products,
    # Lots
    add_lot, list_lots, update_lot, delete_lot, consume_lot,
    # Helper
    status_for
)

# ===== Settings store (fallback si absent) =====
try:
    from settings_store import load_settings, save_settings  # settings_store.py à côté de main.py
except Exception:
    def load_settings():
        return {
            "theme":"auto","table_mode":"scroll","sidebar_compact":False,
            "default_shelf_days":90,
            "toast_duration":3000,"toast_ok":"#4caf50","toast_warn":"#ffb300","toast_error":"#ef5350"
        }
    def save_settings(new_values: dict):
        cur = load_settings(); cur.update(new_values or {}); return cur

# ---------------- Logging global (console + /data/domovra.log)
def setup_logging():
    root = logging.getLogger()
    if root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s")

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    try:
        os.makedirs("/data", exist_ok=True)
        fh = RotatingFileHandler("/data/domovra.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:
        logging.getLogger("domovra").warning("Impossible d'ouvrir /data/domovra.log: %s", e)

setup_logging()
logger = logging.getLogger("domovra")

WARNING_DAYS  = int(os.environ.get("WARNING_DAYS",  "30"))
CRITICAL_DAYS = int(os.environ.get("CRITICAL_DAYS", "14"))
DB_PATH       = os.environ.get("DB_PATH", "/data/domovra.sqlite3")

app = FastAPI()

# === NEW: Static files mount (robuste avec chemin absolu) ===
from fastapi.staticfiles import StaticFiles

# --- Static files : dossier sibling de app/ ---
HERE = os.path.dirname(__file__)                              # …/domovra/app
ROOT = os.path.abspath(os.path.join(HERE, ".."))              # …/domovra
STATIC_DIR = os.path.join(ROOT, "static")                     # …/domovra/static

# sécurité : crée le dossier au besoin (évite le crash au boot)
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
logger.info("Static mounted at %s", STATIC_DIR)

# ============================================================

templates = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape()
)

# -------- Filtre pluralisation FR --------
def pluralize_fr(unit: str, qty) -> str:
    """Pluralise une unité française selon la quantité.
    - Singulier pour 1 / 1.0
    - Invariants: kg, g, L, ml, etc.
    - Irréguliers courants: pièce→pièces, sachet→sachets, œuf→œufs, boîte→boîtes, etc.
    - Sinon: ajout de 's', et quelques règles simples ('al'→'aux', 'eau'→'eaux').
    """
    try:
        q = float(qty)
    except Exception:
        q = qty
    try:
        is_one = abs(float(q) - 1.0) < 1e-9
    except Exception:
        is_one = (q == 1)

    if not unit:
        return unit
    u = str(unit)

    if is_one:
        return u

    invariants = { "kg","g","mg","l","L","ml","cl","m","cm","mm","%", "°C", "°F" }
    if u in invariants:
        return u

    irregulars = {
        "pièce": "pièces",
        "piece": "pieces",
        "sachet": "sachets",
        "boîte": "boîtes",
        "boite": "boites",
        "bouteille": "bouteilles",
        "canette": "canettes",
        "paquet": "paquets",
        "tranche": "tranches",
        "gousse": "gousses",
        "pot": "pots",
        "brique": "briques",
        "barquette": "barquettes",
        "œuf": "œufs",
        "oeuf": "oeufs",
        "unité": "unités",
        "unite": "unites",
        "pack": "packs",
        "lot": "lots",
        "bocal": "bocaux",
        "journal": "journaux"
    }
    # déjà au pluriel / finissant par s/x
    if u in irregulars.values() or u.endswith(("s","x")):
        return u
    if u in irregulars:
        return irregulars[u]
    if u.endswith("al"):
        return u[:-2] + "aux"
    if u.endswith("eau"):
        return u + "x"
    return u + "s"

templates.filters["pluralize_fr"] = pluralize_fr

# -------- Helpers
def nocache_html(html: str) -> Response:
    return HTMLResponse(html, headers={
        "Cache-Control":"no-store, no-cache, must-revalidate, max-age=0",
        "Pragma":"no-cache","Expires":"0"
    })

def render(name: str, **ctx):
    if "SETTINGS" not in ctx:
        ctx["SETTINGS"] = load_settings()
    tpl = templates.get_template(name)
    return nocache_html(tpl.render(**ctx))

def ingress_base(request: Request) -> str:
    base = request.headers.get("X-Ingress-Path") or "/"
    if not base.endswith("/"): base += "/"
    return base

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

# ---------------- Journal (events)
def _ensure_events_table():
    with _conn() as c:
        c.execute("""
          CREATE TABLE IF NOT EXISTS events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            kind       TEXT NOT NULL,
            details    TEXT
          )
        """)
        c.commit()

def log_event(kind: str, details: dict):
    created_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(details or {}, ensure_ascii=False)
    with _conn() as c:
        c.execute("INSERT INTO events(created_at,kind,details) VALUES (?,?,?)",
                  (created_at, kind, payload))
        c.commit()

def list_events(limit: int = 200):
    with _conn() as c:
        rows = c.execute("SELECT id, created_at, kind, details FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        items = []
        for r in rows:
            try:
                det = json.loads(r["details"] or "{}")
            except Exception:
                det = {}
            items.append({"id": r["id"], "created_at": r["created_at"], "kind": r["kind"], "details": det})
        return items

def get_low_stock_products(limit: int = 8):
    """Retourne les produits dont le stock total <= min_qty (et min_qty > 0), triés par criticité."""
    dflt = 1
    try:
        dflt = int(load_settings().get("low_stock_default", 1))
    except Exception:
        dflt = 1

    with _conn() as c:
        try:
            # Chemin « normal » : il existe une colonne p.min_qty
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
            # Fallback si la colonne min_qty n’existe pas encore : on applique seulement le seuil global
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


# ---------------- Lifecycle
@app.on_event("startup")
def _startup():
    logger.info("Domovra starting. DB_PATH=%s", DB_PATH)
    logger.info("WARNING_DAYS=%s CRITICAL_DAYS=%s", WARNING_DAYS, CRITICAL_DAYS)
    init_db()
    _ensure_events_table()
    try:
        current = load_settings()
        logger.info("Settings au démarrage: %s", current)
    except Exception as e:
        logger.exception("Erreur lecture settings au démarrage: %s", e)

@app.get("/ping", response_class=PlainTextResponse)
def ping(): return "ok"

# ---------------- Pages
@app.get("/", response_class=HTMLResponse)
@app.get("//", response_class=HTMLResponse)
def index(request: Request):
    base = ingress_base(request)
    logger.info("GET /  (BASE=%s UA=%s)", base, request.headers.get("user-agent", "-"))

    locations = list_locations()
    products  = list_products()
    lots      = list_lots()
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)

    low_products = get_low_stock_products(limit=8)

    return render("index.html",
                  BASE=base,
                  page="home",
                  request=request,
                  locations=locations,
                  products=products,
                  lots=lots,
                  low_products=low_products,   # ← *** important ***
                  WARNING_DAYS=WARNING_DAYS,
                  CRITICAL_DAYS=CRITICAL_DAYS)


@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request):
    base = ingress_base(request)
    logger.info("GET /products (BASE=%s)", base)
    items = list_products_with_stats()
    return render("products.html",
                  BASE=base,
                  page="products",
                  request=request,
                  items=items)

@app.get("/locations", response_class=HTMLResponse)
def locations_page(request: Request):
    base = ingress_base(request)
    logger.info("GET /locations (BASE=%s)", base)
    items = list_locations()

    # Comptages agrégés (total / soon / urgent)
    counts_total: dict[int,int] = {}
    counts_soon:  dict[int,int] = {}
    counts_urg:   dict[int,int] = {}
    for l in list_lots():
        st = status_for(l.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
        lid = int(l["location_id"])
        counts_total[lid] = counts_total.get(lid, 0) + 1
        if st == "yellow":
            counts_soon[lid] = counts_soon.get(lid, 0) + 1
        elif st == "red":
            counts_urg[lid] = counts_urg.get(lid, 0) + 1

    for it in items:
        lid = int(it["id"])
        it["lot_count"]   = int(counts_total.get(lid, 0))
        it["soon_count"]  = int(counts_soon.get(lid, 0))
        it["urgent_count"]= int(counts_urg.get(lid, 0))

    return render("locations.html",
                  BASE=base,
                  page="locations",
                  request=request,
                  items=items)

@app.get("/lots", response_class=HTMLResponse)
def lots_page(
    request: Request,
    product: str = Query("", alias="product"),
    location: str = Query("", alias="location"),
    status: str = Query("", alias="status"),
):
    base = ingress_base(request)
    logger.info("GET /lots (BASE=%s product=%s location=%s status=%s)", base, product, location, status)

    items = list_lots()
    for it in items:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)

    # Filtres
    if product:
        needle = product.casefold()
        items = [i for i in items if needle in (i.get("product", "").casefold())]
    if location:
        items = [i for i in items if i.get("location") == location]
    if status:
        items = [i for i in items if i.get("status") == status]

    locations = list_locations()

    # IMPORTANT : on passe aussi la liste des produits pour l'autocomplete
    return render(
        "lots.html",
        BASE=base,
        page="lots",
        request=request,
        items=items,
        locations=locations,
        products=list_products(),  # ← pour l'autocomplete
    )

# --------- Journal page
@app.get("/journal", response_class=HTMLResponse)
def journal_page(request: Request, limit: int = Query(200, ge=1, le=1000)):
    base = ingress_base(request)
    logger.info("GET /journal (BASE=%s limit=%s)", base, limit)
    events = list_events(limit)
    return render("journal.html",
                  BASE=base,
                  page="journal",
                  request=request,
                  events=events, limit=limit)

@app.post("/journal/clear")
def journal_clear(request: Request):
    base = ingress_base(request)
    with _conn() as c:
        c.execute("DELETE FROM events")
        c.commit()
    logger.info("POST /journal/clear -> journal vidé")
    log_event("journal.clear", {"by": "ui"})
    return RedirectResponse(base + "journal?cleared=1",
                            status_code=303,
                            headers={"Cache-Control":"no-store"})

@app.get("/api/events")
def api_events(limit: int = 200):
    logger.info("GET /api/events limit=%s", limit)
    return JSONResponse(list_events(limit))

# ---------- API: lookup produit local par code-barres ----------
@app.get("/api/product/by_barcode")
def api_product_by_barcode(code: str):
    code = (code or "").strip().replace(" ", "")
    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)
    with _conn() as c:
        row = c.execute("""
            SELECT id, name, COALESCE(barcode,'') AS barcode
            FROM products
            WHERE REPLACE(COALESCE(barcode,''), ' ', '') = ?
            LIMIT 1
        """, (code,)).fetchone()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"id": row["id"], "name": row["name"], "barcode": row["barcode"]})

# ---------------- Page Paramètres
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    base = ingress_base(request)
    try:
        settings = load_settings()
        logger.info("GET /settings (BASE=%s) -> %s", base, settings)
        return render("settings.html",
                      BASE=base,
                      page="settings",
                      request=request,
                      SETTINGS=settings)
    except Exception as e:
        logger.exception("Erreur GET /settings: %s", e)
        return PlainTextResponse(f"Erreur chargement paramètres: {e}", status_code=500)

@app.post("/settings/save")
def settings_save(request: Request,
                  theme: str = Form("auto"),
                  table_mode: str = Form("scroll"),
                  sidebar_compact: str = Form(None),
                  default_shelf_days: int = Form(90),
                  toast_duration: int = Form(3000),
                  toast_ok: str = Form("#4caf50"),
                  toast_warn: str = Form("#ffb300"),
                  toast_error: str = Form("#ef5350")):
    base = ingress_base(request)
    normalized = {
        "theme": theme if theme in ("auto","light","dark") else "auto",
        "table_mode": table_mode if table_mode in ("scroll","stacked") else "scroll",
        "sidebar_compact": (sidebar_compact == "on"),
        "default_shelf_days": int(default_shelf_days or 90),
        "toast_duration": max(500, int(toast_duration or 3000)),
        "toast_ok": (toast_ok or "#4caf50").strip(),
        "toast_warn": (toast_warn or "#ffb300").strip(),
        "toast_error": (toast_error or "#ef5350").strip(),
    }
    logger.info("POST /settings/save NORMALIZED: %s", normalized)

    try:
        saved = save_settings(normalized)
        logger.info("POST /settings/save OK -> %s", saved)
        log_event("settings.update", saved)
        return RedirectResponse(base + f"settings?ok=1&_={int(time.time())}",
                                status_code=303,
                                headers={"Cache-Control":"no-store"})
    except Exception as e:
        logger.exception("POST /settings/save ERREUR: %s", e)
        log_event("settings.error", {"error": str(e), "payload": normalized})
        return RedirectResponse(base + "settings?error=1",
                                status_code=303,
                                headers={"Cache-Control":"no-store"})

# ---------------- Actions Produits
@app.post("/product/add")
def product_add(request: Request,
                name: str = Form(...),
                unit: str = Form("pièce"),
                shelf: int = Form(90),
                barcode: str = Form(""),
                min_qty: str = Form("")):
    try:
        shelf = int(shelf)
    except Exception:
        shelf = 90
    bid = (barcode or "").strip() or None
    # min_qty optionnel
    mq = None
    if isinstance(min_qty, str) and min_qty.strip():
        try:
            mq = float(min_qty)
            if mq < 0: mq = 0.0
        except Exception:
            mq = None

    pid = add_product(name, unit or "pièce", shelf, bid, mq)
    log_event("product.add", {"id": pid, "name": name, "unit": unit, "shelf": shelf, "barcode": bid, "min_qty": mq})

    base = ingress_base(request)
    referer = (request.headers.get("referer") or "").lower()
    if "/lots" in referer:
        # Si la création provient de la page Stocks, on y revient pour enchaîner l’ajout du lot
        return RedirectResponse(base + f"lots?product_created={pid}", status_code=303,
                                headers={"Cache-Control": "no-store"})

    # Comportement historique (page Produits)
    params = urlencode({"added": 1, "pid": pid})
    return RedirectResponse(base + f"products?{params}", status_code=303,
                            headers={"Cache-Control": "no-store"})

@app.post("/product/update")
def product_update(request: Request,
                   product_id: int = Form(...),
                   name: str = Form(...),
                   unit: str = Form("pièce"),
                   shelf: int = Form(90),
                   barcode: str = Form(""),
                   min_qty: str = Form("")):
    try:
        shelf = int(shelf)
    except Exception:
        shelf = 90

    # Normalisation barcode & min_qty
    bid = (barcode or "").strip() or None
    mq = None
    if isinstance(min_qty, str) and min_qty.strip():
        try:
            mq = float(min_qty)
            if mq < 0: mq = 0.0
        except Exception:
            mq = None

    update_product(product_id, name, unit, shelf, mq, bid)
    log_event("product.update", {"id": product_id, "name": name, "unit": unit, "shelf": shelf, "barcode": bid, "min_qty": mq})
    return RedirectResponse(ingress_base(request)+"products", status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/product/delete")
def product_delete(request: Request, product_id: int = Form(...)):
    delete_product(product_id)
    log_event("product.delete", {"id": product_id})
    return RedirectResponse(ingress_base(request)+"products", status_code=303, headers={"Cache-Control":"no-store"})

# ---------------- Helpers incrémentation rapide
def get_step_for_unit(unit: str) -> float:
    unit = (unit or "").lower().strip()
    # Comptage
    if unit in ["pièce", "piece", "tranche", "paquet", "boîte", "boite",
                "bocal", "bouteille", "sachet", "lot", "barquette", "rouleau", "dosette"]:
        return 1.0
    # Poids
    if unit == "g":  # clic = 50 g
        return 50.0
    if unit == "kg":  # clic = 0,1 kg = 100 g
        return 0.1
    # Volume
    if unit == "ml":  # clic = 50 ml
        return 50.0
    if unit == "l":   # clic = 0,1 L = 100 ml
        return 0.1
    # fallback
    return 1.0

@app.post("/product/adjust")
def product_adjust(request: Request, product_id: int = Form(...), delta: int = Form(...)):
    """
    Ajuste rapidement le stock d'un produit :
    - delta = +1 → ajoute +step (selon l'unité)
    - delta = -1 → retire -step (consommation FIFO par DLC)
    """
    # 1) Retrouver le produit et son unité
    prods = {p["id"]: p for p in list_products()}
    prod = prods.get(int(product_id))
    if not prod:
        return RedirectResponse(ingress_base(request) + "products?error=noprod", status_code=303)

    step = get_step_for_unit(prod.get("unit"))
    qty = step * int(delta)

    if qty > 0:
        # 2) Ajouter un lot "rapide" dans un emplacement (ou en créer un si aucun)
        locs = list_locations()
        if locs:
            loc_id = int(locs[0]["id"])
        else:
            # crée un emplacement par défaut si aucun n'existe (robuste)
            loc_id = int(add_location("Général"))
        add_lot(product_id, loc_id, qty, None, None)
        log_event("product.adjust", {"id": product_id, "delta": qty, "action": "add"})
    else:
        # 3) Consommer en FIFO par date (list_lots() est trié par best_before puis nom)
        remaining = abs(qty)
        for lot in list_lots():
            if lot["product_id"] != product_id:
                continue
            if remaining <= 0:
                break
            consume = min(remaining, float(lot["qty"]))
            consume_lot(int(lot["id"]), consume)
            remaining -= consume
        log_event("product.adjust", {"id": product_id, "delta": qty, "action": "consume"})

    return RedirectResponse(ingress_base(request) + "products", status_code=303)

    

# ---------------- Actions Emplacements
@app.post("/location/add")
def location_add(request: Request, name: str = Form(...)):
    base = ingress_base(request)
    nm = (name or "").strip()
    existing = [l["name"].strip().casefold() for l in list_locations()]
    if nm.casefold() in existing:
        log_event("location.duplicate", {"name": nm})
        params = urlencode({"duplicate": 1, "name": nm})
        return RedirectResponse(base + f"locations?{params}", status_code=303, headers={"Cache-Control":"no-store"})
    lid = add_location(nm)
    log_event("location.add", {"id": lid, "name": nm})
    params = urlencode({"added": 1, "name": nm})
    return RedirectResponse(base + f"locations?{params}", status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/location/update")
def location_update(request: Request, location_id: int = Form(...), name: str = Form(...)):
    base = ingress_base(request)
    nm = (name or "").strip()
    update_location(location_id, nm)
    log_event("location.update", {"id": location_id, "name": nm})
    params = urlencode({"updated": 1, "name": nm})
    return RedirectResponse(base + f"locations?{params}", status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/location/delete")
def location_delete(request: Request, location_id: int = Form(...), move_to: str = Form("")):
    base = ingress_base(request)
    # Nom avant suppression
    with _conn() as c:
        row = c.execute("SELECT name FROM locations WHERE id=?", (location_id,)).fetchone()
        nm = row["name"] if row else ""
    # Déplacement éventuel des lots
    move_to_id = (move_to or "").strip()
    if move_to_id:
        try:
            move_lots_from_location(int(location_id), int(move_to_id))
            log_event("location.move_lots", {"from": int(location_id), "to": int(move_to_id)})
        except Exception as e:
            logger.exception("move_lots_from_location error: %s", e)
    # Suppression
    delete_location(location_id)
    log_event("location.delete", {"id": location_id, "name": nm, "moved_to": move_to_id or None})
    params = urlencode({"deleted": 1})
    return RedirectResponse(base + f"locations?{params}", status_code=303, headers={"Cache-Control":"no-store"})

# ---------------- Actions Lots
@app.post("/lot/add")
def lot_add_action(request: Request,
                   product_id: int = Form(...),
                   location_id: int = Form(...),
                   qty: float = Form(...),
                   frozen_on: str = Form(""),
                   best_before: str = Form("")):
    add_lot(product_id, location_id, float(qty), frozen_on or None, best_before or None)
    log_event("lot.add", {
        "product_id": product_id,
        "location_id": location_id,
        "qty": float(qty),
        "frozen_on": frozen_on or None,
        "best_before": best_before or None
    })
    base = ingress_base(request)
    return RedirectResponse(base + "lots?added=1", status_code=303,
                            headers={"Cache-Control": "no-store"})

@app.post("/lot/update")
def lot_update_action(request: Request,
                      lot_id: int = Form(...),
                      qty: float = Form(...),
                      location_id: int = Form(...),
                      frozen_on: str = Form(""),
                      best_before: str = Form("")):
    try:
        q = float(qty)
    except Exception:
        q = 0.0
    update_lot(lot_id, q, int(location_id), frozen_on or None, best_before or None)
    log_event("lot.update", {
        "lot_id": lot_id,
        "qty": q,
        "location_id": int(location_id),
        "frozen_on": frozen_on or None,
        "best_before": best_before or None
    })
    base = ingress_base(request)
    return RedirectResponse(base + "lots?updated=1", status_code=303,
                            headers={"Cache-Control": "no-store"})

@app.post("/lot/consume")
def lot_consume_action(request: Request, lot_id: int = Form(...), qty: float = Form(...)):
    q = float(qty)
    consume_lot(lot_id, q)
    log_event("lot.consume", {"lot_id": lot_id, "qty": q})
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/lot/delete")
def lot_delete_action(request: Request, lot_id: int = Form(...)):
    delete_lot(lot_id)
    log_event("lot.delete", {"lot_id": lot_id})
    base = ingress_base(request)
    return RedirectResponse(base + "lots?deleted=1", status_code=303,
                            headers={"Cache-Control": "no-store"})

# ---------------- Page Support (Ko-fi)
@app.get("/support", response_class=HTMLResponse)
def support_page(request: Request):
    base = ingress_base(request)
    logger.info("GET /support (BASE=%s)", base)
    return render("support.html",
                  BASE=base,
                  page="support",
                  request=request)

# ---------------- Fallback
@app.get("/{path:path}", include_in_schema=False)
def fallback(request: Request, path: str):
    base = ingress_base(request)
    logger.info("Fallback -> redirect %s", base)
    return RedirectResponse(base, status_code=303, headers={"Cache-Control":"no-store"})

# --------- util pour produits avec stats (fallback)
def get_products_with_stats():
    try:
        from db import list_products_with_stats  # type: ignore
        return list_products_with_stats()
    except Exception:
        q = """
        SELECT p.id, p.name, p.unit, p.default_shelf_life_days,
               COALESCE(SUM(l.qty),0) AS qty_total,
               COUNT(l.id) AS lots_count
        FROM products p
        LEFT JOIN stock_lots l ON l.product_id = p.id
        GROUP BY p.id ORDER BY p.name
        """
        with _conn() as c:
            return [dict(r) for r in c.execute(q)]
