# /opt/app/routes/products.py

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from urllib.parse import urlencode
import json

from utils.http import ingress_base, render as render_with_env
from services.events import log_event

from db import (
    list_products_with_stats, list_locations, list_products, list_product_insights,
    add_product, update_product, delete_product,
    add_lot, list_lots, consume_lot,
    list_price_history_for_product,
    current_stock_value_by_product,
)

router = APIRouter()

# -------------------------------------------------------------------
# Gestion des unités (sans migration DB)
# -------------------------------------------------------------------

_UNIT_ALIASES = {
    # volume
    "l": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l",
    "ml": "ml", "millilitre": "ml", "millilitres": "ml",
    "cl": "cl", "centilitre": "cl", "centilitres": "cl",
    # masse
    "kg": "kg", "kilogramme": "kg", "kilogrammes": "kg",
    "g": "g", "gr": "g", "gramme": "g", "grammes": "g",
    # comptage
    "piece": "pc", "pièce": "pc", "pièces": "pc", "pcs": "pc", "pc": "pc",
    "unite": "pc", "unité": "pc",
    "boite": "pc", "boîte": "pc", "bouteille": "pc", "bouteilles": "pc",
    "paquet": "pc", "sachet": "pc", "tranche": "pc", "lot": "pc",
    "barquette": "pc", "rouleau": "pc", "dosette": "pc",
}

_UNIT_FAMILY = {
    "l": "volume", "ml": "volume", "cl": "volume",
    "kg": "mass", "g": "mass",
    "pc": "count",
}

def _normalize_unit(unit: str) -> str:
    u = (unit or "").strip().lower()
    u = u.replace("gr.", "gr").replace("g.", "g").replace("ml.", "ml").replace("l.", "l")
    if u.endswith("s") and u not in ("ml", "cl", "kg"):
        u = u[:-1]
    return _UNIT_ALIASES.get(u, u) or "pc"

def _unit_family(unit: str) -> str:
    return _UNIT_FAMILY.get(_normalize_unit(unit), "count")

def _get_step_for_unit(unit: str) -> float:
    fam = _unit_family(unit)
    return 0.01 if fam in ("mass", "volume") else 1.0

def _price_label_for_unit(unit: str) -> str:
    fam = _unit_family(unit)
    if fam == "mass":
        return "€/kg"
    if fam == "volume":
        return "€/L"
    return "€/pièce"

# -------------------------------------------------------------------
# Routes Produits
# -------------------------------------------------------------------

