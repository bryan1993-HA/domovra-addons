# domovra/app/routes/settings.py
import time
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse

from utils.http import ingress_base, render as render_with_env
from services.events import log_event, list_events  # ← list_events pour l’onglet Journal

# --- Settings store (fallback inclus) ---
try:
    from settings_store import load_settings, save_settings
except Exception:
    def load_settings():
        return {
            "theme": "auto",
            "table_mode": "scroll",
            "sidebar_compact": False,
            "default_shelf_days": 90,
            "toast_duration": 3000,
            "toast_ok": "#4caf50",
            "toast_warn": "#ffb300",
            "toast_error": "#ef5350",
            # flags éventuellement utilisés ailleurs :
            "enable_off_block": True,
            "enable_scanner": True,
            "ha_notifications": False,
            "log_retention_days": 30,
            "log_consumption": True,
            "log_add_remove": True,
            "ask_move_on_delete": True,
            "low_stock_default": 1,
        }
    def save_settings(new_values: dict):
        cur = load_settings()
        cur.update(new_values or {})
        return cur

# --- Données pour l'onglet Emplacements ---
from db import list_locations, list_lots, status_for
from config import WARNING_DAYS, CRITICAL_DAYS

router = APIRouter()

@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    tab: str = Query("appearance"),         # permet d’ouvrir directement un onglet (?tab=locations|journal|...)
    jlimit: int = Query(200, alias="jlimit") # nb de lignes à afficher dans le Journal
):
    base = ingress_base(request)
    try:
        settings = load_settings()

        # ---- Emplacements (pour l’onglet "locations") ----
        # Même logique de compteurs que l’ancienne page /locations
        items = list_locations()  # emplacements existants

        counts_total: dict[int, int] = {}
        counts_soon:  dict[int, int] = {}
        counts_urg:   dict[int, int] = {}

        for l in list_lots():
            st = status_for(l.get("best_before"), WARNING_DAYS, CRITICAL_DAYS)
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

        # ---- Journal (pour l’onglet "journal") ----
        events = list_events(jlimit)

        return render_with_env(
            request.app.state.templates,
            "settings.html",
            BASE=base,
            page="settings",
            request=request,
            SETTINGS=settings,
            # Onglet Emplacements
            items=items,
            # Onglet Journal
            events=events,
            jlimit=jlimit,
            # Onglet actif (utilisé par ton JS pour sélectionner l'onglet au chargement)
            tab=tab,
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

    # champs potentiels d’autres onglets (ok s’ils n’existent pas dans le form)
    enable_off_block: str = Form(None),
    enable_scanner: str = Form(None),
    ha_notifications: str = Form(None),
    log_retention_days: int = Form(30),
    log_consumption: str = Form(None),
    log_add_remove: str = Form(None),
    ask_move_on_delete: str = Form(None),
    low_stock_default: int = Form(1),
):
    base = ingress_base(request)
    def as_bool(v): return str(v).lower() in ("1","true","on","yes")

    normalized = {
        "theme": theme if theme in ("auto","light","dark") else "auto",
        "table_mode": table_mode if table_mode in ("scroll","stacked") else "scroll",
        "sidebar_compact": (sidebar_compact == "on"),
        "default_shelf_days": int(default_shelf_days or 90),

        "toast_duration": max(500, int(toast_duration or 3000)),
        "toast_ok": (toast_ok or "#4caf50").strip(),
        "toast_warn": (toast_warn or "#ffb300").strip(),
        "toast_error": (toast_error or "#ef5350").strip(),

        # options supplémentaires (no-ops si non utilisées côté UI)
        "enable_off_block": as_bool(enable_off_block),
        "enable_scanner": as_bool(enable_scanner),
        "ha_notifications": as_bool(ha_notifications),
        "log_retention_days": int(log_retention_days or 30),
        "log_consumption": as_bool(log_consumption),
        "log_add_remove": as_bool(log_add_remove),
        "ask_move_on_delete": as_bool(ask_move_on_delete),
        "low_stock_default": int(low_stock_default or 1),
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
