# domovra/app/routes/support.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from utils.http import ingress_base, render as render_with_env

router = APIRouter()

@router.get("/support", response_class=HTMLResponse)
def support_page(request: Request):
    base = ingress_base(request)
    return render_with_env(
        request.app.state.templates,
        "support.html",
        BASE=base,
        page="support",
        request=request,
    )
