import os, logging, sqlite3, time, json, hashlib, shutil
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import (
    HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
)
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlencode

from config import WARNING_DAYS, CRITICAL_DAYS, DB_PATH
from utils.http import ingress_base, render as _render_with_env
from utils.jinja import build_jinja_env
from utils.assets import ensure_hashed_asset
from services.events import _ensure_events_table, log_event, list_events

# Routers “pages”
from routes.home import router as home_router
from routes.products import router as products_router
from routes.locations import router as locations_router
from routes.lots import router as lots_router

# DB: uniquement ce qui est *réellement* utilisé ici
from db import (
    init_db,
    # pages Achats
    list_products, list_locations,
    # helpers pour ajout/merge de lots
    add_lot, list_lots, update_lot,
)

# ================== Logging ==================
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

# ================== App & Templates ==================
app = FastAPI()
templates = build_jinja_env()

def render(name: str, **ctx):
    return _render_with_env(templates, name, **ctx)

app.state.templates = templates

# Valeur par défaut (filet de sécurité si hashing échoue)
templates.globals.setdefault("ASSET_CSS_PATH", "static/css/domovra.css")

# ================== Static ==================
HERE = os.path.dirname(__file__)
STATIC_DIR = os.path.join(HERE, "static")
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Calcul et injection du CSS versionné (une seule fois)
try:
    css_rel = ensure_hashed_asset("static/css/domovra.css")  # -> static/css/domovra-<hash>.css
    if not (isinstance(css_rel, str) and css_rel.startswith("static/")):
        css_rel = "static/css/domovra.css"
    templates.globals["ASSET_CSS_PATH"] = css_rel
    logger.info("ASSET_CSS_PATH set to %s", css_rel)
except Exception as e:
    logger.exception("Failed to compute ASSET_CSS_PATH: %s", e)
    # garde la valeur par défaut

# Logs de vérification au boot (utile en add-on)
try:
    logger.info("Static mounted at %s", STATIC_DIR)
    def _ls(p):
        try:
            return sorted(os.listdir(p))
        except Exception:
            return "N/A"
    logger.info("Check %s exists=%s items=%s", STATIC_DIR, os.path.isdir(STATIC_DIR), _ls(STATIC_DIR))
    css_dir = os.path.join(STATIC_DIR, "css")
    logger.info("Check %s exists=%s items=%s", css_dir, os.path.isdir(css_dir), _ls(css_dir))
    css_file = os.path.join(css_dir, "domovra.css")
    logger.info("CSS file %s exists=%s size=%s",
                css_file, os.path.isfile(css_file),
                os.path.getsize(css_file) if os.path.isfile(css_file) else "N/A")
except Exception as e:
    logger.exception("Static check failed: %s", e)

# ================== Helpers ==================
def _abs_path(relpath: str) -> str:
    p = relpath.lstrip("/\\")
    return os.path.join(HERE, p)

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

# Ajout/Fusion d’un lot existant pour /achats/add
def add_or_merge_lot(product_id: int, location_id: int, qty_delta: float,
                     best_before: str | None, frozen_on: str | None) -> dict:
    bb = best_before or None
    fr = frozen_on or None
    for lot in list_lots():
        if int(lot["product_id"]) != int(product_id):
            continue
        if int(lot["location_id"]) != int(location_id):
            continue
        if (lot.get("best_before") or None) == bb and (lot.get("frozen_on") or None) == fr:
            new_qty = float(lot.get("qty") or 0) + float(qty_delta or 0)
            update_lot(int(lot["id"]), new_qty, int(location_id), fr, bb)
            return {"action": "merge", "lot_id": int(lot["id"]), "new_qty": new_qty}
    lid = add_lot(int(product_id), int(location_id), float(qty_delta or 0), fr, bb)
    return {"action": "insert", "lot_id": int(lid), "new_qty": float(qty_delta or 0)}

# ================== Routers ==================
app.include_router(home_router)
app.include_router(products_router)
app.include_router(locations_router)
app.include_router(lots_router)

