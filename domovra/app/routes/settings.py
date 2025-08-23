# domovra/app/routes/settings.py
import time
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from utils.http import ingress_base, render as render_with_env
from services.events import log_event

# settings_store peut ne pas exister (fallback inclus)
try:
    from settings_store import load_settings, save_settings
except Exception:
    def load_settings():
        return {
            "theme":"auto","table_mode":"scroll","sidebar_compact":False,
            "default_shelf_days":90,
            "toast_duration":3000,"toast_ok":"#4caf50","toast_warn":"#ffb300","toast_error":"#ef5350"
        }
    def save_settings(new_values: dict):
        cur = load_settings(); cur.update(new_values or {}); return cur

router = APIRouter()

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    base = ingress_base(request)
    try:
        settings = load_settings()
        return render_with_env(
            request.app.state.templates,
            "settings.html",
            BASE=base,
            page="settings",
            request=request,
            SETTINGS=settings,
        )
    except Exception as e:
        return PlainTextResponse(f"Erreur chargement paramètres: {e}", status_code=500)

@router.post("/settings/save")
def settings_save(
    request: Request,
    theme: str = Form("auto"),
    table_mode: str = Form("scroll"),
    sidebar_compact: str = Form(None),
    default_shelf_days: int = Form(90),
    toast_duration: int = Form(3000),
    toast_ok: str = Form("#4caf50"),
    toast_warn: str = Form("#ffb300"),
    toast_error: str = Form("#ef5350"),
):
    base = ingress_base(request)
    normalized = {
        "theme": theme if theme in ("auto","light","dark") else "auto",
        "table_mode": table_mode if table_mode in ("scroll","stacked") else "scroll",
        "sidebar_compact": (sidebar_compact == "on"),
        "default_shelf_days": int(default_shelf_days or 90),
        "toast_duration": max(500, int(toast_duration or 3000)),
        "toast_ok": (toast_ok or "#4caf50").strip(),
        "toast_warn": (toast_warn or "#ffb300").strip(),
        "toast_error": (toast_error or "#ef5350").strip(),
    }
    try:
        saved = save_settings(normalized)
        log_event("settings.update", saved)
        return RedirectResponse(
            base + f"settings?ok=1&_={int(time.time())}",
            status_code=303,
            headers={"Cache-Control":"no-store"}
        )
    except Exception as e:
        log_event("settings.error", {"error": str(e), "payload": normalized})
        return RedirectResponse(
            base + "settings?error=1",
            status_code=303,
            headers={"Cache-Control":"no-store"}
        )
