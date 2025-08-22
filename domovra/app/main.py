import os, logging, sqlite3, time, json, hashlib, shutil
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from urllib.parse import urlencode
from config import WARNING_DAYS, CRITICAL_DAYS, DB_PATH
from utils.http import nocache_html, render as _render_with_env, ingress_base
from utils.jinja import build_jinja_env
from utils.assets import ensure_hashed_asset
from services.events import _ensure_events_table, log_event, list_events
from routes.home import router as home_router



from db import (
    init_db,
    # Locations
    add_location, list_locations, update_location, delete_location, move_lots_from_location,
    # Products
    add_product, list_products, update_product, delete_product,
    list_products_with_stats, list_low_stock_products, list_product_insights,
    # Lots
    add_lot, list_lots, update_lot, delete_lot, consume_lot,
    # Helper
    status_for
)

# ===== Settings store (fallback si absent) =====
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

app = FastAPI()

templates = build_jinja_env()

def render(name: str, **ctx):
    return _render_with_env(templates, name, **ctx)

app.state.templates = templates
app.include_router(home_router)



# === Static files : dossier à côté de main.py (Option A) ===
HERE = os.path.dirname(__file__)
STATIC_DIR = os.path.join(HERE, "static")
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ➜ NEW
css_rel = ensure_hashed_asset("static/css/domovra.css")
templates.globals["ASSET_CSS_PATH"] = css_rel

# Logs de vérification au boot
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
    logger.info("CSS file %s exists=%s size=%s", css_file, os.path.isfile(css_file), os.path.getsize(css_file) if os.path.isfile(css_file) else "N/A")
except Exception as e:
    logger.exception("Static check failed: %s", e)

# -------------------- Asset versioning automatique (hash fichier) --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _abs_path(relpath: str) -> str:
    """Relatif à la racine du projet (main.py), accepte '/static/...' ou 'static/...'"""
    p = relpath.lstrip("/\\")
    return os.path.join(BASE_DIR, p)

def _file_hash(abs_path: str) -> str:
    """MD5 court (10 chars) du contenu – change dès que le fichier change."""
    h = hashlib.md5()
    with open(abs_path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:10]

@lru_cache(maxsize=256)
def _version_for(abs_path: str, mtime: float) -> str:
    """Cache par (path, mtime). Si mtime change -> nouveau hash recalculé."""
    return _file_hash(abs_path)

def asset_ver(relpath: str) -> str:
    """Retourne une version stable (hash) pour un fichier statique."""
    abs_path = _abs_path(relpath)
    try:
        mtime = os.path.getmtime(abs_path)
    except FileNotFoundError:
        logger.warning("asset_ver: fichier introuvable: %s", abs_path)
        return "dev"
    return _version_for(abs_path, mtime)

def ensure_hashed_asset(src_rel: str) -> str:
    """
    Crée (si nécessaire) une copie /static/.../nom-<hash>.ext et retourne son chemin relatif.
    Ex: 'static/css/domovra.css' -> 'static/css/domovra-abcdef1234.css'
    """
    abs_src = _abs_path(src_rel)
    hv = asset_ver(src_rel)
    if hv == "dev":
        # Fallback: garder le nom d'origine si le fichier n'existe pas
        logger.warning("ensure_hashed_asset: fallback dev for %s", src_rel)
        return src_rel

    dirname, basename = os.path.split(src_rel)
    name, ext = os.path.splitext(basename)
    hashed_name = f"{name}-{hv}{ext}"
    dst_rel = os.path.join(dirname, hashed_name)
    abs_dst = _abs_path(dst_rel)

    try:
        # Copie si manquant ou si taille différente
        if (not os.path.isfile(abs_dst)) or (os.path.getsize(abs_dst) != os.path.getsize(abs_src)):
            os.makedirs(os.path.dirname(abs_dst), exist_ok=True)
            shutil.copy2(abs_src, abs_dst)
            logger.info("Hashed asset written: %s", abs_dst)
    except Exception as e:
        logger.exception("ensure_hashed_asset error for %s -> %s: %s", abs_src, abs_dst, e)
        return src_rel

    # Nettoyage des anciennes versions
    try:
        abs_dir = _abs_path(dirname)
        for fname in os.listdir(abs_dir):
            if fname.startswith(name + "-") and fname.endswith(ext) and fname != hashed_name:
                try:
                    os.remove(os.path.join(abs_dir, fname))
                except Exception:
                    pass
    except Exception:
        pass

    return dst_rel


