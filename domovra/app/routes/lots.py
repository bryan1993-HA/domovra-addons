# app/routes/lots.py
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from urllib.parse import urlencode

from utils.http import ingress_base, render as render_with_env
from services.events import log_event
from config import WARNING_DAYS, CRITICAL_DAYS
from db import (
    list_lots, list_locations, list_products,
    add_lot, update_lot, delete_lot, consume_lot,
    status_for
)

router = APIRouter()

@router.get("/lots", response_class=HTMLResponse)
def lots_page(
    request: Request,
    product: str = Query("", alias="product"),
    location: str = Query("", alias="location"),
    status: str = Query("", alias="status"),
):
    base = ingress_base(request)

    items = list_lots()
    for it in items:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)

    if product:
        needle = product.casefold()
        items = [i for i in items if needle in (i.get("product", "").casefold())]
    if location:
        items = [i for i in items if i.get("location") == location]
    if status:
        items = [i for i in items if i.get("status") == status]

    return render_with_env(
        request.app.state.templates,
        "lots.html",
        BASE=base,
        page="lots",
        request=request,
        items=items,
        locations=list_locations(),
        products=list_products(),
    )

@router.post("/lot/add")
def lot_add_action(request: Request,
                   product_id: int = Form(...),
                   location_id: int = Form(...),
                   qty: float = Form(...),
                   frozen_on: str = Form(""),
                   best_before: str = Form("")):
    add_lot(product_id, location_id, float(qty), frozen_on or None, best_before or None)
    log_event("lot.add", {
        "product_id": product_id, "location_id": location_id, "qty": float(qty),
        "frozen_on": frozen_on or None, "best_before": best_before or None
    })
    return RedirectResponse(ingress_base(request) + "lots?added=1",
                            status_code=303, headers={"Cache-Control": "no-store"})

@router.post("/lot/update")
def lot_update_action(request: Request,
                      lot_id: int = Form(...),
                      qty: float = Form(...),
                      location_id: int = Form(...),
                      frozen_on: str = Form(""),
                      best_before: str = Form("")):
    try:
        q = float(qty)
    except Exception:
        q = 0.0
    update_lot(lot_id, q, int(location_id), frozen_on or None, best_before or None)
    log_event("lot.update", {
        "lot_id": lot_id, "qty": q, "location_id": int(location_id),
        "frozen_on": frozen_on or None, "best_before": best_before or None
    })
    return RedirectResponse(ingress_base(request) + "lots?updated=1",
                            status_code=303, headers={"Cache-Control": "no-store"})

@router.post("/lot/consume")
def lot_consume_action(request: Request, lot_id: int = Form(...), qty: float = Form(...)):
    q = float(qty)
    consume_lot(lot_id, q)
    log_event("lot.consume", {"lot_id": lot_id, "qty": q})
    return RedirectResponse(ingress_base(request) + "lots",
                            status_code=303, headers={"Cache-Control":"no-store"})

@router.post("/lot/delete")
def lot_delete_action(request: Request, lot_id: int = Form(...)):
    delete_lot(lot_id)
    log_event("lot.delete", {"lot_id": lot_id})
    return RedirectResponse(ingress_base(request) + "lots?deleted=1",
                            status_code=303, headers={"Cache-Control": "no-store"})

# (optionnel) petit debug JSON pratique
@router.get("/_debug/lots")
def debug_lots():
    items = list_lots()
    for it in items:
        it["status"] = status_for(it.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
    return JSONResponse({"count": len(items), "items": items})
