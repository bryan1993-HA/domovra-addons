import os
import logging
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from db import (
    init_db, add_location, list_locations,
    add_product, list_products, list_products_with_stats,
    add_lot, list_lots, consume_lot, status_for
)

# Logs
logger = logging.getLogger("domovra")
logging.basicConfig(level=logging.INFO)

WARNING_DAYS = int(os.environ.get("WARNING_DAYS", "30"))
CRITICAL_DAYS = int(os.environ.get("CRITICAL_DAYS", "14"))
DB_PATH = os.environ.get("DB_PATH", "/data/domovra.sqlite3")

app = FastAPI()

templates = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape()
)

@app.on_event("startup")
def _startup():
    logger.info("Domovra starting. DB_PATH=%s", DB_PATH)
    logger.info("WARNING_DAYS=%s CRITICAL_DAYS=%s", WARNING_DAYS, CRITICAL_DAYS)
    init_db()

@app.get("/ping", response_class=PlainTextResponse)
def ping():
    return "ok"

def nocache_html(html: str) -> Response:
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

def render(name: str, **ctx):
    tpl = templates.get_template(name)
    return nocache_html(tpl.render(**ctx))

def ingress_base(request: Request) -> str:
    base = request.headers.get("X-Ingress-Path") or "/"
    if not base.endswith("/"):
        base += "/"
    return base

# -------- Accueil
@app.get("/", response_class=HTMLResponse)
@app.get("//", response_class=HTMLResponse)
def index(request: Request):
    locations = list_locations()
    products  = list_products()
    lots      = list_lots()
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
    return render(
        "index.html",
        BASE=ingress_base(request),
        locations=locations,
        products=products,
        lots=lots,
        WARNING_DAYS=WARNING_DAYS,
        CRITICAL_DAYS=CRITICAL_DAYS,
        page="home"
    )

# -------- Produits
@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request):
    items = list_products_with_stats()
    return render("products.html", BASE=ingress_base(request), items=items, page="products")

# -------- Emplacements
@app.get("/locations", response_class=HTMLResponse)
def locations_page(request: Request):
    items = list_locations()
    return render("locations.html", BASE=ingress_base(request), items=items, page="locations")

# -------- Lots (tous)
@app.get("/lots", response_class=HTMLResponse)
def lots_page(request: Request):
    items = list_lots()
    for it in items:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
    return render("lots.html", BASE=ingress_base(request), items=items, page="lots")

# -------- Actions (POST) + redirections Ingress
@app.post("/location/add")
def location_add(request: Request, name: str = Form(...)):
    add_location(name)
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control": "no-store"})

@app.get("/location/add", include_in_schema=False)
def location_add_get(request: Request):
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control": "no-store"})

@app.post("/product/add")
def product_add(request: Request, name: str = Form(...), unit: str = Form("pièce"), shelf: int = Form(90)):
    try:
        shelf = int(shelf)
    except Exception:
        shelf = 90
    add_product(name, unit or "pièce", shelf)
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control": "no-store"})

@app.get("/product/add", include_in_schema=False)
def product_add_get(request: Request):
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control": "no-store"})

@app.post("/lot/add")
def lot_add(
    request: Request,
    product_id: int = Form(...),
    location_id: int = Form(...),
    qty: float = Form(...),
    frozen_on: str = Form(""),
    best_before: str = Form("")
):
    add_lot(product_id, location_id, float(qty), frozen_on or None, best_before or None)
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control": "no-store"})

@app.get("/lot/add", include_in_schema=False)
def lot_add_get(request: Request):
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control": "no-store"})

@app.post("/lot/consume")
def lot_consume(request: Request, lot_id: int = Form(...), qty: float = Form(...)):
    consume_lot(lot_id, float(qty))
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control": "no-store"})

@app.get("/lot/consume", include_in_schema=False)
def lot_consume_get(request: Request):
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control": "no-store"})

# -------- API debug
@app.get("/api/locations")
def api_locations(): return JSONResponse(list_locations())

@app.get("/api/products")
def api_products(): return JSONResponse(list_products())

@app.get("/api/lots")
def api_lots(): return JSONResponse(list_lots())

# -------- Fallback
@app.get("/{path:path}", include_in_schema=False)
def fallback(request: Request, path: str):
    return RedirectResponse(ingress_base(request), status_code=303, headers={"Cache-Control": "no-store"})
