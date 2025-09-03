# domovra/app/routes/api.py
from __future__ import annotations

import json
import sqlite3
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Body
from fastapi.responses import JSONResponse

from config import DB_PATH
from db import list_products, list_lots

router = APIRouter()
log = logging.getLogger("domovra.api")

# Active un format lisible et DEBUG si rien n'est configuré ailleurs
if not log.handlers:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
log.setLevel(logging.DEBUG)

# ========= DB helper =========
def _conn() -> sqlite3.Connection:
    """Open a SQLite connection with row dict-style access."""
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

# ========= Endpoints =========
@router.get("/api/product/by_barcode")
def api_product_by_barcode(code: str) -> JSONResponse:
    code = (code or "").strip().replace(" ", "")
    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)

    with _conn() as c:
        row = c.execute(
            """
            SELECT id, name, COALESCE(barcode,'') AS barcode
            FROM products
            WHERE REPLACE(COALESCE(barcode,''), ' ', '') = ?
            LIMIT 1
            """,
            (code,),
        ).fetchone()

    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)

    return JSONResponse({"id": row["id"], "name": row["name"], "barcode": row["barcode"]})

@router.get("/api/off")
def api_off(barcode: str) -> JSONResponse:
    import urllib.request
    import urllib.error

    barcode = (barcode or "").strip()
    if not barcode:
        return JSONResponse({"ok": False, "error": "missing barcode"}, status_code=400)

    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Domovra/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = resp.read()
        data: Dict[str, Any] = json.loads(raw.decode("utf-8"))
    except urllib.error.URLError:
        return JSONResponse({"ok": False, "error": "offline"}, status_code=502)
    except Exception:
        return JSONResponse({"ok": False, "error": "parse"}, status_code=500)

    if not isinstance(data, dict) or data.get("status") != 1:
        return JSONResponse({"ok": False, "error": "notfound"}, status_code=404)

    p: Dict[str, Any] = data.get("product", {}) or {}
    return JSONResponse(
        {
            "ok": True,
            "barcode": barcode,
            "name": p.get("product_name") or "",
            "brand": p.get("brands") or "",
            "quantity": p.get("quantity") or "",
            "image": p.get("image_front_url") or p.get("image_url") or "",
        }
    )

# ---- Helpers -------------------------------------------------------
def _first_non_empty(*vals: Optional[str]) -> Optional[str]:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None

# ---- /api/product-info --------------------------------------------
@router.get("/api/product-info")
def api_product_info(product_id: int = Query(..., ge=1)) -> JSONResponse:
    """
    Donne l’état d’un produit pour la carte 'Consommer un produit':
      - fifo: lot à consommer en premier (DLC la plus proche)
      - total_qty: somme des lots > 0
      - unit, brand
      - lots: tous les lots triés FIFO
    """
    try:
        pid = int(product_id)
    except Exception:
        return JSONResponse({"error": "invalid product_id"}, status_code=400)

    prods = list_products() or []
    prod = next((p for p in prods if int(p.get("id", 0)) == pid), None)
    if not prod:
        return JSONResponse({"error": "not found"}, status_code=404)

    unit_prod = _first_non_empty(prod.get("unit"), prod.get("uom"), prod.get("unity"), prod.get("unite"))
    brand_prod = _first_non_empty(
        prod.get("brand"), prod.get("brands"), prod.get("brand_name"),
        prod.get("marque"), prod.get("producer"), prod.get("brand_owner")
    )

    all_lots = list_lots() or []
    lots = [l for l in all_lots if int(l.get("product_id", 0)) == pid and float(l.get("qty") or 0) > 0]
    total_qty = sum(float(l.get("qty") or 0) for l in lots)

    def fifo_key(l):
        bb = l.get("best_before")
        return ("~", "") if not bb else ("", str(bb))

    fifo_lot = sorted(lots, key=fifo_key)[0] if lots else None
    fifo_payload = {
        "lot_id": fifo_lot.get("id") if fifo_lot else None,
        "best_before": fifo_lot.get("best_before") if fifo_lot else None,
        "location": (fifo_lot.get("location") or fifo_lot.get("location_name")) if fifo_lot else None,
    }

    brand_final = brand_prod
    if not brand_final and fifo_lot:
        brand_final = _first_non_empty(
            fifo_lot.get("brand"), fifo_lot.get("product_brand"),
            fifo_lot.get("brands"), fifo_lot.get("brand_name"),
            fifo_lot.get("marque"), fifo_lot.get("brand_owner"),
        )
    if not brand_final:
        for l in lots:
            brand_final = _first_non_empty(
                l.get("brand"), l.get("product_brand"),
                l.get("brands"), l.get("brand_name"),
                l.get("marque"), l.get("brand_owner"),
            )
            if brand_final:
                break

    lots_sorted = sorted(lots, key=fifo_key)
    lots_payload = []
    for l in lots_sorted:
        lots_payload.append({
            "lot_id": l.get("id"),
            "qty": float(l.get("qty") or 0),
            "unit": _first_non_empty(l.get("unit"), unit_prod) or "",
            "best_before": l.get("best_before"),
            "location": l.get("location") or l.get("location_name"),
            "location_id": l.get("location_id"),
            "brand": _first_non_empty(
                l.get("brand"), l.get("product_brand"),
                l.get("brands"), l.get("brand_name"),
                l.get("marque"), l.get("brand_owner"),
            ) or "",
            "ean": _first_non_empty(l.get("ean"), l.get("barcode"), l.get("code")) or "",
            "store": l.get("store"),
            "frozen_on": l.get("frozen_on"),
            "created_on": l.get("created_on") or l.get("added_on"),
        })

    return JSONResponse({
        "product_id": pid,
        "unit": unit_prod or "",
        "brand": brand_final or "",
        "total_qty": total_qty,
        "fifo": fifo_payload,
        "lots_count": len(lots_payload),
        "lots": lots_payload,
    })

