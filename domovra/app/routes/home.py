# domovra/app/routes/home.py
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from utils.http import ingress_base, render as render_with_env
from config import WARNING_DAYS, CRITICAL_DAYS
from db import list_locations, list_products, list_lots, status_for

router = APIRouter()

@router.get("/ping", response_class=PlainTextResponse)
def ping():
    return "ok"

@router.get("/", response_class=HTMLResponse)
@router.get("//", response_class=HTMLResponse)
def index(request: Request):
    base = ingress_base(request)

    # Données pour la page d’accueil
    locations = list_locations()
    products  = list_products()
    lots      = list_lots()
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)

    # (option) À brancher plus tard si on veut: list_low_stock_products()
    low_products = []

    # Rendu via l'env Jinja stocké dans app.state.templates
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

# ⚠️ Pas de fallback ici. Si besoin, on en mettra un au niveau main.py.
