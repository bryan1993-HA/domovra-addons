# domovra/app/routes/locations.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from urllib.parse import urlencode

from utils.http import ingress_base, render as render_with_env
from services.events import log_event
from config import WARNING_DAYS, CRITICAL_DAYS
from db import (
    list_locations, list_lots, status_for,
    add_location, update_location, delete_location, move_lots_from_location,
)

router = APIRouter()

@router.get("/locations", response_class=HTMLResponse)
def locations_page(request: Request):
    base = ingress_base(request)
    items = list_locations()

    counts_total: dict[int,int] = {}
    counts_soon:  dict[int,int] = {}
    counts_urg:   dict[int,int] = {}
    for l in list_lots():
        st = status_for(l.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
        lid = int(l["location_id"])
        counts_total[lid] = counts_total.get(lid, 0) + 1
        if st == "yellow":
            counts_soon[lid] = counts_soon.get(lid, 0) + 1
        elif st == "red":
            counts_urg[lid] = counts_urg.get(lid, 0) + 1

    for it in items:
        lid = int(it["id"])
        it["lot_count"]    = int(counts_total.get(lid, 0))
        it["soon_count"]   = int(counts_soon.get(lid, 0))
        it["urgent_count"] = int(counts_urg.get(lid, 0))

    return render_with_env(
        request.app.state.templates,
        "locations.html",
        BASE=base,
        page="locations",
        request=request,
        items=items,
    )

@router.post("/location/add")
def location_add(
    request: Request,
    name: str = Form(...),
    is_freezer: str | None = Form(None),
    description: str | None = Form(None),
):
    base = ingress_base(request)
    nm = (name or "").strip()

    existing = [l["name"].strip().casefold() for l in list_locations()]
    if nm.casefold() in existing:
        log_event("location.duplicate", {"name": nm})
        params = urlencode({"duplicate": 1, "name": nm})
        return RedirectResponse(base + f"locations?{params}", status_code=303,
                                headers={"Cache-Control":"no-store"})

    freezer = 1 if is_freezer else 0
    desc = (description or "").strip() or None

    lid = add_location(nm, freezer, desc)
    log_event("location.add", {"id": lid, "name": nm, "is_freezer": freezer, "description": desc})

    params = urlencode({"added": 1, "name": nm})
    return RedirectResponse(base + f"locations?{params}", status_code=303,
                            headers={"Cache-Control":"no-store"})

@router.post("/location/update")
def location_update(
    request: Request,
    location_id: int = Form(...),
    name: str = Form(...),
    is_freezer: str = Form(""),
    description: str = Form(""),
):
    base = ingress_base(request)
    nm = (name or "").strip()
    freezer = 1 if str(is_freezer).lower() in ("1","true","on","yes") else 0
    desc = (description or "").strip()

    update_location(location_id, nm, freezer, desc)
    log_event("location.update", {"id": location_id, "name": nm, "is_freezer": freezer, "description": desc})
    params = urlencode({"updated": 1, "name": nm})
    return RedirectResponse(base + f"locations?{params}", status_code=303,
                            headers={"Cache-Control":"no-store"})

@router.post("/location/delete")
def location_delete(
    request: Request,
    location_id: int = Form(...),
    move_to: str = Form(""),
):
    base = ingress_base(request)

    # on lit pour les logs + vérification congélo
    import sqlite3, os
    from config import DB_PATH
    def _conn():
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        return c

    with _conn() as c:
        row = c.execute(
            "SELECT name, COALESCE(is_freezer,0) AS is_freezer FROM locations WHERE id=?",
            (location_id,)
        ).fetchone()
        nm = row["name"] if row else ""
        src_is_freezer = int(row["is_freezer"] or 0) if row else 0

    move_to_id = (move_to or "").strip()
    move_invalid = False

    if move_to_id:
        try:
            with _conn() as c:
                dest = c.execute(
                    "SELECT COALESCE(is_freezer,0) AS is_freezer FROM locations WHERE id=?",
                    (int(move_to_id),)
                ).fetchone()
                dest_is_freezer = int(dest["is_freezer"] or 0) if dest else 0

            if src_is_freezer != dest_is_freezer:
                move_invalid = True
            else:
                move_lots_from_location(int(location_id), int(move_to_id))
                log_event("location.move_lots", {"from": int(location_id), "to": int(move_to_id)})
        except Exception as e:
            # on loggue mais on continue la suppression
            log_event("location.move_lots.error", {"from": int(location_id), "to": move_to_id, "error": str(e)})

    delete_location(location_id)
    log_event("location.delete", {"id": location_id, "name": nm, "moved_to": move_to_id or None})

    params = {"deleted": 1}
    if move_invalid:
        params["move_invalid"] = 1
    return RedirectResponse(base + "locations?" + urlencode(params),
                            status_code=303,
                            headers={"Cache-Control":"no-store"})
