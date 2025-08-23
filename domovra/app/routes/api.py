# domovra/app/routes/api.py
import json
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import DB_PATH
import sqlite3

router = APIRouter()

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

@router.get("/api/product/by_barcode")
def api_product_by_barcode(code: str):
    code = (code or "").strip().replace(" ", "")
    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)
    with _conn() as c:
        row = c.execute("""
            SELECT id, name, COALESCE(barcode,'') AS barcode
            FROM products
            WHERE REPLACE(COALESCE(barcode,''), ' ', '') = ?
            LIMIT 1
        """, (code,)).fetchone()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"id": row["id"], "name": row["name"], "barcode": row["barcode"]})

@router.get("/api/off")
def api_off(barcode: str):
    import urllib.request, urllib.error
    barcode = (barcode or "").strip()
    if not barcode:
        return JSONResponse({"ok": False, "error": "missing barcode"}, status_code=400)

    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Domovra/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
    except urllib.error.URLError:
        return JSONResponse({"ok": False, "error": "offline"}, status_code=502)
    except Exception:
        return JSONResponse({"ok": False, "error": "parse"}, status_code=500)

    if not isinstance(data, dict) or data.get("status") != 1:
        return JSONResponse({"ok": False, "error": "notfound"}, status_code=404)

    p = data.get("product", {}) or {}
    return JSONResponse({
        "ok": True,
        "barcode": barcode,
        "name": p.get("product_name") or "",
        "brand": p.get("brands") or "",
        "quantity": p.get("quantity") or "",
        "image": p.get("image_front_url") or p.get("image_url") or "",
    })