# -------- Helpers

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

# --- Helper Achats : ajouter OU fusionner un lot existant
def add_or_merge_lot(product_id: int, location_id: int, qty_delta: float,
                     best_before: str | None, frozen_on: str | None) -> dict:
    """
    Si un lot existe avec la même 'signature' (product_id, location_id, best_before, frozen_on),
    on incrémente sa quantité. Sinon on crée un nouveau lot.
    """
    bb = best_before or None
    fr = frozen_on or None

    # Cherche un lot équivalent
    for lot in list_lots():
        if int(lot["product_id"]) != int(product_id):
            continue
        if int(lot["location_id"]) != int(location_id):
            continue
        if (lot.get("best_before") or None) == bb and (lot.get("frozen_on") or None) == fr:
            new_qty = float(lot.get("qty") or 0) + float(qty_delta or 0)
            update_lot(int(lot["id"]), new_qty, int(location_id), fr, bb)
            return {"action": "merge", "lot_id": int(lot["id"]), "new_qty": new_qty}

    # Pas trouvé -> insertion d’un nouveau lot
    lid = add_lot(int(product_id), int(location_id), float(qty_delta or 0), fr, bb)
    return {"action": "insert", "lot_id": int(lid), "new_qty": float(qty_delta or 0)}



# ---------------- Page Achats (entrées de stock)
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
    # fiche parent + emplacement
    product_id: int = Form(...),
    location_id: int = Form(...),

    # quantités / prix
    qty: float = Form(...),
    unit: str = Form("pièce"),
    multiplier: int = Form(1),
    price_total: str = Form(""),

    # identité d'article & achat
    ean: str = Form(""),
    name: str = Form(""),
    brand: str = Form(""),
    store: str = Form(""),
    note: str = Form(""),

    # conservation
    best_before: str = Form(""),
    frozen_on: str = Form(""),
):
    # --- Helpers ---
    def _price_num():
        try:
            return float((price_total or "").replace(",", "."))
        except Exception:
            return None

    # Multiplier sécurisé
    try:
        m = int(multiplier or 1)
    except Exception:
        m = 1
    if m < 1:
        m = 1

    qty_per_unit = float(qty or 0)
    qty_delta = qty_per_unit * m

    # EAN nettoyé
    ean_digits = "".join(ch for ch in (ean or "") if ch.isdigit())

    # --- Ajout ou fusion du lot ---
    res = add_or_merge_lot(
        int(product_id),
        int(location_id),
        float(qty_delta),
        best_before or None,
        frozen_on or None,
    )

    # --- Mise à jour des infos du produit si code-barres manquant ---
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

    # --- NOUVEAU : mise à jour des champs d’achat dans stock_lots ---
    try:
        lot_id = int(res["lot_id"])
        with _conn() as c:
            # Préparation des valeurs
            _name  = (name or "").strip()
            _brand = (brand or "").strip()
            _ean   = ean_digits
            _store = (store or "").strip()
            _note  = (note or "").strip()
            _price_total = _price_num()

            sets, params = [], []

            if _name:
                sets.append("name=?")
                params.append(_name)
                sets.append("article_name=?")
                params.append(_name)

            if _brand:
                sets.append("brand=?")
                params.append(_brand)

            if _ean:
                sets.append("ean=?")
                params.append(_ean)

            if _store:
                sets.append("store=?")
                params.append(_store)

            if _note:
                sets.append("note=?")
                params.append(_note)

            if _price_total is not None:
                sets.append("price_total=?")
                params.append(_price_total)

            sets.append("qty_per_unit=?")
            params.append(qty_per_unit)

            sets.append("multiplier=?")
            params.append(m)

            if unit:
                sets.append("unit_at_purchase=?")
                params.append(unit)

            if sets:
                params.append(lot_id)
                c.execute(f"UPDATE stock_lots SET {', '.join(sets)} WHERE id=?", params)
                c.commit()

    except Exception as e:
        logger.warning("achats_add_action: unable to update lot purchase fields: %s", e)

    # --- Journal ---
    log_event("achats.add", {
        "result": res["action"], "lot_id": res["lot_id"], "new_qty": res["new_qty"],
        "product_id": int(product_id), "location_id": int(location_id),
        "ean": ean_digits or None,
        "name": (name or None), "brand": (brand or None),
        "unit": (unit or None), "qty_per_unit": qty_per_unit, "multiplier": m,
        "qty_delta": qty_delta, "price_total": _price_num(),
        "store": (store or None), "note": (note or None),
        "best_before": best_before or None, "frozen_on": frozen_on or None,
    })

    # --- Redirect ---
    base = ingress_base(request)
    return RedirectResponse(base + "achats?added=1", status_code=303,
                            headers={"Cache-Control": "no-store"})


