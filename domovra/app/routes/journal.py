# domovra/app/routes/journal.py
import sqlite3
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from config import DB_PATH
from utils.http import ingress_base, render as render_with_env
from services.events import list_events, log_event

router = APIRouter()

# --- DB helper ---------------------------------------------------------------

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

# --- Pages -------------------------------------------------------------------

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
    # Suppression dure côté base
    with _conn() as c:
        c.execute("DELETE FROM events")
        c.commit()
    # Trace l’action dans les logs applicatifs (pas dans la table qu’on vient d’effacer)
    log_event("journal.clear", {"by": "ui"})
    return RedirectResponse(
        base + "journal?cleared=1",
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )

# --- API ---------------------------------------------------------------------

@router.get("/api/events")
def api_events(limit: int = 200):
    return JSONResponse(list_events(limit))
