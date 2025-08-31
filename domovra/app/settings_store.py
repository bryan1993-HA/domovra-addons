# domovra/app/settings_store.py
import json
import os
import tempfile
import shutil
import logging
from typing import Any, Dict

LOGGER = logging.getLogger("domovra.settings_store")

DATA_DIR = "/data"
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

DEFAULTS: Dict[str, Any] = {
    "theme": "auto",              # auto | light | dark
    "sidebar_compact": False,     # bool
    "table_mode": "scroll",       # scroll | stacked
    "default_shelf_days": 30,     # int >= 1
    # Seuils DLC gérés par l'UI
    "retention_days_warning": 30, # int >= 0
    "retention_days_critical": 14,# int >= 0, et <= warning (voir _coerce_types)
    # (low_stock_default supprimé de l'UI ; fallback de sécurité codé côté home.py)
}

def ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix="settings.", suffix=".tmp")
    os.close(fd)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    shutil.move(tmp_path, path)

def _coerce_types(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = DEFAULTS.copy()
    out.update(raw or {})

    # Normalisations/validations simples
    if out["theme"] not in ("auto", "light", "dark"):
        out["theme"] = "auto"

    out["sidebar_compact"] = bool(out.get("sidebar_compact"))

    if out["table_mode"] not in ("scroll", "stacked"):
        out["table_mode"] = "scroll"

    try:
        out["default_shelf_days"] = max(1, int(out.get("default_shelf_days", DEFAULTS["default_shelf_days"])))
    except Exception:
        out["default_shelf_days"] = DEFAULTS["default_shelf_days"]

    # Seuils DLC
    def _int_ge0(v, dflt):
        try:
            return max(0, int(v))
        except Exception:
            return dflt

    out["retention_days_warning"]  = _int_ge0(out.get("retention_days_warning",  DEFAULTS["retention_days_warning"]),  DEFAULTS["retention_days_warning"])
    out["retention_days_critical"] = _int_ge0(out.get("retention_days_critical", DEFAULTS["retention_days_critical"]), DEFAULTS["retention_days_critical"])

    # Garde-fou logique : rouge ≤ jaune
    if out["retention_days_critical"] > out["retention_days_warning"]:
        out["retention_days_critical"] = out["retention_days_warning"]

    return out

def load_settings() -> Dict[str, Any]:
    ensure_data_dir()
    if not os.path.exists(SETTINGS_PATH):
        LOGGER.info("settings.json introuvable, création avec valeurs par défaut")
        save_settings(DEFAULTS)
        return DEFAULTS.copy()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = _coerce_types(data)
        LOGGER.debug("Chargement settings: %s", data)
        return data
    except Exception as e:
        LOGGER.exception("Erreur de lecture settings.json: %s", e)
        # On ne casse pas l'UI : retourne defaults
        return DEFAULTS.copy()

def save_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_data_dir()
    data = _coerce_types(payload)
    try:
        _atomic_write_json(SETTINGS_PATH, data)
        LOGGER.info("Paramètres enregistrés: %s", data)
        return data
    except Exception as e:
        LOGGER.exception("Erreur d'écriture settings.json: %s", e)
        raise
