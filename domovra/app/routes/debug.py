# domovra/app/routes/debug.py
import os, sqlite3
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from config import DB_PATH

router = APIRouter()

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

@router.get("/_debug/vars")
def debug_vars(request: Request):
    templates = request.app.state.templates
    here = os.path.dirname(os.path.abspath(__file__))        # .../routes
    app_dir = os.path.abspath(os.path.join(here, ".."))      # .../app
    static_dir = os.path.join(app_dir, "static")
    return {
        "ASSET_CSS_PATH": templates.globals.get("ASSET_CSS_PATH"),
        "STATIC_DIR": os.path.abspath(static_dir),
        "ls_static": sorted(os.listdir(static_dir)) if os.path.isdir(static_dir) else [],
        "ls_css": sorted(os.listdir(os.path.join(static_dir, "css"))) if os.path.isdir(os.path.join(static_dir, "css")) else [],
    }

@router.get("/debug/db")
def debug_db():
    out = []
    with _conn() as c:
        tables = [r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        for t in tables:
            rows = [dict(r) for r in c.execute(f"SELECT * FROM {t} LIMIT 5")]
            out.append({"table": t, "columns": list(rows[0].keys()) if rows else [], "rows": rows})
    return JSONResponse(out)
