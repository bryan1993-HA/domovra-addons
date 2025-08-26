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
    """Retourne la 1re valeur non vide (après trim), sinon None."""
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s != "":
            return s
    return None

def _get_product_fields_from_db(prod_id: int, wanted: Iterable[str]) -> Dict[str, str]:
    """
    Lit les colonnes *existantes* parmi 'wanted' pour le produit 'prod_id'.
    Renvoie un dict {col: valeur} avec valeurs déjà COALESCE('','').
    """
    with _conn() as c:
        cols = [r["name"] for r in c.execute("PRAGMA table_info(products)")]

        picks = [col for col in wanted if col in cols]
        if not picks:
            return {}

        select_expr = ", ".join([f"COALESCE({col}, '') AS {col}" for col in picks])
        row = c.execute(
            f"SELECT {select_expr} FROM products WHERE id = ? LIMIT 1",
            (prod_id,),
        ).fetchone()
        return dict(row) if row else {}


@router.get("/api/product-info")
def api_product_info(product_id: int = Query(..., ge=1)) -> JSONResponse:
    """
    Infos rapides pour 'Consommer un produit' (lecture seule):
      - fifo.lot_id (lot à consommer en premier, basé sur la DLC la plus proche)
      - fifo.best_before
      - total_qty (somme des lots qty > 0 de ce produit)
      - unit, brand (du produit) — robustes avec fallbacks
      - location (nom de l'emplacement du lot FIFO)
    """
    try:
        pid = int(product_id)
    except Exception:
        return JSONResponse({"error": "invalid product_id"}, status_code=400)

    try:
        # 1) Produit via helpers (clé 'brand' peut varier selon dumps)
        prods = list_products() or []
        prod = next((p for p in prods if int(p.get("id", 0)) == pid), None)
        if not prod:
            return JSONResponse({"error": "not found"}, status_code=404)

        # Fallbacks fréquents pour unit/brand (différents dumps ou anciennes versions)
        unit = _first_non_empty(
            prod.get("unit"), prod.get("uom"), prod.get("unity"), prod.get("unite")
        )
        brand = _first_non_empty(
            prod.get("brand"), prod.get("brands"), prod.get("brand_name"),
            prod.get("marque"), prod.get("producer")
        )

        # 1.b : si toujours vide, tente lecture directe DB sur les colonnes existantes
        if unit is None or brand is None:
            raw = _get_product_fields_from_db(pid, [
                "unit", "uom", "unity", "unite",
                "brand", "brands", "brand_name", "marque", "producer",
            ])
            if unit is None:
                unit = _first_non_empty(raw.get("unit"), raw.get("uom"), raw.get("unity"), raw.get("unite"))
            if brand is None:
                brand = _first_non_empty(raw.get("brand"), raw.get("brands"), raw.get("brand_name"),
                                         raw.get("marque"), raw.get("producer"))

        # 2) Lots de ce produit (qty > 0)
        lots = [l for l in (list_lots() or [])
                if int(l.get("product_id", 0)) == pid and float(l.get("qty") or 0) > 0]

        # Total
        total_qty = sum(float(l.get("qty") or 0) for l in lots)

        # 3) FIFO = DLC la plus proche ; DLC vides en dernier
        def fifo_key(l):
            bb = l.get("best_before")
            # vides après → astuce : "~" > chiffres en tri ASCII
            return ("~", "") if not bb else ("", str(bb))

        fifo = {"lot_id": None, "best_before": None, "location": None}
        if lots:
            first = sorted(lots, key=fifo_key)[0]
            fifo = {
                "lot_id": first.get("id"),
                "best_before": first.get("best_before"),
                "location": first.get("location") or first.get("location_name"),
            }

        return JSONResponse({
            "product_id": pid,
            "unit": unit or "",     # renvoie string (facile à afficher côté UI)
            "brand": brand or "",   # idem
            "total_qty": total_qty,
            "fifo": fifo,
        })

    except Exception as e:
        # Tu peux logguer e si besoin
        return JSONResponse({"error": "server", "detail": str(e)}, status_code=500)