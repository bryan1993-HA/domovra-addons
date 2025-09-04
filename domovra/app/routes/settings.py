# domovra/app/routes/settings.py
import time
import os
import json
import platform
import sqlite3
from datetime import datetime
from importlib.metadata import version as pkg_version, PackageNotFoundError

from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse

from utils.http import ingress_base, render as render_with_env
from services.events import log_event, list_events  # Journal

# --- Settings store (avec fallback inline si le module n'existe pas) ---
try:
    from settings_store import load_settings, save_settings  # type: ignore
    SETTINGS_PATH_FALLBACK = "/data/settings.json"  # utilisé seulement pour ABOUT
except Exception:  # pragma: no cover
    from pathlib import Path

    SETTINGS_FILE = Path("/data/settings.json")
    SETTINGS_PATH_FALLBACK = str(SETTINGS_FILE)

    DEFAULTS = {
        "theme": "auto",
        "sidebar_compact": False,
        # Toasts
        "toast_duration": 3000,
        "toast_ok": "#4caf50",
        "toast_warn": "#ffb300",
        "toast_error": "#ef5350",
        # Seuils DLC (UI)
        "retention_days_warning": None,  # None ⇒ fallback env/valeur sûre
        "retention_days_critical": None,
        # Divers drapeaux existants
        "enable_off_block": True,
        "enable_scanner": True,
        "ha_notifications": False,
        "log_retention_days": 30,
        "log_consumption": True,
        "log_add_remove": True,
        "ask_move_on_delete": False,
    }

    def _env_int(name: str, default: int) -> int:
        try:
            raw = os.environ.get(name)
            if raw is None or str(raw).strip() == "":
                return int(default)
            return int(str(raw).strip())
        except Exception:
            return int(default)

    def load_settings():
        data = DEFAULTS.copy()
        if SETTINGS_FILE.exists():
            try:
                data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass

        # Compat add-on : si absent/None, on regarde les env vars
        if data.get("retention_days_warning") is None:
            data["retention_days_warning"] = _env_int("WARNING_DAYS", 30)
        if data.get("retention_days_critical") is None:
            data["retention_days_critical"] = _env_int("CRITICAL_DAYS", 14)

        return data

    def save_settings(new_values: dict):
        data = load_settings()
        # on ne persiste que les clés connues
        for k, v in new_values.items():
            if k in DEFAULTS:
                data[k] = v
        SETTINGS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return data

# --- Données pour Emplacements & Admin DB ---
from db import list_locations, list_lots, status_for
from config import DB_PATH, get_retention_thresholds

router = APIRouter()

# ======================
# Helpers pour ABOUT
# ======================

def _safe_pkg_version(name: str) -> str:
    try:
        return pkg_version(name)
    except PackageNotFoundError:
        return "n/a"
    except Exception:
        return "n/a"

def _file_size(path: str) -> str:
    try:
        b = os.path.getsize(path)
    except OSError:
        return "n/a"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.0f} {u}"
        b /= 1024
    return f"{b:.1f} PB"

def _read_addon_config() -> dict:
    """
    Recherche config.json à plusieurs emplacements possibles.
    Dans un add-on Home Assistant, le fichier n'est pas toujours copié dans l'image.
    On remonte donc l'arbo + on teste quelques chemins connus.
    """
    here = os.path.abspath(os.path.dirname(__file__))  # …/domovra/app/routes
    candidates = []

    # 1) Remonte jusqu'à 6 niveaux et teste "config.json" à chaque niveau
    cur = here
    for _ in range(6):
        candidates.append(os.path.join(cur, "config.json"))
        cur = os.path.dirname(cur)

    # 2) Chemins habituels dans un conteneur
    candidates += [
        os.path.join(os.getcwd(), "config.json"),
        "/app/config.json",
        "/usr/src/app/config.json",
        "/config.json",
    ]

    for p in candidates:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Valide rapidement qu'on a bien un config d'add-on
                    if isinstance(data, dict) and ("slug" in data or "name" in data or "version" in data):
                        return data
        except Exception:
            pass

    # Pas trouvé : on renvoie un dict vide, build_about() gèrera les fallbacks.
    return {}

