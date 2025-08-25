# domovra/app/routes/achats.py
from __future__ import annotations

import sqlite3
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from urllib.parse import urlencode

from config import DB_PATH
from utils.http import ingress_base, render as render_with_env
from services.events import log_event
from db import (
    list_products, list_locations,
    add_lot, list_lots, update_lot
)

router = APIRouter()


# =============== Helpers DB ===============

def _conn() -> sqlite3.Connection:
    """Connexion courte à SQLite avec Row factory."""
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _num_or_none(val: str | float | int | None) -> Optional[float]:
    """Convertit une entrée en float, sinon None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _clean_barcode(raw: str | None) -> str:
    """Ne conserve que les chiffres du code-barres."""
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def _add_or_merge_lot(
    product_id: int,
    location_id: int,
    qty_delta: float,
    best_before: Optional[str],
    frozen_on: Optional[str],
) -> Dict[str, Any]:
    """
    S'il existe déjà un lot avec la signature (product_id, location_id, best_before, frozen_on),
    on incrémente sa quantité. Sinon, on crée un lot.
    """
    bb = best_before or None
    fr = frozen_on or None

    for lot in list_lots():
        if int(lot["product_id"]) != int(product_id):
            continue
        if int(lot["location_id"]) != int(location_id):
            continue
        if (lot.get("best_before") or None) == bb and (lot.get("frozen_on") or None) == fr:
            new_qty = float(lot.get("qty") or 0) + float(qty_delta or 0)
            update_lot(int(lot["id"]), new_qty, int(location_id), fr, bb)
            return {"action": "merge", "lot_id": int(lot["id"]), "new_qty": new_qty}

    lid = add_lot(int(product_id), int(location_id), float(qty_delta or 0), fr, bb)
    return {"action": "insert", "lot_id": int(lid), "new_qty": float(qty_delta or 0)}


# =============== Routes ===============

@router.get("/achats", response_class=HTMLResponse)
def achats_page(request: Request):
    """Formulaire d’ajout d’entrées de stock."""
    base = ingress_base(request)
    return render_with_env(
        request.app.state.templates,
        "achats.html",
        BASE=base,
        page="achats",
        request=request,
        products=list_products(),
        locations=list_locations(),
    )


@router.post("/achats/add")
def achats_add_action(
    request: Request,
    product_id: int = Form(...),
    location_id: int = Form(...),
    qty: float = Form(...),
    # infos achat
    unit: str = Form("pièce"),
    multiplier: int = Form(1),
    price_total: str = Form(""),
    ean: str = Form(""),
    name: str = Form(""),
    brand: str = Form(""),
    store: str = Form(""),
    note: str = Form(""),
    # conservation
    best_before: str = Form(""),
    frozen_on: str = Form(""),
):
    """
    Ajoute un achat :
      - fusionne avec un lot équivalent si possible,
      - sinon crée un lot,
      - enrichit la ligne de lot avec les infos d’achat (prix, ean, etc.),
      - met à jour le code-barres produit si absent.
    """
# Multiplieur sûr (>= 1)
try:
    m = max(1, int(multiplier or 1))
except Exception:
    m = 1

# --- NOUVEAU : normalisation des unités vers l'unité de référence du produit ---
# 1) Récupérer l'unité de base du produit (ex. "g", "kg", "ml", "L", "pièce")
prod = next((p for p in list_products() if int(p["id"]) == int(product_id)), None)
base_unit = (prod["unit"] if prod else "").strip() or "pièce"

# (Optionnel) Avertissement si incohérence masse/volume
mass = {"g", "kg"}
vol  = {"ml", "l", "L"}
if (base_unit in mass and (unit or "").lower() in {"ml", "l"}) or \
   (base_unit in {"ml", "l", "L"} and (unit or "").lower() in {"g", "kg"}):
    # Tu peux soit:
    # - lever une erreur (redirect avec ?error=unite_incoherente)
    # - OU juste continuer mais sans conversion, et afficher un toast côté UI.
    pass


# 2) Petit helper local de conversion vers l'unité de base
def _to_base(q: float, u_in: str, u_base: str) -> float:
    ui = (u_in or "").strip().lower()
    ub = (u_base or "").strip().lower()
    # Harmoniser litre
    if ui == "l": ui = "l"
    if ub == "l": ub = "l"

    # Masses
    if (ui, ub) == ("kg", "g"):   return q * 1000.0
    if (ui, ub) == ("g", "kg"):   return q / 1000.0

    # Volumes
    if (ui, ub) == ("l", "ml"):   return q * 1000.0
    if (ui, ub) == ("ml", "l"):   return q / 1000.0

    # Identique ou conversion non gérée : on ne touche pas
    return q

# 3) Convertir la quantité saisie vers l'unité de base du produit
qty_per_unit = float(qty or 0)
qty_per_unit_base = _to_base(qty_per_unit, unit, base_unit)

# 4) Appliquer le multiplicateur
qty_delta = qty_per_unit_base * m
# -------------------------------------------------------------------------------

ean_digits = _clean_barcode(ean)
price_num = _num_or_none(price_total)

# Ajout ou merge du lot
res = _add_or_merge_lot(
    int(product_id), int(location_id),
    float(qty_delta),
    best_before or None, frozen_on or None,
)


    # Si EAN fourni et produit sans code-barres -> on le remplit
    if ean_digits:
        try:
            with _conn() as c:
                row = c.execute(
                    "SELECT COALESCE(barcode,'') AS barcode FROM products WHERE id=?",
                    (int(product_id),)
                ).fetchone()
                current_bc = (row["barcode"] or "") if row else ""
                if not current_bc.strip():
                    c.execute(
                        "UPDATE products SET barcode=? WHERE id=?",
                        (ean_digits, int(product_id))
                    )
                    c.commit()
        except Exception:
            # volontairement silencieux (pas bloquant pour l’ajout)
            pass

    # Enrichit la ligne de lot (infos d’achat entrées utilisateur)
    try:
        lot_id = int(res["lot_id"])
        with _conn() as c:
            sets, params = [], []

            def _add_set(col: str, val: Any) -> None:
                if val is None:
                    return
                if not isinstance(val, (int, float)):
                    val = str(val).strip()
                    if val == "":
                        return
                sets.append(f"{col}=?")
                params.append(val)

            _add_set("name", name)
            _add_set("article_name", name)        # alias affichage
            _add_set("brand", brand)
            _add_set("ean", ean_digits or None)
            _add_set("store", store)
            _add_set("note", note)
            _add_set("price_total", price_num)
            _add_set("qty_per_unit", qty_per_unit)
            _add_set("multiplier", m)
            _add_set("unit_at_purchase", unit or "pièce")

            if sets:
                params.append(lot_id)
                c.execute(f"UPDATE stock_lots SET {', '.join(sets)} WHERE id=?", params)
                c.commit()
    except Exception:
        # enrichissement best-effort; on n’échoue pas l’opération principale
        pass

    # Journalisation
    log_event("achats.add", {
        "result": res["action"], "lot_id": res["lot_id"], "new_qty": res["new_qty"],
        "product_id": int(product_id), "location_id": int(location_id),
        "ean": ean_digits or None,
        "name": (name or None), "brand": (brand or None),
        "unit": (unit or None), "qty_per_unit": qty_per_unit, "multiplier": m,
        "qty_delta": qty_delta, "price_total": price_num,
        "store": (store or None), "note": (note or None),
        "best_before": best_before or None, "frozen_on": frozen_on or None,
    })

    # Redirect UI
    base = ingress_base(request)
    return RedirectResponse(base + "achats?added=1", status_code=303,
                            headers={"Cache-Control": "no-store"})
