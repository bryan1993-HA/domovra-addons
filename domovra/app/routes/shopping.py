# domovra/app/routes/shopping.py
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse

from utils.http import ingress_base, render as render_with_env
from db import list_products_with_stats  # on reste cohérent avec products.py

router = APIRouter()

@router.get("/shopping", response_class=HTMLResponse)
def shopping_page(
    request: Request,
    show: str = Query("outofstock", description="all | outofstock"),
    q: str = Query("", description="recherche simple par nom de produit"),
):
    """
    Page Liste de courses.
    Par défaut : affiche les produits en rupture (stock <= 0).
    Paramètres :
      - show=all        → tout afficher
      - show=outofstock → uniquement rupture (défaut)
      - q=...           → filtre côté serveur par nom
    """
    base = ingress_base(request)

    products = list_products_with_stats()  # doit fournir au moins: id, name, stock_qty
    items = []
    q_norm = (q or "").strip().lower()

    for p in products:
        qty = p.get("stock_qty") or 0
        name = (p.get("name") or "").strip()
        if show == "outofstock" and qty > 0:
            continue
        if q_norm and q_norm not in name.lower():
            continue
        items.append({
            "id": p.get("id"),
            "name": name,
            "stock_qty": qty,
        })

    return render_with_env("shopping.html", {
        "BASE": base,
        "items": items,
        "params": {"show": show, "q": q},
    })