# ================== Pages / Achats ==================
@app.get("/achats", response_class=HTMLResponse)
def achats_page(request: Request):
    base = ingress_base(request)
    logger.info("GET /achats (BASE=%s)", base)
    return render(
        "achats.html",
        BASE=base,
        page="achats",
        request=request,
        products=list_products(),
        locations=list_locations(),
    )

@app.post("/achats/add")
def achats_add_action(
    request: Request,
    product_id: int = Form(...),
    location_id: int = Form(...),
    qty: float = Form(...),
    unit: str = Form("pièce"),
    multiplier: int = Form(1),
    price_total: str = Form(""),
    ean: str = Form(""),
    name: str = Form(""),
    brand: str = Form(""),
    store: str = Form(""),
    note: str = Form(""),
    best_before: str = Form(""),
    frozen_on: str = Form(""),
):
    def _price_num():
        try:
            return float((price_total or "").replace(",", "."))
        except Exception:
            return None

    try:
        m = max(1, int(multiplier or 1))
    except Exception:
        m = 1

    qty_per_unit = float(qty or 0)
    qty_delta = qty_per_unit * m
    ean_digits = "".join(ch for ch in (ean or "") if ch.isdigit())

    res = add_or_merge_lot(
        int(product_id), int(location_id), float(qty_delta),
        best_before or None, frozen_on or None,
    )

    # barcode sur le produit si manquant
    if ean_digits:
        try:
            with _conn() as c:
                row = c.execute(
                    "SELECT COALESCE(barcode,'') AS barcode FROM products WHERE id=?",
                    (int(product_id),)
                ).fetchone()
                current_bc = (row["barcode"] or "") if row else ""
                if not current_bc.strip():
                    c.execute("UPDATE products SET barcode=? WHERE id=?", (ean_digits, int(product_id)))
                    c.commit()
        except Exception as e:
            logger.warning("achats_add_action: unable to set product barcode: %s", e)

    # enrichit le lot (infos d’achat)
    try:
        lot_id = int(res["lot_id"])
        with _conn() as c:
            sets, params = [], []
            def add_set(col, val):
                if val is None: return
                v = (val if isinstance(val, (int, float)) else str(val).strip())
                if v == "": return
                sets.append(f"{col}=?"); params.append(v)

            add_set("name", name); add_set("article_name", name)
            add_set("brand", brand)
            add_set("ean", ean_digits or None)
            add_set("store", store)
            add_set("note", note)
            add_set("price_total", _price_num())
            add_set("qty_per_unit", qty_per_unit)
            add_set("multiplier", m)
            add_set("unit_at_purchase", unit or "pièce")

            if sets:
                params.append(lot_id)
                c.execute(f"UPDATE stock_lots SET {', '.join(sets)} WHERE id=?", params)
                c.commit()
    except Exception as e:
        logger.warning("achats_add_action: unable to update lot purchase fields: %s", e)

    log_event("achats.add", {
        "result": res["action"], "lot_id": res["lot_id"], "new_qty": res["new_qty"],
        "product_id": int(product_id), "location_id": int(location_id),
        "ean": ean_digits or None, "name": (name or None), "brand": (brand or None),
        "unit": (unit or None), "qty_per_unit": qty_per_unit, "multiplier": m,
        "qty_delta": qty_delta, "price_total": _price_num(),
        "store": (store or None), "note": (note or None),
        "best_before": best_before or None, "frozen_on": frozen_on or None,
    })

    base = ingress_base(request)
    return RedirectResponse(base + "achats?added=1", status_code=303,
                            headers={"Cache-Control": "no-store"})

# ================== Lifecycle ==================
@app.on_event("startup")
def _startup():
    logger.info("Domovra starting. DB_PATH=%s", DB_PATH)
    logger.info("WARNING_DAYS=%s CRITICAL_DAYS=%s", WARNING_DAYS, CRITICAL_DAYS)
    init_db()
    _ensure_events_table()
    try:
        from settings_store import load_settings  # lazy (fallback plus bas sinon)
        current = load_settings()
        logger.info("Settings au démarrage: %s", current)
    except Exception as e:
        logger.exception("Erreur lecture settings au démarrage: %s", e)