@app.on_event("startup")
def _startup():
    logger.info("Domovra starting. DB_PATH=%s", DB_PATH)
    logger.info("WARNING_DAYS=%s CRITICAL_DAYS=%s", WARNING_DAYS, CRITICAL_DAYS)

    # S'assurer que le CSS hashé existe (log utile)
try:
    hashed_rel = ensure_hashed_asset("static/css/domovra.css")
    templates.globals["ASSET_CSS_PATH"] = hashed_rel
    logger.info("CSS hashed path ready: %s", hashed_rel)
except Exception as e:
    logger.exception("ensure_hashed_asset at startup failed: %s", e)

    init_db()
    _ensure_events_table()   # <- importé depuis services.events

    try:
        current = load_settings()
        logger.info("Settings au démarrage: %s", current)
    except Exception as e:
        logger.exception("Erreur lecture settings au démarrage: %s", e)





@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request):
    base = ingress_base(request)
    logger.info("GET /products (BASE=%s)", base)

    items = list_products_with_stats()
    locations = list_locations()
    parents = list_products()
    insights = list_product_insights()

    # -> dictionnaire { id: name } utilisable dans TOUS les blocks Jinja
    loc_map = { str(loc["id"]): loc["name"] for loc in (locations or []) }

    return render(
        "products.html",
        BASE=base,
        page="products",
        request=request,
        items=items,
        locations=locations,
        parents=parents,
        insights=insights,
        loc_map=loc_map,   # <— on passe ça au template
    )



@app.get("/locations", response_class=HTMLResponse)
def locations_page(request: Request):
    base = ingress_base(request)
    logger.info("GET /locations (BASE=%s)", base)
    items = list_locations()

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

    if product:
        needle = product.casefold()
        items = [i for i in items if needle in (i.get("product", "").casefold())]
    if location:
        items = [i for i in items if i.get("location") == location]
    if status:
        items = [i for i in items if i.get("status") == status]

    locations = list_locations()

    return render(
        "lots.html",
        BASE=base,
        page="lots",
        request=request,
        items=items,
        locations=locations,
        products=list_products(),
    )

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

# --- Open Food Facts proxy (côté serveur) : /api/off?barcode=...
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
    except urllib.error.URLError as e:
        logger.warning("OFF error: %s", e)
        return JSONResponse({"ok": False, "error": "offline"}, status_code=502)
    except Exception as e:
        logger.exception("OFF parse error: %s", e)
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
        # Bonus possibles plus tard :
        # "nutriscore": p.get("nutriscore_grade"),
        # "nova": p.get("nova_group"),
        # "ecoscore": p.get("ecoscore_grade"),
        # "categories": p.get("categories"),
    })


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

