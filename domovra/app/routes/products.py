# /opt/app/routes/products.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/products", response_class=HTMLResponse)
def products_page(request: Request):
    return HTMLResponse("<h1>OK /products</h1>")
