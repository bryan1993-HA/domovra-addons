import os, logging, sqlite3, time, json
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from urllib.parse import urlencode

from db import (
    init_db,
    # Locations
    add_location, list_locations, update_location, delete_location, move_lots_from_location,
    # Products
    add_product, list_products, update_product, delete_product,
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
            "default_shelf_days":90,"low_stock_default":1,
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

templates = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape()
)

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
    return render("index.html",
                  BASE=base,
                  page="home",
                  request=request,
                  locations=locations, products=products, lots=lots,
                  WARNING_DAYS=WARNING_DAYS, CRITICAL_DAYS=CRITICAL_DAYS)

@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request):
    base = ingress_base(request)
    logger.info("GET /products (BASE=%s)", base)
    items = get_products_with_stats()
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
        products=list_products(),  # ← ajouté
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
                  low_stock_default: int = Form(1),
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
        "low_stock_default": int(low_stock_default or 1),
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
                barcode: str = Form("")):
    try:
        shelf = int(shelf)
    except Exception:
        shelf = 90
    bid = barcode.strip() or None
    pid = add_product(name, unit or "pièce", shelf, bid)
    log_event("product.add", {"id": pid, "name": name, "unit": unit, "shelf": shelf, "barcode": bid})

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
                   shelf: int = Form(90)):
    try: shelf = int(shelf)
    except Exception: shelf = 90
    update_product(product_id, name, unit, shelf)
    log_event("product.update", {"id": product_id, "name": name, "unit": unit, "shelf": shelf})
    return RedirectResponse(ingress_base(request)+"products", status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/product/delete")
def product_delete(request: Request, product_id: int = Form(...)):
    delete_product(product_id)
    log_event("product.delete", {"id": product_id})
    return RedirectResponse(ingress_base(request)+"products", status_code=303, headers={"Cache-Control":"no-store"})

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
