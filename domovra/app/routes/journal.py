# domovra/app/routes/journal.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from utils.http import ingress_base, render as render_with_env
from services.events import list_events, log_event

router = APIRouter()

@router.get("/journal", response_class=HTMLResponse)
def journal_page(request: Request, limit: int = 200):
    base = ingress_base(request)
    events = list_events(limit)
    return render_with_env(
        request.app.state.templates,
        "journal.html",
        BASE=base,
        page="journal",
        request=request,
        events=events,
        limit=limit,
    )

@router.post("/journal/clear")
def journal_clear(request: Request):
    base = ingress_base(request)
    # On vide via log_event utilitaire existant (la suppression physique se fait côté services/db)
    # Si tu préfères supprimer en SQL brut, tu peux garder l’ancienne logique.
    log_event("journal.clear", {"by": "ui"})
    return RedirectResponse(base + "journal?cleared=1",
                            status_code=303,
                            headers={"Cache-Control": "no-store"})

@router.get("/api/events")
def api_events(limit: int = 200):
    return JSONResponse(list_events(limit))
