# domovra/app/routes/home.py
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse
from urllib.parse import urlencode

from utils.http import ingress_base, render as render_with_env
from config import START_TS, WARNING_DAYS, CRITICAL_DAYS
from db import list_locations, list_products, list_lots, status_for

router = APIRouter()

@router.get("/ping", response_class=PlainTextResponse)
def ping():
    return "ok"

@router.get("/", response_class=HTMLResponse)
@router.get("//", response_class=HTMLResponse)
def index(request: Request):
    base = ingress_base(request)

    # Calcule les données de la home (ex-logiciel de main.py)
    locations = list_locations()
    products  = list_products()
    lots      = list_lots()
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)

    # Optionnel: basiques “faible stock” si tu veux tout de suite
    low_products = []  # tu peux brancher list_low_stock_products si dispo

    # Rendu en utilisant l’env Jinja stocké dans app.state.templates
    return render_with_env(
        request.app.state.templates,
        "index.html",
        BASE=base,
        page="home",
        request=request,
        locations=locations,
        products=products,
        lots=lots,
        low_products=low_products,
        WARNING_DAYS=WARNING_DAYS,
        CRITICAL_DAYS=CRITICAL_DAYS,
    )

@router.get("/_debug/static")
def debug_static(request: Request):
    templates = request.app.state.templates
    HERE = os.path.dirname(__file__)                # .../routes
    APP_DIR = os.path.abspath(os.path.join(HERE, ".."))
    STATIC_DIR = os.path.join(APP_DIR, "static")

    css_path = os.path.join(STATIC_DIR, "css", "domovra.css")
    hashed_rel = templates.globals.get("ASSET_CSS_PATH")
    hashed_path = (os.path.join(STATIC_DIR, hashed_rel.split("static/",1)[1]) if hashed_rel else None)
    hashed_url = (str(request.url_for("static", path=hashed_rel.split("static/",1)[1])) if hashed_rel else None)

    return JSONResponse({
        "STATIC_DIR": STATIC_DIR,
        "exists": os.path.isdir(STATIC_DIR),
        "css_exists": os.path.isfile(css_path),
        "css_size": os.path.getsize(css_path) if os.path.isfile(css_path) else None,
        "ls_static": sorted(os.listdir(STATIC_DIR)) if os.path.isdir(STATIC_DIR) else [],
        "ls_css": sorted(os.listdir(os.path.join(STATIC_DIR, "css"))) if os.path.isdir(os.path.join(STATIC_DIR, "css")) else [],
        "url_css": str(request.url_for("static", path="css/domovra.css")),
        "cache_buster_boot": START_TS,
        "hashed_css_rel": hashed_rel,
        "hashed_css_exists": os.path.isfile(hashed_path) if hashed_path else False,
        "hashed_css_url": hashed_url,
    })

@router.get("/support", response_class=HTMLResponse)
def support_page(request: Request):
    base = ingress_base(request)
    return render_with_env(request.app.state.templates, "support.html",
                           BASE=base, page="support", request=request)

@router.get("/_debug/vars")
def debug_vars(request: Request):
    templates = request.app.state.templates
    HERE = os.path.dirname(__file__)
    APP_DIR = os.path.abspath(os.path.join(HERE, ".."))
    STATIC_DIR = os.path.join(APP_DIR, "static")
    return {
        "ASSET_CSS_PATH": templates.globals.get("ASSET_CSS_PATH"),
        "STATIC_DIR": STATIC_DIR,
        "ls_static": sorted(os.listdir(STATIC_DIR)) if os.path.isdir(STATIC_DIR) else [],
        "ls_css": sorted(os.listdir(os.path.join(STATIC_DIR, "css"))) if os.path.isdir(os.path.join(STATIC_DIR, "css")) else [],
    }

@router.get("/_debug/static")
def debug_static(request: Request):
    templates = request.app.state.templates
    HERE = os.path.dirname(__file__)
    APP_DIR = os.path.abspath(os.path.join(HERE, ".."))
    STATIC_DIR = os.path.join(APP_DIR, "static")
    css_path = os.path.join(STATIC_DIR, "css", "domovra.css")
    hashed_rel = templates.globals.get("ASSET_CSS_PATH")
    hashed_path = (os.path.join(STATIC_DIR, hashed_rel.split("static/",1)[1]) if hashed_rel else None)
    hashed_url = (str(request.url_for("static", path=hashed_rel.split("static/",1)[1])) if hashed_rel else None)
    return JSONResponse({
        "STATIC_DIR": STATIC_DIR,
        "exists": os.path.isdir(STATIC_DIR),
        "css_exists": os.path.isfile(css_path),
        "css_size": os.path.getsize(css_path) if os.path.isfile(css_path) else None,
        "ls_static": sorted(os.listdir(STATIC_DIR)) if os.path.isdir(STATIC_DIR) else [],
        "ls_css": sorted(os.listdir(os.path.join(STATIC_DIR, "css"))) if os.path.isdir(os.path.join(STATIC_DIR, "css")) else [],
        "url_css": str(request.url_for("static", path="css/domovra.css")),
        "hashed_css_rel": hashed_rel,
        "hashed_css_exists": os.path.isfile(hashed_path) if hashed_path else False,
        "hashed_css_url": hashed_url,
    })

# ⚠️ Pas de fallback ici ! On en remettra un plus tard côté main.py si besoin.
