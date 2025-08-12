import os
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from db import init_db, add_location, list_locations, add_product, list_products, add_lot, list_lots, consume_lot, status_for

WARNING_DAYS = int(os.environ.get("WARNING_DAYS","30"))
CRITICAL_DAYS = int(os.environ.get("CRITICAL_DAYS","14"))

app = FastAPI()

templates = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape()
)

@app.on_event("startup")
def _startup():
    init_db()

@app.get("/ping", response_class=PlainTextResponse)
def ping(): return "ok"

def render(name, **ctx):
    tpl = templates.get_template(name)
    return HTMLResponse(tpl.render(**ctx))

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    locations = list_locations()
    products  = list_products()
    lots      = list_lots()
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
    return render("index.html",
                  locations=locations, products=products, lots=lots,
                  WARNING_DAYS=WARNING_DAYS, CRITICAL_DAYS=CRITICAL_DAYS)

# Locations
@app.post("/location/add")
def location_add(name: str = Form(...)):
    add_location(name)
    return RedirectResponse(url="/", status_code=303)

# Products
@app.post("/product/add")
def product_add(name: str = Form(...), unit: str = Form("pièce"), shelf: int = Form(90)):
    try: shelf = int(shelf)
    except: shelf = 90
    add_product(name, unit or "pièce", shelf)
    return RedirectResponse(url="/", status_code=303)

# Lots (stock entries)
@app.post("/lot/add")
def lot_add(product_id: int = Form(...), location_id: int = Form(...),
            qty: float = Form(...), frozen_on: str = Form(""), best_before: str = Form("")):
    add_lot(product_id, location_id, float(qty), frozen_on or None, best_before or None)
    return RedirectResponse(url="/", status_code=303)

@app.post("/lot/consume")
def lot_consume(lot_id: int = Form(...), qty: float = Form(...)):
    consume_lot(lot_id, float(qty))
    return RedirectResponse(url="/", status_code=303)

# API for HA (soon/urgent)
@app.get("/api/soon")
def api_soon():
    data = []
    for it in list_lots():
        st = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
        if st in ("yellow","red"): 
            it["status"] = st
            data.append(it)
    return JSONResponse(data)

# Fallback
@app.get("/{path:path}", include_in_schema=False)
def fallback(path:str):
    return RedirectResponse("/")