@router.get("/products", response_class=HTMLResponse)
def products_page(request: Request):
    base = ingress_base(request)

    items = list_products_with_stats()
    locations = list_locations()
    parents = list_products()
    insights = list_product_insights()
    stock_values = current_stock_value_by_product()

    for it in items:
        pid = int(it["id"])
        hist = list_price_history_for_product(pid, limit=10) or []

        # ===== Dernier prix unitaire (robuste & aligné DB) =====
        last_unit = None
        if hist:
            # utilitaires
            def to_float(x):
                if x is None:
                    return None
                if isinstance(x, (int, float)):
                    return float(x)
                try:
                    return float(str(x).replace(",", "."))
                except Exception:
                    return None

            def _norm(u: str) -> str:
                u = (u or "").strip().lower().replace("l.", "l").replace("ml.", "ml").replace("g.", "g").replace("gr.", "g")
                if u in ("litre", "litres", "liter", "liters"):
                    return "l"
                if u in ("centilitre", "centilitres"):
                    return "cl"
                if u in ("millilitre", "millilitres", "milliliter", "milliliters"):
                    return "ml"
                if u in ("kilogramme", "kilogrammes"):
                    return "kg"
                if u in ("gramme", "grammes"):
                    return "g"
                if u in ("piece", "pièce", "pièces", "pcs", "unité", "unite", "boite", "boîte", "bouteille", "paquet", "sachet", "lot", "barquette", "rouleau", "dosette"):
                    return "pc"
                return u or "pc"

            def _to_base(q: float, u: str):
                u = _norm(u)
                if u == "g":
                    return q / 1000.0, "kg"
                if u == "kg":
                    return q, "kg"
                if u == "ml":
                    return q / 1000.0, "l"
                if u == "cl":
                    return q / 100.0, "l"
                if u == "l":
                    return q, "l"
                return q, "pc"

            # tri décroissant (date de création si dispo)
            def pick_date(r):
                return (r.get("created_on") or r.get("date") or r.get("ended_on") or "")[:19]
            hist_sorted = sorted(hist, key=pick_date, reverse=True)

            picked = None
            for r in hist_sorted:
                price_total = to_float(r.get("price_total") or r.get("price") or r.get("total_price"))

                # quantité TOTALE si dispo (prioritaire)
                qty_total_field = to_float(r.get("initial_qty") or r.get("qty_total") or r.get("qty_all"))

                # sinon : quantité PAR UNITE × N unités
                qty_per_unit = to_float(r.get("qty_per_unit") or r.get("qty_unit") or r.get("unit_qty") or r.get("size"))
                multiplier   = to_float(r.get("multiplier") or r.get("count") or r.get("units") or r.get("nb"))

                # fallback si la source ne stocke qu'une "qty" simple
                qty_simple = to_float(r.get("qty") or r.get("qty_in") or r.get("quantity"))

                hist_unit = (r.get("unit_at_purchase") or r.get("unit") or r.get("unit_in") or r.get("u_map") or it.get("unit") or "").strip()

                # 1) quantité totale prioritaire
                qty_total_raw = None
                if qty_total_field and qty_total_field > 0:
                    qty_total_raw = qty_total_field
                # 2) sinon qty_per_unit × multiplier
                elif qty_per_unit and qty_per_unit > 0:
                    qty_total_raw = qty_per_unit * (multiplier if (multiplier and multiplier > 0) else 1.0)
                # 3) sinon qty simple (rare)
                elif qty_simple and qty_simple > 0:
                    qty_total_raw = qty_simple

                if price_total and price_total > 0 and qty_total_raw and qty_total_raw > 0:
                    picked = (price_total, qty_total_raw, hist_unit)
                    break

            if picked:
                price_total, qty_total_raw, hist_unit = picked
                qty_total_base, _ = _to_base(qty_total_raw, hist_unit)
                if qty_total_base and qty_total_base > 0:
                    last_unit = price_total / qty_total_base  # €/L, €/kg ou €/pc

        it["last_price_unit"] = last_unit
        it["currency"] = "€"
        it["price_history_json"] = json.dumps(hist, ensure_ascii=False)
        it["stock_value"] = stock_values.get(pid, 0.0)
        it["price_label"] = _price_label_for_unit(it.get("unit"))

    loc_map = {str(loc["id"]): loc["name"] for loc in (locations or [])}

    return render_with_env(
        request.app.state.templates,
        "products.html",
        BASE=base,
        page="products",
        request=request,
        items=items,
        locations=locations,
        parents=parents,
        insights=insights,
        loc_map=loc_map,
    )

@router.post("/product/add")
def product_add(
    request: Request,
    name: str = Form(...),
    unit: str = Form("pièce"),
    shelf: int = Form(90),
    description: str = Form(""),
    default_location_id: str = Form(""),
    low_stock_enabled: str = Form("1"),
    expiry_kind: str = Form("DLC"),
    default_freeze_shelf_days: str = Form(""),
    no_freeze: str = Form(""),
    category: str = Form(""),
    parent_id: str = Form(""),
    barcode: str = Form(""),
    min_qty: str = Form(""),
):
    try:
        shelf = int(shelf)
    except Exception:
        shelf = 90

    bid = (barcode or "").strip() or None
    mq = None
    if isinstance(min_qty, str) and min_qty.strip():
        try:
            mq = float(min_qty)
            if mq < 0:
                mq = 0.0
        except Exception:
            mq = None

    pid = add_product(
        name=name,
        unit=unit or "pièce",
        shelf=shelf,
        barcode=bid,
        min_qty=mq,
        description=description,
        default_location_id=default_location_id or None,
        low_stock_enabled=low_stock_enabled,
        expiry_kind=expiry_kind,
        default_freeze_shelf_days=default_freeze_shelf_days or None,
        no_freeze=(no_freeze or "0"),
        category=category,
        parent_id=parent_id or None,
    )

    log_event("product.add", {
        "id": pid, "name": name, "unit": unit, "shelf": shelf, "min_qty": mq,
        "description": description or None,
        "default_location_id": (int(default_location_id) if str(default_location_id).strip() else None),
        "low_stock_enabled": 0 if str(low_stock_enabled).lower() in ("0", "false", "off", "no") else 1,
        "expiry_kind": (expiry_kind or "DLC").upper(),
        "default_freeze_shelf_days": default_freeze_shelf_days or None,
        "no_freeze": 1 if str(no_freeze).lower() in ("1", "true", "on", "yes") else 0,
        "category": category or None,
        "parent_id": parent_id or None,
    })

    base = ingress_base(request)
    referer = (request.headers.get("referer") or "").lower()
    if "/lots" in referer:
        return RedirectResponse(base + f"lots?product_created={pid}", status_code=303,
                                headers={"Cache-Control": "no-store"})
    params = urlencode({"added": 1, "pid": pid})
    return RedirectResponse(base + f"products?{params}", status_code=303,
                            headers={"Cache-Control": "no-store"})