# ---- /api/consume (neutralisé pour éviter 500) ---------------------
@router.api_route("/api/consume", methods=["GET", "POST"])
def api_consume_disabled(
    product_id: Optional[int] = Body(None, embed=True),
    qty: Optional[float] = Body(None, embed=True),
    product_id_q: Optional[int] = Query(None, alias="product_id"),
    qty_q: Optional[float] = Query(None, alias="qty"),
) -> JSONResponse:
    """
    Neutralisé volontairement : dans ton instance, la table SQLite 'lots' n'existe pas.
    La consommation se fait côté front en postant sur 'lot/consume' (route historique).
    """
    log.warning("api_consume disabled: DB table 'lots' missing. Use client-side lot/consume.")
    return JSONResponse({"ok": False, "error": "disabled"}, status_code=501)

# ---- Consommation ciblée d’un lot (optionnelle) --------------------
@router.post("/api/stock/consume-lot")
def api_consume_lot(
    lot_id: int = Body(..., embed=True, ge=1),
    qty: float = Body(..., embed=True, gt=0),
) -> JSONResponse:
    """Décrémente UNIQUEMENT le lot donné (sans passer au suivant)."""
    try:
        lid = int(lot_id)
        q = float(qty)
    except Exception:
        return JSONResponse({"ok": False, "error": "bad params"}, status_code=400)
    if q <= 0:
        return JSONResponse({"ok": False, "error": "qty must be > 0"}, status_code=400)

    # Si ta base n’a pas de table 'lots', on sort poliment :
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT id, product_id, qty FROM lots WHERE id = ?",
                (lid,)
            ).fetchone()
    except sqlite3.OperationalError:
        return JSONResponse({"ok": False, "error": "disabled"}, status_code=501)

    if not row:
        return JSONResponse({"ok": False, "error": "lot not found"}, status_code=404)

    before = float(row["qty"] or 0.0)
    take = before if before <= q else q
    after = max(0.0, before - take)

    try:
        with _conn() as c:
            c.execute("UPDATE lots SET qty = ? WHERE id = ?", (after, lid))
    except Exception:
        return JSONResponse({"ok": False, "error": "server"}, status_code=500)

    return JSONResponse({
        "ok": True,
        "requested_qty": q,
        "consumed_qty": round(take, 6),
        "remaining_to_consume": round(max(0.0, q - take), 6),
        "lot": {"lot_id": lid, "before": round(before, 6), "after": round(after, 6)},
    })

# ---- Journalisation best-effort depuis le front --------------------
def _try_log_event(kind: str, payload: Dict[str, Any]) -> None:
    """Envoie dans un service d'événements si présent (ne plante jamais)."""
    try:
        from services.events import add_event  # optionnel selon ton projet
        add_event(kind, payload)
    except Exception:
        pass

@router.post("/api/log")
def api_log(kind: str = Body(...), payload: Dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
    """
    Écrit un événement dans le journal (si dispo). N'affecte pas la DB.
    Body JSON: { "kind": "lot_consume" | "product_consume", "payload": {...} }
    """
    try:
        log.debug("api_log kind=%s payload=%s", kind, payload)
        _try_log_event(kind, payload or {})
        return JSONResponse({"ok": True})
    except Exception:
        return JSONResponse({"ok": False}, status_code=500)
