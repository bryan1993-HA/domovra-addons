from fastapi import FastAPI, Request, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Fonctions fictives (à remplacer par ta logique réelle)
def ingress_base(request: Request):
    return "/"

def get_all_lots():
    # Exemple : chaque lot a un product, location, status
    return [
        {"id": 1, "product": "Pâtes", "location": "Cuisine", "status": "green", "quantity": 5},
        {"id": 2, "product": "Riz", "location": "Cuisine", "status": "yellow", "quantity": 2},
        {"id": 3, "product": "Lait", "location": "Frigo", "status": "red", "quantity": 1},
    ]

def get_all_locations():
    return [
        {"name": "Cuisine"},
        {"name": "Frigo"},
        {"name": "Garage"}
    ]

def render(name, **kwargs):
    return templates.TemplateResponse(name, kwargs)

@app.get("/lots", response_class=HTMLResponse)
def lots_page(request: Request,
              product: str = Query("", alias="product"),
              location: str = Query("", alias="location"),
              status: str = Query("", alias="status")):
    items = get_all_lots()
    locations = get_all_locations()

    # Filtrage produit
    if product:
        items = [i for i in items if product.lower() in i["product"].lower()]

    # Filtrage emplacement
    if location:
        items = [i for i in items if i["location"] == location]

    # Filtrage statut
    if status:
        items = [i for i in items if i["status"] == status]

    return render("lots.html",
                  BASE=ingress_base(request),
                  page="lots",
                  items=items,
                  locations=locations,
                  request=request)
