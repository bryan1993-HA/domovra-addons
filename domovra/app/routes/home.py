# domovra/app/routes/home.py
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse

from utils.http import ingress_base, render as render_with_env
from config import WARNING_DAYS, CRITICAL_DAYS
from db import list_locations, list_products, list_lots, status_for

router = APIRouter()

@router.get("/ping", response_class=PlainTextResponse)
def ping():
    return "ok"

def _to_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(str(x).replace(",", "."))
    except Exception:
        return default

def _is_true(v) -> bool:
    s = str(v).strip().lower()
    return s not in ("0", "false", "off", "no", "none", "")

def _compute_low_products(products, lots):
    """
    Calcule les produits qui sont en faible stock
    - On prend en compte 'low_stock_enabled' et 'min_qty' pour chaque produit
    - On somme les quantités des lots et on les compare au min_qty
    """
    # Somme des quantités par produit
    totals = {}
    for l in lots:
        pid = l.get("product_id")
        if not pid:
            continue
        q = _to_float(l.get("qty"), 0.0)
        totals[pid] = totals.get(pid, 0.0) + q

    low_products = []
    for p in products:
        pid = p.get("id")
        if not pid:
            continue

        # Vérifie si l'alerte de faible stock est activée
        enabled = str(p.get("low_stock_enabled") or "0").lower() not in ("0", "false", "off", "no")
        min_qty = _to_float(p.get("min_qty"), 0.0)
        qty_total = _to_float(totals.get(pid, 0.0), 0.0)

        if not enabled or min_qty <= 0 or qty_total >= min_qty:
            continue

        low_products.append({
            "id": pid,
            "name": p.get("name"),
            "unit": (p.get("unit") or "").strip(),
            "qty_total": qty_total,
            "min_qty": min_qty,
        })

    # Trier par manque (min_qty - qty_total) pour avoir les produits en plus faible stock en haut
    low_products.sort(key=lambda x: (x["min_qty"] - x["qty_total"]), reverse=True)
    return totals, low_products


@router.get("/", response_class=HTMLResponse)
@router.get("//", response_class=HTMLResponse)
def index(request: Request):
    base = ingress_base(request)

    locations = list_locations() or []
    products  = list_products()  or []
    lots      = list_lots()      or []

    # Calcul du statut des lots
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)

    # Calcul des produits en faible stock
    totals, low_products = _compute_low_products(products, lots)

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


# --- DEBUG: JSON pour vérifier les données côté front ---
@router.get("/api/home-debug", response_class=JSONResponse)
def home_debug(request: Request):
    products  = list_products()  or []
    lots      = list_lots()      or []
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
    totals, low_products = _compute_low_products(products, lots)

    # on simplifie pour que ce soit lisible
    simple_products = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "unit": p.get("unit"),
            "min_qty": p.get("min_qty"),
            "low_stock_enabled": p.get("low_stock_enabled"),
        }
        for p in products
    ]
    simple_lots = [
        {
            "id": l.get("id"),
            "product_id": l.get("product_id"),
            "qty": l.get("qty"),
            "status": l.get("status"),
            "ended_on": l.get("ended_on"),
            "best_before": l.get("best_before"),
            "location_id": l.get("location_id"),
        }
        for l in lots
    ]

    return {
        "counts": {
            "products": len(products),
            "lots": len(lots),
            "low_products": len(low_products),
        },
        "totals_by_product_id": totals,
        "low_products": low_products,
        "products": simple_products,
        "lots": simple_lots,
    }