@router.post("/product/update")
def product_update(
    request: Request,
    product_id: int = Form(...),
    name: str = Form(...),
    unit: str = Form("pièce"),
    shelf: int = Form(90),
    description: str = Form(""),
    default_location_id: str = Form(""),
    low_stock_enabled: str = Form("1"),
    expiry_kind: str = Form("DLC"),
    default_freeze_shelf_days: str = Form(""),
    no_freeze: str = Form(""),
    category: str = Form(""),
    parent_id: str = Form(""),
    barcode: str = Form(""),
    min_qty: str = Form(""),
):
    try:
        shelf = int(shelf)
    except Exception:
        shelf = 90

    mq = None
    if isinstance(min_qty, str) and min_qty.strip():
        try:
            mq = float(min_qty)
            if mq < 0:
                mq = 0.0
        except Exception:
            mq = None

    update_product(
        product_id=product_id,
        name=name,
        unit=unit,
        default_shelf_life_days=shelf,
        min_qty=mq,
        barcode=(barcode or "").strip() or None,
        description=description,
        default_location_id=default_location_id or None,
        low_stock_enabled=low_stock_enabled,
        expiry_kind=expiry_kind,
        default_freeze_shelf_days=default_freeze_shelf_days or None,
        no_freeze=(no_freeze or "0"),
        category=category,
        parent_id=parent_id or None,
    )

    log_event("product.update", {
        "id": product_id, "name": name, "unit": unit, "shelf": shelf, "min_qty": mq,
        "description": description or None,
        "default_location_id": (int(default_location_id) if str(default_location_id).strip() else None),
        "low_stock_enabled": 0 if str(low_stock_enabled).lower() in ("0", "false", "off", "no") else 1,
        "expiry_kind": (expiry_kind or "DLC").upper(),
        "default_freeze_shelf_days": default_freeze_shelf_days or None,
        "no_freeze": 1 if str(no_freeze).lower() in ("1", "true", "on", "yes") else 0,
        "category": category or None,
        "parent_id": parent_id or None,
    })

    return RedirectResponse(ingress_base(request) + "products",
                            status_code=303, headers={"Cache-Control": "no-store"})

@router.post("/product/delete")
def product_delete(request: Request, product_id: int = Form(...)):
    delete_product(product_id)
    log_event("product.delete", {"id": product_id})
    return RedirectResponse(ingress_base(request) + "products",
                            status_code=303, headers={"Cache-Control": "no-store"})

@router.post("/product/adjust")
def product_adjust(request: Request, product_id: int = Form(...), delta: int = Form(...)):
    prods = {p["id"]: p for p in list_products()}
    prod = prods.get(int(product_id))
    if not prod:
        return RedirectResponse(ingress_base(request) + "products?error=noprod", status_code=303)

    step = _get_step_for_unit(prod.get("unit"))
    qty = step * int(delta)

    if qty > 0:
        locs = list_locations()
        if locs:
            loc_id = int(locs[0]["id"])
        else:
            from db import add_location  # import local pour éviter cycle
            loc_id = int(add_location("Général"))
        add_lot(product_id, loc_id, qty, None, None)
        log_event("product.adjust", {"id": product_id, "delta": qty, "action": "add"})
    else:
        remaining = abs(qty)
        for lot in list_lots():
            if lot["product_id"] != product_id:
                continue
            if remaining <= 0:
                break
            consume = min(remaining, float(lot["qty"]))
            consume_lot(int(lot["id"]), consume)
            remaining -= consume
        log_event("product.adjust", {"id": product_id, "delta": qty, "action": "consume"})

    return RedirectResponse(ingress_base(request) + "products", status_code=303)