def _counts_summary(db_path: str) -> dict:
    out = {"products": 0, "locations": 0, "lots": 0, "journal": 0}
    try:
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            for table, key in (("products", "products"),
                               ("locations", "locations"),
                               ("lots", "lots"),
                               ("journal", "journal")):
                try:
                    row = c.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
                    out[key] = int(row["c"] or 0)
                except Exception:
                    pass
    except Exception:
        pass
    return out

def build_about(db_path: str, settings_path: str) -> dict:
    cfg = _read_addon_config()

    # Fallback version depuis variables d'env si config.json absent
    env_version = os.environ.get("DOMOVRA_VERSION") or os.environ.get("ADDON_VERSION")

    slug = str(cfg.get("slug", "domovra") or "domovra").lower()
    channel = "Stable"
    if "beta" in slug:
        channel = "Beta"
    if "dev" in slug or "test" in slug:
        channel = "DEV"

    # --- NEW: URLs projet / changelog
    repo_url = (cfg.get("url") or "").strip()
    changelog = (cfg.get("changelog") or "").strip()
    if not changelog and "github.com" in repo_url:
        base = repo_url[:-1] if repo_url.endswith("/") else repo_url
        # priorité aux releases ; change en /blob/main/CHANGELOG.md si tu préfères
        changelog = base + "/releases"

    log_path = "/data/domovra.log"

    return {
        "addon": {
            "name": cfg.get("name", "Domovra"),
            "version": cfg.get("version") or env_version or "n/a",
            "slug": cfg.get("slug", "domovra"),
            "channel": channel,
            "url": repo_url or None,
            "documentation": cfg.get("documentation"),
            "issue_tracker": cfg.get("issue_tracker"),
            "changelog": changelog or None,  # <- corrigé
            "description": cfg.get("description"),
        },
        "sys": {
            "python": platform.python_version(),
            "fastapi": _safe_pkg_version("fastapi"),
            "jinja2": _safe_pkg_version("jinja2"),
            "uvicorn": _safe_pkg_version("uvicorn"),
            "sqlite_lib": sqlite3.sqlite_version,
            "db_path": db_path,
            "db_size": _file_size(db_path),
            "settings_path": settings_path,
            "settings_size": _file_size(settings_path),
            "log_path": log_path,
            "log_size": _file_size(log_path),
        },
    }



# ======================
# Routes
# ======================

