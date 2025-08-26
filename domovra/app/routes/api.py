# domovra/app/routes/api.py
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import DB_PATH

router = APIRouter()


# ========= DB helper =========
def _conn() -> sqlite3.Connection:
    """Open a SQLite connection with row dict-style access."""
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


# ========= Endpoints =========
@router.get("/api/product/by_barcode")
def api_product_by_barcode(code: str) -> JSONResponse:
    """
    Lookup a product by its barcode.

    Query params:
      - code: barcode string (spaces allowed; they are stripped)
    Returns:
      200 JSON: { id, name, barcode }
      400 JSON: { error: "missing code" }
      404 JSON: { error: "not found" }
    """
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
    """
    Proxy to Open Food Facts.

    Query params:
      - barcode: EAN/UPC code
    Returns:
      200 JSON: { ok: True, barcode, name, brand, quantity, image }
      4xx/5xx JSON with { ok: False, error: <reason> }
    """
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

import logging
log = logging.getLogger("domovra.api")

from fastapi import Query
from db import list_products, list_lots

# ---- Helpers internes (fallback champs produit) ----------------------------

from typing import Optional, Iterable

def _first_non_empty(*vals: Optional[str]) -> Optional[str]:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None

@router.get("/api/product-info")
def api_product_info(product_id: int = Query(..., ge=1)) -> JSONResponse:
    """
    Infos rapides pour 'Consommer un produit':
      - fifo: lot à consommer en premier (DLC la plus proche)
      - total_qty: somme des lots > 0
      - unit, brand: métadonnées (brand fallback depuis lots si vide sur produit)
      - lots: TOUS les lots du produit (tri FIFO), pour affichage/contrôles côté UI

    Réponse:
    {
      product_id, unit, brand, total_qty,
      fifo: { lot_id, best_before, location },
      lots_count, lots: [
        { lot_id, qty, unit, best_before, location, location_id,
          brand, ean, store, frozen_on, created_on }
      ]
    }
    """
    try:
        pid = int(product_id)
    except Exception:
        return JSONResponse({"error": "invalid product_id"}, status_code=400)

    # 1) Produit
    prods = list_products() or []
    prod = next((p for p in prods if int(p.get("id", 0)) == pid), None)
    if not prod:
        return JSONResponse({"error": "not found"}, status_code=404)

    unit_prod = _first_non_empty(prod.get("unit"), prod.get("uom"), prod.get("unity"), prod.get("unite"))
    brand_prod = _first_non_empty(
        prod.get("brand"), prod.get("brands"), prod.get("brand_name"),
        prod.get("marque"), prod.get("producer"), prod.get("brand_owner")
    )

    # 2) Lots du produit (qty > 0)
    all_lots = list_lots() or []
    lots = [
        l for l in all_lots
        if int(l.get("product_id", 0)) == pid and float(l.get("qty") or 0) > 0
    ]

    # Total
    total_qty = sum(float(l.get("qty") or 0) for l in lots)

    # 3) Trie FIFO (DLC vides en dernier)
    def fifo_key(l):
        bb = l.get("best_before")
        return ("~", "") if not bb else ("", str(bb))

    fifo_lot = None
    if lots:
        fifo_lot = sorted(lots, key=fifo_key)[0]

    fifo_payload = {
        "lot_id": fifo_lot.get("id") if fifo_lot else None,
        "best_before": fifo_lot.get("best_before") if fifo_lot else None,
        "location": (fifo_lot.get("location") or fifo_lot.get("location_name")) if fifo_lot else None,
    }

    # 4) Marque finale: produit -> lot FIFO -> premier lot qui en a une
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

    # 5) Construire la liste complète des lots pour le JSON (tri FIFO)
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

            # infos “achats”
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

from fastapi import Body

def _fifo_sort_key(l: Dict[str, Any]):
    bb = l.get("best_before")
    return ("~", "") if not bb else ("", str(bb))

def _try_log_event(kind: str, payload: Dict[str, Any]) -> None:
    """Best-effort: logge dans le journal si le service est dispo."""
    try:
        from services.events import add_event  # ou log_event selon ton projet
        add_event(kind, payload)
    except Exception:
        # on ne bloque jamais l'API pour le journal
        pass

