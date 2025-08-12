import logging
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from starlette import status

from app.settings_store import load_settings, save_settings

LOGGER = logging.getLogger("domovra.routes.settings")
templates = Jinja2Templates(directory="app/templates")

router = APIRouter()

def _base_path(req: Request) -> str:
    # Permet un préfixe éventuel si tu en utilises un
    return getattr(req.app.state, "BASE_PATH", "/")

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    try:
        settings = load_settings()
        base = _base_path(request)
        LOGGER.info("GET /settings depuis %s UA=%s",
                    request.client.host if request.client else "?", request.headers.get("user-agent", "-"))
        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "SETTINGS": settings,
                "BASE": base if base.endswith("/") else f"{base}/",
            },
        )
    except Exception as e:
        LOGGER.exception("Erreur GET /settings: %s", e)
        return PlainTextResponse(f"Erreur chargement paramètres: {e}", status_code=500)

@router.post("/settings/save")
async def settings_save(
    request: Request,
    theme: str = Form(...),
    sidebar_compact: str | None = Form(None),
    table_mode: str = Form(...),
    default_shelf_days: int = Form(...),
    low_stock_default: int = Form(...),
):
    """
    Sauvegarde des paramètres avec logs détaillés.
    - On journalise le payload normalisé.
    - En cas d'erreur, on log l'exception et on renvoie 303 vers la page avec un indicateur d'erreur.
    """
    base = _base_path(request)
    # Normalise le booléen checkbox : présent => "on"/"1", sinon None
    compact_bool = bool(sidebar_compact in ("on", "1", "true", "True"))

    raw = {
        "theme": theme,
        "sidebar_compact": compact_bool,
        "table_mode": table_mode,
        "default_shelf_days": default_shelf_days,
        "low_stock_default": low_stock_default,
    }
    LOGGER.info("POST /settings/save payload brut: %s", raw)

    try:
        data = save_settings(raw)
        LOGGER.info("POST /settings/save OK -> %s", data)
        # Redirection vers la page settings (303 pour éviter le repost)
        url = (base if base.endswith("/") else f"{base}/") + "settings?ok=1"
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        LOGGER.exception("POST /settings/save ERREUR: %s", e)
        url = (base if base.endswith("/") else f"{base}/") + "settings?error=1"
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
