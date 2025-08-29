# domovra/app/routes/shopping.py
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse

from utils.http import ingress_base, render as render_with_env

# On tente d'utiliser la version "with_stats" si dispo, sinon fallback.
try:
    from db import list_products_with_stats as _list_products
    _HAS_STATS = True
except Exception:
    from db import list_products as _list_products  # type: ignore
    _HAS_STATS = False

router = APIRouter()

@router.get("/shopping", response_class=HTMLResponse)
def shopping_page(
    request: Request,
    show: str = Query("outofstock", description="all | outofstock"),
    q: str = Query("", description="recherche par nom"),
):
    """
    Liste de courses :
      - show=outofstock (défaut) => produits en rupture (stock <= 0)
      - show=all => tous les produits
      - q=... => filtre par nom (contient)
    """
    base = ingress_base(request)

    # Récupère les produits (dict-like)
    products = _list_products()

    items = []
    q_norm = (q or "").strip().lower()

    for p in products:
        name = (p.get("name") or p.get("product_name") or "").strip()

        # Plusieurs backends possibles pour la quantité
        qty = p.get("stock_qty")
        if qty is None:
            qty = p.get("stock")
        if qty is None:
            qty = 0

        # Filtres
        if show == "outofstock" and (qty or 0) > 0:
            continue
        if q_norm and q_norm not in name.lower():
            continue

        items.append({
            "id": p.get("id"),
            "name": name or "(Sans nom)",
            "stock_qty": qty or 0,
        })

    return render_with_env(
        "shopping.html",
        {
            "BASE": base,
            "items": items,
            "params": {"show": show, "q": q},
            "debug": {"has_stats": _HAS_STATS, "raw_count": len(products), "after_filter": len(items)},
        },
        request.app.state.templates
    )