@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    tab: str = Query("appearance"),            # ?tab=locations|journal|admindb|...
    jlimit: int = Query(200, alias="jlimit"),  # nb de lignes à afficher dans Journal
):
    base = ingress_base(request)
    try:
        settings = load_settings()

        # Seuils dynamiques (UI → fallback env → défauts)
        WARN_DAYS, CRIT_DAYS = get_retention_thresholds()

        # ---- Emplacements (compteurs) ----
        items = list_locations()
        counts_total: dict[int, int] = {}
        counts_soon:  dict[int, int] = {}
        counts_urg:   dict[int, int] = {}

        for l in list_lots():
            st = status_for(l.get("best_before"), WARN_DAYS, CRIT_DAYS)
            lid = int(l["location_id"])
            counts_total[lid] = counts_total.get(lid, 0) + 1
            if st == "yellow":
                counts_soon[lid] = counts_soon.get(lid, 0) + 1
            elif st == "red":
                counts_urg[lid] = counts_urg.get(lid, 0) + 1

        for it in items:
            lid = int(it["id"])
            it["lot_count"]    = int(counts_total.get(lid, 0))
            it["soon_count"]   = int(counts_soon.get(lid, 0))
            it["urgent_count"] = int(counts_urg.get(lid, 0))

        # ---- Journal ----
        events = list_events(jlimit)

        # ---- Admin DB : liste des tables + chemin fichier ----
        with sqlite3.connect(DB_PATH) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """).fetchall()
        db_tables = [r["name"] for r in rows]

        # ---- ABOUT (version, chemins, tailles, runtime, counts) ----
        about = build_about(DB_PATH, SETTINGS_PATH_FALLBACK)

        return render_with_env(
            request.app.state.templates,
            "settings.html",
            BASE=base,
            page="settings",
            request=request,
            SETTINGS=settings,     # exposé au template
            # Emplacements
            items=items,
            # Journal
            events=events,
            jlimit=jlimit,
            # Admin DB
            db_tables=db_tables,
            db_path=DB_PATH,
            # Onglet actif
            tab=tab,
            # Seuils (utile si tu veux les afficher dans l’UI)
            WARNING_DAYS=WARN_DAYS,
            CRITICAL_DAYS=CRIT_DAYS,
            # À propos
            ABOUT=about,
        )
    except Exception as e:
        return PlainTextResponse(f"Erreur chargement paramètres: {e}", status_code=500)


@router.post("/settings/save")
def settings_save(
    request: Request,
    # Apparence / UI
    theme: str = Form("auto"),
    sidebar_compact: str = Form(None),
    # Toasts
    toast_duration: int = Form(3000),
    toast_ok: str = Form("#4caf50"),
    toast_warn: str = Form("#ffb300"),
    toast_error: str = Form("#ef5350"),
    # Seuils DLC (UI)
    retention_days_warning: int = Form(30),
    retention_days_critical: int = Form(14),
    # Divers (déjà existants)
    enable_off_block: str = Form(None),
    enable_scanner: str = Form(None),
    ha_notifications: str = Form(None),
    log_retention_days: int = Form(30),
    log_consumption: str = Form(None),
    log_add_remove: str = Form(None),
    ask_move_on_delete: str = Form(None),
):
    base = ingress_base(request)

    def as_bool(v) -> bool:
        return str(v).lower() in ("1", "true", "on", "yes")

    # Garde-fous numériques
    try:
        retention_days_warning = max(0, int(retention_days_warning))
    except Exception:
        retention_days_warning = 30
    try:
        retention_days_critical = max(0, int(retention_days_critical))
    except Exception:
        retention_days_critical = 14

    # 🔒 Garde-fou logique : rouge ne doit pas être > jaune
    if retention_days_critical > retention_days_warning:
        retention_days_critical = retention_days_warning

    normalized = {
        "theme": theme if theme in ("auto", "light", "dark") else "auto",
        "sidebar_compact": (sidebar_compact == "on"),

        "toast_duration": max(500, int(toast_duration or 3000)),
        "toast_ok": (toast_ok or "#4caf50").strip(),
        "toast_warn": (toast_warn or "#ffb300").strip(),
        "toast_error": (toast_error or "#ef5350").strip(),

        # seuils DLC (désormais côté UI)
        "retention_days_warning": retention_days_warning,
        "retention_days_critical": retention_days_critical,

        # autres options existantes
        "enable_off_block": as_bool(enable_off_block),
        "enable_scanner": as_bool(enable_scanner),
        "ha_notifications": as_bool(ha_notifications),
        "log_retention_days": int(log_retention_days or 30),
        "log_consumption": as_bool(log_consumption),
        "log_add_remove": as_bool(log_add_remove),
        "ask_move_on_delete": as_bool(ask_move_on_delete),
    }
    try:
        saved = save_settings(normalized)

        # rafraîchir l'état en mémoire (utile pour d'autres champs éventuels)
        try:
            request.app.state.settings = load_settings()
        except Exception:
            pass

        log_event("settings.update", saved)
        return RedirectResponse(
            base + f"settings?ok=1&_={int(time.time())}",
            status_code=303,
            headers={"Cache-Control": "no-store"},
        )
    except Exception as e:
        log_event("settings.error", {"error": str(e), "payload": normalized})
        return RedirectResponse(
            base + "settings?error=1",
            status_code=303,
            headers={"Cache-Control": "no-store"},
        )