@app.post("/product/add")
def product_add(
    request: Request,
    name: str = Form(...),
    unit: str = Form("pièce"),
    shelf: int = Form(90),
    # champs étendus
    description: str = Form(""),
    default_location_id: str = Form(""),
    low_stock_enabled: str = Form("1"),
    expiry_kind: str = Form("DLC"),
    default_freeze_shelf_days: str = Form(""),
    no_freeze: str = Form(""),          # checkbox
    category: str = Form(""),
    parent_id: str = Form(""),
    # compat (présents dans l’API, même si absents du formulaire)
    barcode: str = Form(""),
    min_qty: str = Form(""),
):
    try:
        shelf = int(shelf)
    except Exception:
        shelf = 90

    bid = (barcode or "").strip() or None
    mq = None
    if isinstance(min_qty, str) and min_qty.strip():
        try:
            mq = float(min_qty)
            if mq < 0: mq = 0.0
        except Exception:
            mq = None

    pid = add_product(
        name=name,
        unit=unit or "pièce",
        shelf=shelf,
        barcode=bid,
        min_qty=mq,
        description=description,
        default_location_id=default_location_id or None,
        low_stock_enabled=low_stock_enabled,
        expiry_kind=expiry_kind,
        default_freeze_shelf_days=default_freeze_shelf_days or None,
        no_freeze=(no_freeze or "0"),
        category=category,
        parent_id=parent_id or None,
    )

    log_event("product.add", {
        "id": pid, "name": name, "unit": unit, "shelf": shelf, "min_qty": mq,
        "description": description or None,
        "default_location_id": (int(default_location_id) if str(default_location_id).strip() else None),
        "low_stock_enabled": 0 if str(low_stock_enabled).lower() in ("0","false","off","no") else 1,
        "expiry_kind": (expiry_kind or "DLC").upper(),
        "default_freeze_shelf_days": default_freeze_shelf_days or None,
        "no_freeze": 1 if str(no_freeze).lower() in ("1","true","on","yes") else 0,
        "category": category or None,
        "parent_id": parent_id or None,
    })

    base = ingress_base(request)
    referer = (request.headers.get("referer") or "").lower()
    if "/lots" in referer:
        return RedirectResponse(base + f"lots?product_created={pid}", status_code=303,
                                headers={"Cache-Control": "no-store"})
    params = urlencode({"added": 1, "pid": pid})
    return RedirectResponse(base + f"products?{params}", status_code=303,
                            headers={"Cache-Control": "no-store"})

@app.post("/product/update")
def product_update(
    request: Request,
    product_id: int = Form(...),
    name: str = Form(...),
    unit: str = Form("pièce"),
    shelf: int = Form(90),
    # étendus
    description: str = Form(""),
    default_location_id: str = Form(""),
    low_stock_enabled: str = Form("1"),
    expiry_kind: str = Form("DLC"),
    default_freeze_shelf_days: str = Form(""),
    no_freeze: str = Form(""),
    category: str = Form(""),
    parent_id: str = Form(""),
    # compat
    barcode: str = Form(""),
    min_qty: str = Form(""),
):
    try:
        shelf = int(shelf)
    except Exception:
        shelf = 90

    mq = None
    if isinstance(min_qty, str) and min_qty.strip():
        try:
            mq = float(min_qty)
            if mq < 0: mq = 0.0
        except Exception:
            mq = None

    update_product(
        product_id=product_id,
        name=name,
        unit=unit,
        default_shelf_life_days=shelf,
        min_qty=mq,
        barcode=(barcode or "").strip() or None,
        description=description,
        default_location_id=default_location_id or None,
        low_stock_enabled=low_stock_enabled,
        expiry_kind=expiry_kind,
        default_freeze_shelf_days=default_freeze_shelf_days or None,
        no_freeze=(no_freeze or "0"),
        category=category,
        parent_id=parent_id or None,
    )

    log_event("product.update", {
        "id": product_id, "name": name, "unit": unit, "shelf": shelf, "min_qty": mq,
        "description": description or None,
        "default_location_id": (int(default_location_id) if str(default_location_id).strip() else None),
        "low_stock_enabled": 0 if str(low_stock_enabled).lower() in ("0","false","off","no") else 1,
        "expiry_kind": (expiry_kind or "DLC").upper(),
        "default_freeze_shelf_days": default_freeze_shelf_days or None,
        "no_freeze": 1 if str(no_freeze).lower() in ("1","true","on","yes") else 0,
        "category": category or None,
        "parent_id": parent_id or None,
    })

    return RedirectResponse(ingress_base(request)+"products", status_code=303, headers={"Cache-Control":"no-store"})


@app.post("/product/delete")
def product_delete(request: Request, product_id: int = Form(...)):
    delete_product(product_id)
    log_event("product.delete", {"id": product_id})
    return RedirectResponse(ingress_base(request)+"products", status_code=303, headers={"Cache-Control":"no-store"})

def get_step_for_unit(unit: str) -> float:
    unit = (unit or "").lower().strip()
    if unit in ["pièce", "piece", "tranche", "paquet", "boîte", "boite",
                "bocal", "bouteille", "sachet", "lot", "barquette", "rouleau", "dosette"]:
        return 1.0
    if unit == "g":
        return 50.0
    if unit == "kg":
        return 0.1
    if unit == "ml":
        return 50.0
    if unit == "l":
        return 0.1
    return 1.0

