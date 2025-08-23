# domovra/app/main.py
# ============================================================
# Domovra — Point d’entrée FastAPI
# - Boot de l’app (logging, templates, static)
# - Montage des routers (pages + API + debug)
# - Hooks de lifecycle (startup)
# ============================================================

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import WARNING_DAYS, CRITICAL_DAYS, DB_PATH
from services.events import _ensure_events_table
from utils.assets import ensure_hashed_asset
from utils.jinja import build_jinja_env

# Routers “pages”
from routes.home import router as home_router
from routes.products import router as products_router
from routes.locations import router as locations_router
from routes.lots import router as lots_router
from routes.achats import router as achats_router
from routes.journal import router as journal_router
from routes.support import router as support_router
from routes.settings import router as settings_router
# Routers techniques
from routes.api import router as api_router
from routes.debug import router as debug_router

# DB (uniquement ce dont on a besoin ici)
from db import init_db


# ============================================================
# Logging
# ============================================================

def setup_logging() -> None:
    """Console + fichier /data/domovra.log (rotation)."""
    root = logging.getLogger()
    # reset propres si relance à chaud
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s")

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    try:
        os.makedirs("/data", exist_ok=True)
        fh = RotatingFileHandler(
            "/data/domovra.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:  # pragma: no cover (en add-on seulement)
        logging.getLogger("domovra").warning("Impossible d'ouvrir /data/domovra.log: %s", e)


setup_logging()
logger = logging.getLogger("domovra")


# ============================================================
# App & Templates
# ============================================================

app = FastAPI()
templates = build_jinja_env()

# Valeur par défaut (filet de sécurité si hashing échoue)
templates.globals.setdefault("ASSET_CSS_PATH", "static/css/domovra.css")
# Expose l'env Jinja dans l'app (utilisé par les routers)
app.state.templates = templates


# ============================================================
# Fichiers statiques + CSS versionné
# ============================================================

HERE = os.path.dirname(__file__)
STATIC_DIR = os.path.join(HERE, "static")
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)

# /static sera résolu automatiquement derrière l’ingress
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Calcule une version hashée de la CSS et l’injecte dans Jinja
try:
    css_rel = ensure_hashed_asset("static/css/domovra.css")  # -> static/css/domovra-<hash>.css
    if not (isinstance(css_rel, str) and css_rel.startswith("static/")):
        css_rel = "static/css/domovra.css"  # filet de sécurité
    templates.globals["ASSET_CSS_PATH"] = css_rel
    logger.info("ASSET_CSS_PATH = %s", css_rel)
except Exception as e:  # pragma: no cover
    logger.exception("Failed to compute ASSET_CSS_PATH: %s", e)

# Logs utiles au boot (surtout en add-on)
try:
    def _ls(p: str):
        try:
            return sorted(os.listdir(p))
        except Exception:
            return "N/A"

    logger.info("Static mounted at %s", STATIC_DIR)
    logger.info("Check %s exists=%s items=%s", STATIC_DIR, os.path.isdir(STATIC_DIR), _ls(STATIC_DIR))
    css_dir = os.path.join(STATIC_DIR, "css")
    css_file = os.path.join(css_dir, "domovra.css")
    logger.info(
        "Check %s exists=%s items=%s", css_dir, os.path.isdir(css_dir), _ls(css_dir)
    )
    logger.info(
        "CSS file %s exists=%s size=%s",
        css_file,
        os.path.isfile(css_file),
        os.path.getsize(css_file) if os.path.isfile(css_file) else "N/A",
    )
except Exception as e:  # pragma: no cover
    logger.exception("Static check failed: %s", e)


# ============================================================
# Montage des routers
# ============================================================

# Pages
app.include_router(home_router)
app.include_router(products_router)
app.include_router(locations_router)
app.include_router(lots_router)
app.include_router(achats_router)
app.include_router(journal_router)
app.include_router(support_router)
app.include_router(settings_router)

# Technique / API
app.include_router(api_router)
app.include_router(debug_router)


# ============================================================
# Lifecycle
# ============================================================

@app.on_event("startup")
def _startup() -> None:
    logger.info("Domovra starting. DB_PATH=%s", DB_PATH)
    logger.info("WARNING_DAYS=%s  CRITICAL_DAYS=%s", WARNING_DAYS, CRITICAL_DAYS)

    # DB & events table
    init_db()
    _ensure_events_table()

    # Settings (si présents, sinon fallback dans routes/settings)
    try:
        from settings_store import load_settings  # lazy import
        current = load_settings()
        logger.info("Settings au démarrage: %s", current)
    except Exception as e:  # pragma: no cover
        logger.exception("Erreur lecture settings au démarrage: %s", e)
