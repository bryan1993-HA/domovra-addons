# domovra/app/routes/home.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse

from utils.http import ingress_base, render as render_with_env
from config import get_retention_thresholds
from db import list_locations, list_products, list_lots, status_for, get_product_info

router = APIRouter()

@router.get("/ping", response_class=PlainTextResponse)
def ping():
    return "ok"


# --- Helpers internes --------------------------------------------------------

def _to_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(str(x).replace(",", "."))
    except Exception:
        return default

def _enabled_from(raw, default_int_0_or_1: int) -> bool:
    """
    Convertit le champ low_stock_enabled (qui peut être None/'0'/'1'/bool/str) en bool.
    Si None/'' -> fallback sur default_int_0_or_1 (sécurité globale).
    """
    if raw is None or str(raw).strip() == "":
        return bool(int(default_int_0_or_1))
    s = str(raw).strip().lower()
    return s not in ("0", "false", "off", "no")

def _compute_low_products(products, lots, default_follow: int = 1):
    """
    Calcule la liste des produits en faible stock :
      - min_qty > 0
      - low_stock_enabled actif (ou fallback sur default_follow)
      - qty_total < min_qty
    """
    # Somme des quantités par produit
    totals = {}
    for l in (lots or []):
        pid = l.get("product_id")
        if not pid:
            continue
        q = _to_float(l.get("qty"), 0.0)
        totals[pid] = totals.get(pid, 0.0) + q

    low_products = []
    debug_per_product = []

    for p in (products or []):
        pid = p.get("id")
        if not pid:
            continue

        min_qty = _to_float(p.get("min_qty"), 0.0)
        qty_total = _to_float(totals.get(pid, 0.0), 0.0)
        enabled = _enabled_from(p.get("low_stock_enabled"), default_follow)

        lack = max(0.0, min_qty - qty_total)
        debug_per_product.append({
            "id": pid,
            "name": p.get("name"),
            "enabled": enabled,
            "low_stock_enabled_raw": p.get("low_stock_enabled"),
            "default_follow": default_follow,
            "min_qty": min_qty,
            "qty_total": qty_total,
            "lack": lack,
        })

        if not enabled:
            continue
        if min_qty <= 0:
            continue
        if qty_total >= min_qty:
            continue

        low_products.append({
            "id": pid,
            "name": p.get("name"),
            "unit": (p.get("unit") or "").strip(),
            "qty_total": qty_total,
            "min_qty": min_qty,
        })

    # Trie par manque décroissant
    low_products.sort(key=lambda x: (x["min_qty"] - x["qty_total"]), reverse=True)
    return totals, low_products, debug_per_product


# --- Page accueil ------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
@router.get("//", response_class=HTMLResponse)
def index(request: Request):
    base = ingress_base(request)

    locations = list_locations() or []
    products  = list_products()  or []
    lots      = list_lots()      or []

    # seuils dynamiques depuis /data/settings.json (fallback env/valeurs sûres)
    WARNING_DAYS, CRITICAL_DAYS = get_retention_thresholds()

    # statut pour le bloc "À consommer en priorité"
    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)

    # Sécurité : si une fiche n’a pas de préférence, on suit le stock (1)
    DEFAULT_LOW_STOCK = 1

    # ← calcule les totaux par produit + la liste faible stock
    totals, low_products, _ = _compute_low_products(
        products, lots, default_follow=DEFAULT_LOW_STOCK
    )

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
        totals=totals,  # ← IMPORTANT : passé au template pour le stock dans la liste
        WARNING_DAYS=WARNING_DAYS,
        CRITICAL_DAYS=CRITICAL_DAYS,
    )


# --- DEBUG JSON --------------------------------------------------------------

@router.get("/api/home-debug", response_class=JSONResponse)
def home_debug(request: Request):
    products  = list_products()  or []
    lots      = list_lots()      or []

    # seuils dynamiques pour le calcul des statuts
    WARNING_DAYS, CRITICAL_DAYS = get_retention_thresholds()

    for it in lots:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)

    # Sécurité : suivre le stock par défaut si une fiche est incomplète
    DEFAULT_LOW_STOCK = 1
    totals, low_products, dbg = _compute_low_products(products, lots, default_follow=DEFAULT_LOW_STOCK)

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
        "settings": {"low_stock_default": DEFAULT_LOW_STOCK},
        "counts": {
            "products": len(products),
            "lots": len(lots),
            "low_products": len(low_products),
        },
        "totals_by_product_id": totals,
        "low_products": low_products,
        "debug_per_product": dbg,
        "products": simple_products,
        "lots": simple_lots,
    }


# tolère aussi //api/product-info si un client externe l’envoie par erreur
@router.get("//api/product-info", response_class=JSONResponse)
@router.get("/api/product-info", response_class=JSONResponse)
def api_product_info(product_id: int):
    """
    Payload utilisé par la page d'accueil (consommation FIFO).
    Inclut fifo.article_name (fallback: l.name puis p.name).
    """
    try:
        pid = int(product_id)
    except Exception:
        return JSONResponse({"error": "bad_product_id"}, status_code=400)

    data = get_product_info(pid)
    if not data:
        return JSONResponse({"error": "not_found", "product_id": pid}, status_code=404)

    return JSONResponse(data)
