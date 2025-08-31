# domovra/app/routes/locations.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from urllib.parse import urlencode

from utils.http import ingress_base
from services.events import log_event

from db import (
    list_locations, list_lots,
    status_for,
    add_location, update_location, delete_location, move_lots_from_location,
)
from config import get_retention_thresholds

router = APIRouter()

# --------- Redirection de /locations vers Settings ---------

@router.get("/locations", response_class=HTMLResponse)
def locations_page(request: Request):
    """On n’affiche plus locations.html : on redirige vers Settings → onglet Emplacements"""
    base = ingress_base(request)
    url = f"{base}settings?tab=locations"
    return RedirectResponse(url=url, status_code=307, headers={"Cache-Control": "no-store"})


# --------- Endpoints d’actions ---------

@router.post("/location/add")
def location_add(request: Request,
                 name: str = Form(...),
                 is_freezer: str | None = Form(None),
                 description: str | None = Form(None)):
    base = ingress_base(request)
    nm = (name or "").strip()

    existing = [l["name"].strip().casefold() for l in list_locations()]
    if nm.casefold() in existing:
        log_event("location.duplicate", {"name": nm})
        params = urlencode({"tab": "locations", "duplicate": 1, "name": nm})
        return RedirectResponse(base + f"settings?{params}", status_code=303, headers={"Cache-Control": "no-store"})

    freezer = 1 if is_freezer else 0
    desc = (description or "").strip() or None

    lid = add_location(nm, freezer, desc)
    log_event("location.add", {"id": lid, "name": nm, "is_freezer": freezer, "description": desc})

    params = urlencode({"tab": "locations", "added": 1, "name": nm})
    return RedirectResponse(base + f"settings?{params}", status_code=303, headers={"Cache-Control": "no-store"})


@router.post("/location/update")
def location_update(
    request: Request,
    location_id: int = Form(...),
    name: str = Form(...),
    is_freezer: str = Form(""),
    description: str = Form("")
):
    base = ingress_base(request)
    nm = (name or "").strip()
    freezer = 1 if str(is_freezer).lower() in ("1", "true", "on", "yes") else 0
    desc = (description or "").strip()

    update_location(location_id, nm, freezer, desc)
    log_event("location.update", {"id": location_id, "name": nm, "is_freezer": freezer, "description": desc})
    params = urlencode({"tab": "locations", "updated": 1, "name": nm})
    return RedirectResponse(base + f"settings?{params}", status_code=303, headers={"Cache-Control": "no-store"})


@router.post("/location/delete")
def location_delete(request: Request, location_id: int = Form(...), move_to: str = Form("")):
    base = ingress_base(request)
    import sqlite3
    from config import DB_PATH

    def _conn():
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        return c

    with _conn() as c:
        row = c.execute("SELECT name, COALESCE(is_freezer,0) AS is_freezer FROM locations WHERE id=?",
                        (location_id,)).fetchone()
        nm = row["name"] if row else ""
        src_is_freezer = int(row["is_freezer"] or 0) if row else 0

    move_to_id = (move_to or "").strip()
    move_invalid = False

    if move_to_id:
        try:
            with _conn() as c:
                dest = c.execute("SELECT COALESCE(is_freezer,0) AS is_freezer FROM locations WHERE id=?",
                                 (int(move_to_id),)).fetchone()
                dest_is_freezer = int(dest["is_freezer"] or 0) if dest else 0

            if src_is_freezer != dest_is_freezer:
                move_invalid = True
            else:
                move_lots_from_location(int(location_id), int(move_to_id))
                log_event("location.move_lots", {"from": int(location_id), "to": int(move_to_id)})
        except Exception as e:
            log_event("location.move_lots.error", {"error": str(e)})

    delete_location(location_id)
    log_event("location.delete", {"id": location_id, "name": nm, "moved_to": move_to_id or None})

    params = {"tab": "locations", "deleted": 1}
    if move_invalid:
        params["move_invalid"] = 1
    return RedirectResponse(base + "settings?" + urlencode(params),
                            status_code=303, headers={"Cache-Control": "no-store"})


# --------- DEBUG : pour vérifier les compteurs/calculs ---------

@router.get("/_debug/locations")
def debug_locations():
    items = list_locations()
    lots = list_lots()

    counts_total, counts_soon, counts_urg = {}, {}, {}

    # ← seuils dynamiques depuis /data/settings.json (fallback env/valeurs sûres)
    WARNING_DAYS, CRITICAL_DAYS = get_retention_thresholds()

    for l in lots:
        st = status_for(l.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
        lid = int(l["location_id"])
        counts_total[lid] = counts_total.get(lid, 0) + 1
        if st == "yellow":
            counts_soon[lid] = counts_soon.get(lid, 0) + 1
        elif st == "red":
            counts_urg[lid] = counts_urg.get(lid, 0) + 1

    data = []
    for it in items:
        lid = int(it["id"])
        data.append({
            "id": lid,
            "name": it["name"],
            "is_freezer": int(it.get("is_freezer") or 0),
            "lot_count": int(counts_total.get(lid, 0)),
            "soon_count": int(counts_soon.get(lid, 0)),
            "urgent_count": int(counts_urg.get(lid, 0)),
        })
    return JSONResponse({"items": data, "total_lots": len(lots)})
