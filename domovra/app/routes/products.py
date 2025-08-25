# /opt/app/routes/products.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from urllib.parse import urlencode
import json

from utils.http import ingress_base, render as render_with_env
from services.events import log_event
import json  # >>> AJOUT si absent

from db import (
    list_products_with_stats, list_locations, list_products, list_product_insights,
    add_product, update_product, delete_product,
    add_lot, list_lots, consume_lot,
    list_price_history_for_product,
    current_stock_value_by_product,  # >>> AJOUT
)

router = APIRouter()


def _get_step_for_unit(unit: str) -> float:
    unit = (unit or "").lower().strip()
    if unit in ["pièce", "piece", "tranche", "paquet", "boîte", "boite",
                "bocal", "bouteille", "sachet", "lot", "barquette", "rouleau", "dosette"]:
        return 1.0
    if unit == "g":
        return 50.0
    if unit == "kg":
        return 0.1
    if unit == "ml":
        return 50.0
    if unit == "l":
        return 0.1
    return 1.0


@router.get("/products", response_class=HTMLResponse)
def products_page(request: Request):
    base = ingress_base(request)

    items = list_products_with_stats()
    locations = list_locations()
    parents = list_products()
    insights = list_product_insights()
    stock_values = current_stock_value_by_product()

    # Enrichir chaque produit avec last_price + historique JSON (pour la modale Voir)
    # Enrichir chaque produit avec:
    #  - last_price_unit = dernier prix *unitaire* (prix_total / quantité_achetée)
    #  - historique JSON (graph)
    #  - stock_value = somme réelle des lots restants (DB)
    for it in items:
        pid = int(it["id"])
        hist = list_price_history_for_product(pid, limit=10) or []

        # ===== Dernier prix unitaire =====
        last_unit = None
        if hist:
            r0 = hist[0]  # entrée la plus récente
            price_total = float(r0.get("price") or 0)  # "price" = prix total saisi lors de l'achat

            # On cherche d'abord une quantité totale fiable pour ce lot d'achat.
            qty_hist = r0.get("qty")
            qty_per_unit = r0.get("qty_per_unit")
            multiplier = r0.get("multiplier")

            qty_total = None
            # cas 1: l'historique fournit directement la quantité (ex: 3 L)
            if qty_hist is not None:
                try:
                    q = float(qty_hist)
                    if q > 0:
                        qty_total = q
                except Exception:
                    pass

            # cas 2: sinon on reconstitue: qty_per_unit × multiplier (ex: 1 L × 3)
            if qty_total is None and (qty_per_unit is not None or multiplier is not None):
                try:
                    qpu = float(qty_per_unit or 0)
                    mul = float(multiplier or 0)
                    q = qpu * mul
                    if q > 0:
                        qty_total = q
                except Exception:
                    pass

            # Si on a une quantité correcte, on calcule le prix unitaire
            if price_total > 0 and qty_total and qty_total > 0:
                last_unit = price_total / qty_total

        it["last_price_unit"] = last_unit  # peut être None si inconnu
        it["currency"] = "€"  # TODO: lire depuis settings si besoin
        it["price_history_json"] = json.dumps(hist, ensure_ascii=False)
        it["stock_value"] = stock_values.get(pid, 0.0)


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
    # étendus
    description: str = Form(""),
    default_location_id: str = Form(""),
    low_stock_enabled: str = Form("1"),
    expiry_kind: str = Form("DLC"),
    default_freeze_shelf_days: str = Form(""),
    no_freeze: str = Form(""),
    category: str = Form(""),
    parent_id: str = Form(""),
    # compat
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
        "low_stock_enabled": 0 if str(low_stock_enabled).lower() in ("0","false","off","no") else 1,
        "expiry_kind": (expiry_kind or "DLC").upper(),
        "default_freeze_shelf_days": default_freeze_shelf_days or None,
        "no_freeze": 1 if str(no_freeze).lower() in ("1","true","on","yes") else 0,
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
    # étendus
    description: str = Form(""),
    default_location_id: str = Form(""),
    low_stock_enabled: str = Form("1"),
    expiry_kind: str = Form("DLC"),
    default_freeze_shelf_days: str = Form(""),
    no_freeze: str = Form(""),
    category: str = Form(""),
    parent_id: str = Form(""),
    # compat
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
        "low_stock_enabled": 0 if str(low_stock_enabled).lower() in ("0","false","off","no") else 1,
        "expiry_kind": (expiry_kind or "DLC").upper(),
        "default_freeze_shelf_days": default_freeze_shelf_days or None,
        "no_freeze": 1 if str(no_freeze).lower() in ("1","true","on","yes") else 0,
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
            # pas de location -> crée “Général”
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