@router.post("/api/consume")
def api_consume(
    product_id: int = Body(..., embed=True, ge=1),
    qty: float = Body(..., embed=True, gt=0),
) -> JSONResponse:
    try:
        pid = int(product_id)
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid product_id"}, status_code=400)
    try:
        q = float(qty)
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid qty"}, status_code=400)
    if q <= 0:
        return JSONResponse({"ok": False, "error": "qty must be > 0"}, status_code=400)

    from db import list_products, list_lots  # lazy

    prods = list_products() or []
    prod = next((p for p in prods if int(p.get("id", 0)) == pid), None)
    if not prod:
        return JSONResponse({"ok": False, "error": "product not found"}, status_code=404)

    all_lots = list_lots() or []
    lots = [l for l in all_lots if int(l.get("product_id", 0)) == pid and float(l.get("qty") or 0) > 0]
    if not lots:
        return JSONResponse({"ok": False, "error": "no stock"}, status_code=404)
    lots = sorted(lots, key=_fifo_sort_key)

    total_before = sum(float(l.get("qty") or 0) for l in lots)
    remaining = q
    ops: list[dict] = []

    # ---- LOGS DEBUG UTILES ----
    log.info("consume request pid=%s qty=%s", pid, q)
    log.info("fifo order lot_ids=%s", [int(l["id"]) for l in lots])

    try:
        with _conn() as c:
            cur = c.cursor()
            for l in lots:
                if remaining <= 1e-12:
                    break
                lot_id = int(l["id"])
                before = float(l.get("qty") or 0)
                if before <= 0:
                    continue
                take = before if before <= remaining else remaining
                after = max(0.0, before - take)

                # DEBUG: trace l’UPDATE exact
                log.info("UPDATE lots SET qty=%s WHERE id=%s (before=%s, take=%s)", after, lot_id, before, take)

                cur.execute("UPDATE lots SET qty = ? WHERE id = ?", (after, lot_id))

                ops.append({
                    "lot_id": lot_id,
                    "take": round(take, 6),
                    "before": round(before, 6),
                    "after": round(after, 6),
                    "best_before": l.get("best_before"),
                    "location": l.get("location") or l.get("location_name"),
                })

                _try_log_event("lot_consume", {
                    "lot_id": lot_id,
                    "product_id": pid,
                    "qty_delta": -round(take, 6),
                    "before": round(before, 6),
                    "after": round(after, 6),
                    "best_before": l.get("best_before"),
                    "location": l.get("location") or l.get("location_name"),
                    "unit": prod.get("unit") or prod.get("uom") or prod.get("unity") or prod.get("unite"),
                    "name": prod.get("name"),
                })

                remaining = max(0.0, remaining - take)

    except Exception as e:
        # >>>>> CHANGEMENT ICI : on remonte le détail <<<<<
        log.exception("api_consume failed for product_id=%s qty=%s", product_id, qty)
        return JSONResponse({"ok": False, "error": "server", "detail": str(e)}, status_code=500)

    consumed = round(q - remaining, 6)

    try:
        with _conn() as c2:
            r = c2.execute(
                "SELECT COALESCE(SUM(qty), 0) AS t FROM lots WHERE product_id = ? AND qty > 0",
                (pid,)
            ).fetchone()
            total_after = float(r["t"] or 0.0)
    except Exception as e:
        log.warning("post-consume total_after fallback due to: %s", e)
        total_after = max(0.0, total_before - consumed)

    _try_log_event("product_consume", {
        "product_id": pid,
        "requested_qty": q,
        "consumed_qty": consumed,
        "remaining_to_consume": remaining,
        "operations_count": len(ops),
    })

    return JSONResponse({
        "ok": True,
        "requested_qty": q,
        "consumed_qty": consumed,
        "remaining_to_consume": remaining,
        "operations": ops,
        "total_qty_before": round(total_before, 6),
        "total_qty_after": round(total_after, 6),
    })


@router.post("/api/consume-lot")
def api_consume_lot(
    lot_id: int = Body(..., embed=True, ge=1),
    qty: float = Body(..., embed=True, gt=0),
) -> JSONResponse:
    """Décrémente UNIQUEMENT le lot donné (sans passer au suivant)."""
    try:
        lid = int(lot_id)
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid lot_id"}, status_code=400)
    try:
        q = float(qty)
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid qty"}, status_code=400)
    if q <= 0:
        return JSONResponse({"ok": False, "error": "qty must be > 0"}, status_code=400)

    try:
        with _conn() as c:
            cur = c.cursor()
            row = cur.execute(
                "SELECT id, product_id, qty, best_before, location_id FROM lots WHERE id = ?",
                (lid,)
            ).fetchone()
            if not row:
                return JSONResponse({"ok": False, "error": "lot not found"}, status_code=404)

            before = float(row["qty"] or 0.0)
            if before <= 0:
                return JSONResponse({"ok": False, "error": "empty lot"}, status_code=409)

            take = before if before <= q else q
            after = max(0.0, before - take)
            cur.execute("UPDATE lots SET qty = ? WHERE id = ?", (after, lid))

            # journal best-effort
            _try_log_event("lot_consume", {
                "lot_id": lid,
                "product_id": int(row["product_id"]),
                "qty_delta": -round(take, 6),
                "before": round(before, 6),
                "after": round(after, 6),
                "best_before": row["best_before"],
                "location_id": row["location_id"],
            })

        # total produit après conso (utile pour UI)
        try:
            with _conn() as c2:
                r = c2.execute(
                    "SELECT COALESCE(SUM(qty),0) AS t FROM lots WHERE product_id = ? AND qty > 0",
                    (int(row["product_id"]),)
                ).fetchone()
                total_after = float(r["t"] or 0.0)
        except Exception:
            total_after = None

        return JSONResponse({
            "ok": True,
            "requested_qty": q,
            "consumed_qty": round(take, 6),
            "remaining_to_consume": round(max(0.0, q - take), 6),
            "lot": {
                "lot_id": lid,
                "before": round(before, 6),
                "after": round(after, 6),
                "best_before": row["best_before"],
                "location_id": row["location_id"],
                "product_id": int(row["product_id"]),
            },
            "total_qty_after": total_after,
        })
    except Exception:
        return JSONResponse({"ok": False, "error": "server"}, status_code=500)