# ================== Debug ==================
@app.get("/_debug/vars")
def debug_vars():
    return {
        "ASSET_CSS_PATH": templates.globals.get("ASSET_CSS_PATH"),
        "STATIC_DIR": os.path.abspath(STATIC_DIR),
        "ls_static": sorted(os.listdir(STATIC_DIR)) if os.path.isdir(STATIC_DIR) else [],
        "ls_css": sorted(os.listdir(os.path.join(STATIC_DIR, "css"))) if os.path.isdir(os.path.join(STATIC_DIR, "css")) else [],
    }

# ================== Journal / API ==================
@app.get("/journal", response_class=HTMLResponse)
def journal_page(request: Request, limit: int = Query(200, ge=1, le=1000)):
    base = ingress_base(request)
    events = list_events(limit)
    return render("journal.html", BASE=base, page="journal", request=request, events=events, limit=limit)

@app.post("/journal/clear")
def journal_clear(request: Request):
    base = ingress_base(request)
    with _conn() as c:
        c.execute("DELETE FROM events")
        c.commit()
    log_event("journal.clear", {"by": "ui"})
    return RedirectResponse(base + "journal?cleared=1", status_code=303,
                            headers={"Cache-Control":"no-store"})

@app.get("/api/events")
def api_events(limit: int = 200):
    return JSONResponse(list_events(limit))

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

# ================== OFF proxy ==================
@app.get("/api/off")
def api_off(barcode: str):
    import urllib.request, urllib.error
    barcode = (barcode or "").strip()
    if not barcode:
        return JSONResponse({"ok": False, "error": "missing barcode"}, status_code=400)

    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Domovra/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
    except urllib.error.URLError:
        return JSONResponse({"ok": False, "error": "offline"}, status_code=502)
    except Exception:
        return JSONResponse({"ok": False, "error": "parse"}, status_code=500)

    if not isinstance(data, dict) or data.get("status") != 1:
        return JSONResponse({"ok": False, "error": "notfound"}, status_code=404)

    p = data.get("product", {}) or {}
    return JSONResponse({
        "ok": True,
        "barcode": barcode,
        "name": p.get("product_name") or "",
        "brand": p.get("brands") or "",
        "quantity": p.get("quantity") or "",
        "image": p.get("image_front_url") or p.get("image_url") or "",
    })

# ================== Settings ==================
try:
    from settings_store import load_settings, save_settings
except Exception:
    def load_settings():
        return {
            "theme":"auto","table_mode":"scroll","sidebar_compact":False,
            "default_shelf_days":90,
            "toast_duration":3000,"toast_ok":"#4caf50","toast_warn":"#ffb300","toast_error":"#ef5350"
        }
    def save_settings(new_values: dict):
        cur = load_settings(); cur.update(new_values or {}); return cur

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    base = ingress_base(request)
    try:
        settings = load_settings()
        return render("settings.html", BASE=base, page="settings", request=request, SETTINGS=settings)
    except Exception as e:
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
    try:
        saved = save_settings(normalized)
        log_event("settings.update", saved)
        return RedirectResponse(base + f"settings?ok=1&_={int(time.time())}",
                                status_code=303, headers={"Cache-Control":"no-store"})
    except Exception as e:
        log_event("settings.error", {"error": str(e), "payload": normalized})
        return RedirectResponse(base + "settings?error=1",
                                status_code=303, headers={"Cache-Control":"no-store"})

# ================== Debug DB ==================
@app.get("/debug/db")
def debug_db():
    out = []
    with _conn() as c:
        tables = [r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        for t in tables:
            rows = [dict(r) for r in c.execute(f"SELECT * FROM {t} LIMIT 5")]
            out.append({
                "table": t,
                "columns": list(rows[0].keys()) if rows else [],
                "rows": rows
            })
    return out
