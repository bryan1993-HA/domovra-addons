# domovra/app/routes/home.py
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles  # (uniquement pour typer, pas utilisé ici)
from urllib.parse import urlencode

from utils.http import ingress_base, render as render_with_env
from config import START_TS

router = APIRouter()

@router.get("/ping", response_class=PlainTextResponse)
def ping():
    return "ok"

@router.get("/", response_class=HTMLResponse)
@router.get("//", response_class=HTMLResponse)
def index(request: Request):
    """
    ⚠️ ATTENTION :
    - On NE met ici que le rendu de la page (données minimales),
    - La logique métier / données complexes restent dans leurs routers/dépendances dédiés.
    """
    base = ingress_base(request)
    # Les données utilisées par index.html viennent de main.py jusqu'à la migration complète
    # (pour cette 3A on garde l'implémentation “plein pot” côté main.py, voir plus bas)
    # Ici on ne fait que “proxy” l’appel de rendu pour éviter le double code.
    return render_with_env(request.app.state.templates, "index.html", BASE=base, page="home", request=request)

@router.get("/_debug/static")
def debug_static(request: Request):
    """
    Copie du endpoint debug, mais en s’appuyant uniquement sur l'état de l'app
    (templates globals + STATIC_DIR).
    """
    templates = request.app.state.templates
    HERE = os.path.dirname(__file__)                # .../routes
    APP_DIR = os.path.abspath(os.path.join(HERE, ".."))   # .../app
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

@router.get("/{path:path}", include_in_schema=False)
def fallback(request: Request, path: str):
    base = ingress_base(request)
    return RedirectResponse(base, status_code=303, headers={"Cache-Control":"no-store"})
