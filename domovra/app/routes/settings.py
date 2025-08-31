# domovra/app/routes/settings.py
import time
import sqlite3
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse

from utils.http import ingress_base, render as render_with_env
from services.events import log_event, list_events  # Journal

# --- Settings store (avec fallback inline si le module n'existe pas) ---
try:
    from settings_store import load_settings, save_settings  # type: ignore
except Exception:  # pragma: no cover
    import os
    import json
    from pathlib import Path

    SETTINGS_FILE = Path("/data/settings.json")

    DEFAULTS = {
        "theme": "auto",
        "table_mode": "scroll",
        "sidebar_compact": False,
        "default_shelf_days": 90,
        "toast_duration": 3000,
        "toast_ok": "#4caf50",
        "toast_warn": "#ffb300",
        "toast_error": "#ef5350",
        # ↓↓↓ nouveaux réglages gérés par l’UI Domovra ↓↓↓
        "retention_days_warning": None,  # None ⇒ on tombera sur env/valeur sûre
        "retention_days_critical": None,
        # autres flags potentiels déjà utilisés par l’app :
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


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    tab: str = Query("appearance"),           # ?tab=locations|journal|admindb|...
    jlimit: int = Query(200, alias="jlimit"), # nb de lignes à afficher dans Journal
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
        )
    except Exception as e:
        return PlainTextResponse(f"Erreur chargement paramètres: {e}", status_code=500)


@router.post("/settings/save")
def settings_save(
    request: Request,
    # Apparence / UI
    theme: str = Form("auto"),
    table_mode: str = Form("scroll"),
    sidebar_compact: str = Form(None),
    default_shelf_days: int = Form(90),
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
        "table_mode": table_mode if table_mode in ("scroll", "stacked") else "scroll",
        "sidebar_compact": (sidebar_compact == "on"),
        "default_shelf_days": int(default_shelf_days or 90),

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
        # rafraîchir l'état en mémoire (utile pour d'autres champs)
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
