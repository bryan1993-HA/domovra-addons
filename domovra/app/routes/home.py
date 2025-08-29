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

    # --- Données ---
    locations = list_locations() or []
    products  = list_products()  or []
    lots      = list_lots()      or []

    # Statut des lots (pour "À consommer en priorité")
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)

    # --- Somme des quantités par produit (à partir des lots ouverts) ---
    totals = {}
    for l in lots:
        pid = l.get("product_id")
        if not pid:
            continue
        try:
            q = float(l.get("qty") or 0)
        except Exception:
            q = 0.0
        totals[pid] = totals.get(pid, 0.0) + q

    # --- Construction de la liste faible stock ---
    low_products = []
    for p in products:
        pid = p.get("id")
        if not pid:
            continue

        # low_stock_enabled peut être '0'/'1'/None/bool
        enabled = str(p.get("low_stock_enabled") or "0").lower() not in ("0", "false", "off", "no")

        # min_qty peut être None / str / float
        try:
            min_qty = float(p.get("min_qty")) if p.get("min_qty") is not None else 0.0
        except Exception:
            min_qty = 0.0

        qty_total = float(totals.get(pid, 0.0))

        if not enabled or min_qty <= 0 or qty_total >= min_qty:
            continue

        low_products.append({
            "id": pid,
            "name": p.get("name"),
            "unit": (p.get("unit") or "").strip(),
            "qty_total": qty_total,
            "min_qty": min_qty,
        })

    # Trier par manque décroissant (optionnel)
    low_products.sort(key=lambda x: (x["min_qty"] - x["qty_total"]), reverse=True)

    # Rendu
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
