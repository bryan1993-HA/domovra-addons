# domovra/app/routes/journal.py
import sqlite3
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from config import DB_PATH
from utils.http import ingress_base, render as render_with_env
from services.events import list_events, log_event

router = APIRouter()

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

@router.get("/journal", response_class=HTMLResponse)
def journal_page(request: Request, limit: int = Query(200)):
    """Page dédiée conservée pour compat, mais on redirige désormais vers Settings -> onglet Journal."""
    base = ingress_base(request)
    return RedirectResponse(f"{base}settings?tab=journal&jlimit={int(limit)}",
                           status_code=307, headers={"Cache-Control":"no-store"})

@router.post("/journal/clear")
def journal_clear(request: Request, redirect_to: str = Form(None)):
    base = ingress_base(request)
    with _conn() as c:
        c.execute("DELETE FROM events")
        c.commit()
    log_event("journal.clear", {"by": "ui"})
    if redirect_to:
        return RedirectResponse(redirect_to, status_code=303, headers={"Cache-Control":"no-store"})
    return RedirectResponse(base + "settings?tab=journal&cleared=1",
                            status_code=303, headers={"Cache-Control":"no-store"})

@router.get("/api/events")
def api_events(limit: int = 200):
    return JSONResponse(list_events(limit))
