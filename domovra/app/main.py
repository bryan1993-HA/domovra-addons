import os, logging, sqlite3, time, json, hashlib, shutil
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import (
    HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
)
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlencode

from config import WARNING_DAYS, CRITICAL_DAYS, DB_PATH
from utils.http import ingress_base, render as _render_with_env
from utils.jinja import build_jinja_env
from utils.assets import ensure_hashed_asset
from services.events import _ensure_events_table, log_event, list_events

# Routers “pages”
from routes.home import router as home_router
from routes.products import router as products_router
from routes.locations import router as locations_router
from routes.lots import router as lots_router
from routes.achats import router as achats_router
from routes.journal import router as journal_router
from routes.support import router as support_router
from routes.settings import router as settings_router

from routes.api import router as api_router
from routes.debug import router as debug_router


# DB: uniquement ce qui est *réellement* utilisé ici
from db import (
    init_db,
    # pages Achats
    list_products, list_locations,
    # helpers pour ajout/merge de lots
    add_lot, list_lots, update_lot,
)

# ================== Logging ==================
def setup_logging():
    root = logging.getLogger()
    if root.handlers:
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
        fh = RotatingFileHandler("/data/domovra.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:
        logging.getLogger("domovra").warning("Impossible d'ouvrir /data/domovra.log: %s", e)

setup_logging()
logger = logging.getLogger("domovra")

# ================== App & Templates ==================
app = FastAPI()
templates = build_jinja_env()

def render(name: str, **ctx):
    return _render_with_env(templates, name, **ctx)

app.state.templates = templates

# Valeur par défaut (filet de sécurité si hashing échoue)
templates.globals.setdefault("ASSET_CSS_PATH", "static/css/domovra.css")

# ================== Static ==================
HERE = os.path.dirname(__file__)
STATIC_DIR = os.path.join(HERE, "static")
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Calcul et injection du CSS versionné (une seule fois)
try:
    css_rel = ensure_hashed_asset("static/css/domovra.css")  # -> static/css/domovra-<hash>.css
    if not (isinstance(css_rel, str) and css_rel.startswith("static/")):
        css_rel = "static/css/domovra.css"
    templates.globals["ASSET_CSS_PATH"] = css_rel
    logger.info("ASSET_CSS_PATH set to %s", css_rel)
except Exception as e:
    logger.exception("Failed to compute ASSET_CSS_PATH: %s", e)
    # garde la valeur par défaut

# Logs de vérification au boot (utile en add-on)
try:
    logger.info("Static mounted at %s", STATIC_DIR)
    def _ls(p):
        try:
            return sorted(os.listdir(p))
        except Exception:
            return "N/A"
    logger.info("Check %s exists=%s items=%s", STATIC_DIR, os.path.isdir(STATIC_DIR), _ls(STATIC_DIR))
    css_dir = os.path.join(STATIC_DIR, "css")
    logger.info("Check %s exists=%s items=%s", css_dir, os.path.isdir(css_dir), _ls(css_dir))
    css_file = os.path.join(css_dir, "domovra.css")
    logger.info("CSS file %s exists=%s size=%s",
                css_file, os.path.isfile(css_file),
                os.path.getsize(css_file) if os.path.isfile(css_file) else "N/A")
except Exception as e:
    logger.exception("Static check failed: %s", e)

# ================== Helpers ==================
def _abs_path(relpath: str) -> str:
    p = relpath.lstrip("/\\")
    return os.path.join(HERE, p)

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

# ================== Routers ==================
app.include_router(home_router)
app.include_router(products_router)
app.include_router(locations_router)
app.include_router(lots_router)
app.include_router(achats_router)
app.include_router(journal_router)
app.include_router(support_router)
app.include_router(settings_router)
app.include_router(api_router)
app.include_router(debug_router)



# ================== Lifecycle ==================
@app.on_event("startup")
def _startup():
    logger.info("Domovra starting. DB_PATH=%s", DB_PATH)
    logger.info("WARNING_DAYS=%s CRITICAL_DAYS=%s", WARNING_DAYS, CRITICAL_DAYS)
    init_db()
    _ensure_events_table()
    try:
        from settings_store import load_settings  # lazy (fallback plus bas sinon)
        current = load_settings()
        logger.info("Settings au démarrage: %s", current)
    except Exception as e:
        logger.exception("Erreur lecture settings au démarrage: %s", e)