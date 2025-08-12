import os, logging, sqlite3
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from db import (
    init_db, add_location, list_locations, update_location, delete_location,
    add_product, list_products, update_product, delete_product,
    add_lot, list_lots, update_lot, delete_lot, consume_lot, status_for
)

# list_products_with_stats peut manquer selon le build -> fallback
_DB_HAS_STATS = True
try:
    from db import list_products_with_stats  # type: ignore
except Exception:
    _DB_HAS_STATS = False

logger = logging.getLogger("domovra")
logging.basicConfig(level=logging.INFO)

WARNING_DAYS = int(os.environ.get("WARNING_DAYS", "30"))
CRITICAL_DAYS = int(os.environ.get("CRITICAL_DAYS", "14"))
DB_PATH = os.environ.get("DB_PATH", "/data/domovra.sqlite3")

app = FastAPI()
templates = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape())

def nocache_html(html: str) -> Response:
    return HTMLResponse(html, headers={
        "Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0"
    })

def render(name: str, **ctx):
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
           COALESCE(SUM(l.qty),0) AS qty_total, COUNT(l.id) AS lots_count
    FROM products p
    LEFT JOIN stock_lots l ON l.product_id = p.id
    GROUP BY p.id
    ORDER BY p.name
    """
    with _conn() as c:
        return [dict(r) for r in c.execute(q)]

def get_products_with_stats():
    if _DB_HAS_STATS:
        try: return list_products_with_stats()  # type: ignore
        except Exception: return _list_products_with_stats_fallback()
    return _list_products_with_stats_fallback()

@app.on_event("startup")
def _startup():
    logger.info("Domovra starting. DB_PATH=%s", DB_PATH)
    logger.info("WARNING_DAYS=%s CRITICAL_DAYS=%s", WARNING_DAYS, CRITICAL_DAYS)
    init_db()

@app.get("/ping", response_class=PlainTextResponse)
def ping(): return "ok"

# ---------- PAGES
@app.get("/", response_class=HTMLResponse)
@app.get("//", response_class=HTMLResponse)
def index(request: Request):
    locations = list_locations()
    products  = list_products()
    lots      = list_lots()
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
    return render("index.html", BASE=ingress_base(request), page="home",
                  locations=locations, products=products, lots=lots,
                  WARNING_DAYS=WARNING_DAYS, CRITICAL_DAYS=CRITICAL_DAYS)

@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request):
    items = get_products_with_stats()
    return render("products.html", BASE=ingress_base(request), page="products", items=items)

@app.get("/locations", response_class=HTMLResponse)
def locations_page(request: Request):
    items = list_locations()
    return render("locations.html", BASE=ingress_base(request), page="locations", items=items)

@app.get("/lots", response_class=HTMLResponse)
def lots_page(request: Request):
    items = list_lots()
    locations = list_locations()
    for it in items:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
    return render("lots.html", BASE=ingress_base(request), page="lots", items=items, locations=locations)

# ---------- ACTIONS Produits
@app.post("/product/add")
def product_add(request: Request, name: str = Form(...), unit: str = Form("pièce"), shelf: int = Form(90)):
    try: shelf = int(shelf)
    except Exception: shelf = 90
    add_product(name, unit or "pièce", shelf)
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/product/update")
def product_update(request: Request,
                   product_id: int = Form(...),
                   name: str = Form(...),
                   unit: str = Form("pièce"),
                   shelf: int = Form(90)):
    try: shelf = int(shelf)
    except Exception: shelf = 90
    update_product(product_id, name, unit, shelf)
    return RedirectResponse(ingress_base(request)+"products", status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/product/delete")
def product_delete(request: Request, product_id: int = Form(...)):
    delete_product(product_id)
    return RedirectResponse(ingress_base(request)+"products", status_code=303, headers={"Cache-Control":"no-store"})

# ---------- ACTIONS Emplacements
@app.post("/location/add")
def location_add(request: Request, name: str = Form(...)):
    add_location(name)
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/location/update")
def location_update(request: Request, location_id: int = Form(...), name: str = Form(...)):
    update_location(location_id, name)
    return RedirectResponse(ingress_base(request)+"locations", status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/location/delete")
def location_delete(request: Request, location_id: int = Form(...)):
    delete_location(location_id)
    return RedirectResponse(ingress_base(request)+"locations", status_code=303, headers={"Cache-Control":"no-store"})

# ---------- ACTIONS Lots
@app.post("/lot/add")
def lot_add(request: Request,
            product_id: int = Form(...),
            location_id: int = Form(...),
            qty: float = Form(...),
            frozen_on: str = Form(""),
            best_before: str = Form("")):
    add_lot(product_id, location_id, float(qty), frozen_on or None, best_before or None)
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/lot/update")
def lot_update(request: Request,
               lot_id: int = Form(...),
               qty: float = Form(...),
               location_id: int = Form(...),
               frozen_on: str = Form(""),
               best_before: str = Form("")):
    try: q = float(qty)
    except Exception: q = 0.0
    update_lot(lot_id, q, int(location_id), frozen_on or None, best_before or None)
    return RedirectResponse(ingress_base(request)+"lots", status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/lot/consume")
def lot_consume_action(request: Request, lot_id: int = Form(...), qty: float = Form(...)):
    consume_lot(lot_id, float(qty))
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control":"no-store"})

@app.post("/lot/delete")
def lot_delete_action(request: Request, lot_id: int = Form(...)):
    delete_lot(lot_id)
    return RedirectResponse(ingress_base(request)+"lots", status_code=303, headers={"Cache-Control":"no-store"})

# ---------- API debug
@app.get("/api/locations")
def api_locations(): return JSONResponse(list_locations())
@app.get("/api/products")
def api_products(): return JSONResponse(list_products())
@app.get("/api/lots")
def api_lots(): return JSONResponse(list_lots())

# ---------- Fallback
@app.get("/{path:path}", include_in_schema=False)
def fallback(request: Request, path: str):
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control":"no-store"})