@app.post("/product/adjust")
def product_adjust(request: Request, product_id: int = Form(...), delta: int = Form(...)):
    prods = {p["id"]: p for p in list_products()}
    prod = prods.get(int(product_id))
    if not prod:
        return RedirectResponse(ingress_base(request) + "products?error=noprod", status_code=303)

    step = get_step_for_unit(prod.get("unit"))
    qty = step * int(delta)

    if qty > 0:
        locs = list_locations()
        if locs:
            loc_id = int(locs[0]["id"])
        else:
            loc_id = int(add_location("Général"))
        add_lot(product_id, loc_id, qty, None, None)
        log_event("product.adjust", {"id": product_id, "delta": qty, "action": "add"})
    else:
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

@app.post("/location/add")
def location_add(request: Request,
                 name: str = Form(...),
                 is_freezer: str | None = Form(None),
                 description: str | None = Form(None)):
    base = ingress_base(request)
    nm = (name or "").strip()

    existing = [l["name"].strip().casefold() for l in list_locations()]
    if nm.casefold() in existing:
        log_event("location.duplicate", {"name": nm})
        params = urlencode({"duplicate": 1, "name": nm})
        return RedirectResponse(base + f"locations?{params}", status_code=303, headers={"Cache-Control":"no-store"})

    freezer = 1 if is_freezer else 0
    desc = (description or "").strip() or None

    lid = add_location(nm, freezer, desc)
    log_event("location.add", {"id": lid, "name": nm, "is_freezer": freezer, "description": desc})

    params = urlencode({"added": 1, "name": nm})
    return RedirectResponse(base + f"locations?{params}", status_code=303, headers={"Cache-Control":"no-store"})


@app.post("/location/update")
def location_update(
    request: Request,
    location_id: int = Form(...),
    name: str = Form(...),
    is_freezer: str = Form(""),
    description: str = Form("")
):
    base = ingress_base(request)
    nm = (name or "").strip()
    freezer = 1 if str(is_freezer).lower() in ("1","true","on","yes") else 0
    desc = (description or "").strip()

    update_location(location_id, nm, freezer, desc)
    log_event("location.update", {"id": location_id, "name": nm, "is_freezer": freezer, "description": desc})
    params = urlencode({"updated": 1, "name": nm})
    return RedirectResponse(base + f"locations?{params}", status_code=303, headers={"Cache-Control":"no-store"})


@app.post("/location/delete")
def location_delete(request: Request, location_id: int = Form(...), move_to: str = Form("")):
    base = ingress_base(request)
    with _conn() as c:
        row = c.execute("SELECT name, COALESCE(is_freezer,0) AS is_freezer FROM locations WHERE id=?",
                        (location_id,)).fetchone()
        nm = row["name"] if row else ""
        src_is_freezer = int(row["is_freezer"] or 0) if row else 0

    move_to_id = (move_to or "").strip()
    move_invalid = False

    if move_to_id:
        try:
            with _conn() as c:
                dest = c.execute("SELECT COALESCE(is_freezer,0) AS is_freezer FROM locations WHERE id=?",
                                 (int(move_to_id),)).fetchone()
                dest_is_freezer = int(dest["is_freezer"] or 0) if dest else 0

            if src_is_freezer != dest_is_freezer:
                move_invalid = True
                logger.info("location.delete move refused: freezer mismatch src=%s dest=%s",
                            src_is_freezer, dest_is_freezer)
            else:
                move_lots_from_location(int(location_id), int(move_to_id))
                log_event("location.move_lots", {"from": int(location_id), "to": int(move_to_id)})
        except Exception as e:
            logger.exception("move_lots_from_location error: %s", e)

    delete_location(location_id)
    log_event("location.delete", {"id": location_id, "name": nm, "moved_to": move_to_id or None})

    params = {"deleted": 1}
    if move_invalid:
        params["move_invalid"] = 1
    return RedirectResponse(base + "locations?" + urlencode(params),
                            status_code=303,
                            headers={"Cache-Control":"no-store"})


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

def list_product_insights(limit: int = 8):
    # TODO: calcule “dernier achat”, “dernière utilisation”, etc.
    # Pour l’instant on renvoie une structure vide.
    return []

@app.get("/debug/db")
def debug_db():
    """Retourne toutes les tables et les 5 premières lignes de chaque table"""
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
