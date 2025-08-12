import os, logging, sqlite3, time
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from db import (
    init_db,
    # Locations
    add_location, list_locations, update_location, delete_location,
    # Products
    add_product, list_products, update_product, delete_product,
    # Lots
    add_lot, list_lots, update_lot, delete_lot, consume_lot,
    # Helper
    status_for
)

# Certains builds anciens n'ont pas list_products_with_stats -> fallback
_DB_HAS_STATS = True
try:
    from db import list_products_with_stats  # type: ignore
except Exception:
    _DB_HAS_STATS = False

# ===== import CORRECT du store =====
from app.settings_store import load_settings, save_settings  # <-- IMPORTANT

logger = logging.getLogger("domovra")
logging.basicConfig(level=logging.INFO)

WARNING_DAYS  = int(os.environ.get("WARNING_DAYS",  "30"))
CRITICAL_DAYS = int(os.environ.get("CRITICAL_DAYS", "14"))
DB_PATH       = os.environ.get("DB_PATH", "/data/domovra.sqlite3")

app = FastAPI()

templates = Environment(
    loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "app", "templates")),
    autoescape=select_autoescape()
)

def nocache_html(html: str) -> Response:
    return HTMLResponse(html, headers={
        "Cache-Control":"no-store, no-cache, must-revalidate, max-age=0",
        "Pragma":"no-cache","Expires":"0"
    })

def render(name: str, **ctx):
    # Injecte les SETTINGS automatiquement dans TOUS les rendus
    if "SETTINGS" not in ctx:
        ctx["SETTINGS"] = load_settings()
    tpl = templates.get_template(name)
    return nocache_html(tpl.render(**ctx))

def ingress_base(request: Request) -> str:
    base = request.headers.get("X-Ingress-Path") or "/"
    if not base.endswith("/"): base += "/"
    return base

def _conn():
    c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row; return c

def _list_products_with_stats_fallback():
    q = """
    SELECT p.id, p.name, p.unit, p.default_shelf_life_days,
           COALESCE(SUM(l.qty),0) AS qty_total,
           COUNT(l.id) AS lots_count
    FROM products p
    LEFT JOIN stock_lots l ON l.product_id = p.id
    GROUP BY p.id
    ORDER BY p.name
    """
    with _conn() as c:
        return [dict(r) for r in c.execute(q)]

def get_products_with_stats():
    if _DB_HAS_STATS:
        try:
            return list_products_with_stats()  # type: ignore
        except Exception:
            return _list_products_with_stats_fallback()
    return _list_products_with_stats_fallback()

# ---------------- Lifecycle
@app.on_event("startup")
def _startup():
    logger.info("Domovra starting. DB_PATH=%s", DB_PATH)
    logger.info("WARNING_DAYS=%s CRITICAL_DAYS=%s", WARNING_DAYS, CRITICAL_DAYS)
    init_db()

@app.get("/ping", response_class=PlainTextResponse)
def ping(): return "ok"

# ---------------- Pages
@app.get("/", response_class=HTMLResponse)
@app.get("//", response_class=HTMLResponse)  # Ingress parfois envoie "//"
def index(request: Request):
    locations = list_locations()
    products  = list_products()
    lots      = list_lots()
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
    return render("index.html",
                  BASE=ingress_base(request),
                  page="home",
                  request=request,
                  locations=locations, products=products, lots=lots,
                  WARNING_DAYS=WARNING_DAYS, CRITICAL_DAYS=CRITICAL_DAYS)

@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request):
    items = get_products_with_stats()
    return render("products.html",
                  BASE=ingress_base(request),
                  page="products",
                  request=request,
                  items=items)

@app.get("/locations", response_class=HTMLResponse)
def locations_page(request: Request):
    items = list_locations()
    return render("locations.html",
                  BASE=ingress_base(request),
                  page="locations",
                  request=request,
                  items=items)

@app.get("/lots", response_class=HTMLResponse)
def lots_page(request: Request,
              product: str = Query("", alias="product"),
              location: str = Query("", alias="location"),
              status:  str = Query("", alias="status")):
    items = list_lots()
    for it in items:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)

    if product:
        needle = product.casefold()
        items = [i for i in items if needle in (i.get("product","").casefold())]
    if location:
        items = [i for i in items if i.get("location") == location]
    if status:
        items = [i for i in items if i.get("status") == status]

    locations = list_locations()
    return render("lots.html",
                  BASE=ingress_base(request),
                  page="lots",
                  request=request,
                  items=items, locations=locations)

# ---------------- Page Paramètres
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    settings = load_settings()
    return render("settings.html",
                  BASE=ingress_base(request),
                  page="settings",
                  request=request,
                  SETTINGS=settings)

# ---------------- Sauvegarde Paramètres
@app.post("/settings/save")
def settings_save(request: Request,
                  theme: str = Form("auto"),
                  table_mode: str = Form("scroll"),
                  sidebar_compact: str = Form(None),
                  default_shelf_days: int = Form(90),
                  low_stock_default: int = Form(1)):
    new_vals = {
        "theme": theme if theme in ("auto","light","dark") else "auto",
        "table_mode": table_mode if table_mode in ("scroll","stacked") else "scroll",
        "sidebar_compact": (sidebar_compact == "on"),
        "default_shelf_days": int(default_shelf_days or 90),
        "low_stock_default": int(low_stock_default or 1),
    }
    settings = save_settings(new_vals)
    logger.info("Settings saved: %s", settings)

    # Redirige sur /settings avec cache-busting
    return RedirectResponse(ingress_base(request) + f"settings?ok=1&_={int(time.time())}",
                            status_code=303,
                            headers={"Cache-Control":"no-store"})

# ---------------- API debug (pour vérifier que ça marche)
@app.get("/api/settings")
def api_settings(): return JSONResponse(load_settings())

@app.get("/api/locations")
def api_locations(): return JSONResponse(list_locations())

@app.get("/api/products")
def api_products(): return JSONResponse(list_products())

@app.get("/api/lots")
def api_lots(): return JSONResponse(list_lots())

# ---------------- Fallback
@app.get("/{path:path}", include_in_schema=False)
def fallback(request: Request, path: str):
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control":"no-store"})
