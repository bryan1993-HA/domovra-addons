# domovra/app/routes/shopping.py
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse

from utils.http import ingress_base, render as render_with_env

# On tente l'import "stats" (comme products.py). Si indispo, on retombe sur list_products()
try:
    from db import list_products_with_stats as _list_products_fn
    _HAS_STATS = True
except Exception:
    from db import list_products as _list_products_fn  # type: ignore
    _HAS_STATS = False

router = APIRouter()

@router.get("/shopping", response_class=HTMLResponse)
def shopping_page(
    request: Request,
    show: str = Query("outofstock", description="all | outofstock"),
    q: str = Query("", description="recherche simple par nom de produit"),
):
    """
    Liste de courses :
      - show=outofstock (défaut) => produits en rupture (stock <= 0 si dispo)
      - show=all => tous les produits
      - q=... => filtre par nom
    """
    base = ingress_base(request)

    # Récup des produits
    products = _list_products_fn()  # rows dict-like

    items = []
    q_norm = (q or "").strip().lower()

    for p in products:
        # Nom (tolérant aux clés possibles)
        name = (p.get("name") or p.get("product_name") or "").strip()

        # Quantité en stock : plusieurs backends => on essaie plusieurs clés
        qty = p.get("stock_qty")
        if qty is None:
            qty = p.get("stock")  # fallback
        if qty is None:
            # Si on n’a pas la stat, on met 0 pour que 'outofstock' montre au moins quelque chose
            qty = 0 if _HAS_STATS else 0

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

    return render_with_env("shopping.html", {
        "BASE": base,
        "items": items,
        "params": {"show": show, "q": q},
        # Debug léger visible dans /data/domovra.log si ton logging est en INFO+
        "debug": {"has_stats": _HAS_STATS, "raw_count": len(products), "after_filter": len(items)},
    })
