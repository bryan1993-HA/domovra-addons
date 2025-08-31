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

# Clés officiellement supportées par l'UI
DEFAULTS: Dict[str, Any] = {
    "theme": "auto",                # auto | light | dark
    "sidebar_compact": False,       # bool
    "table_mode": "scroll",         # scroll | stacked
    "default_shelf_days": 30,       # int >= 1
    # Seuils DLC gérés par l'UI
    "retention_days_warning": 30,   # int >= 0
    "retention_days_critical": 14,  # int >= 0, et <= warning (voir _coerce_types)
    # (low_stock_default a été retiré de l'UI ; un fallback "1" vit côté home.py)
}


def ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix="settings.", suffix=".tmp"
    )
    os.close(fd)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    shutil.move(tmp_path, path)


def _only_known_keys(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ne conserve que les clés connues de DEFAULTS.
    (Évite de réécrire des clés obsolètes comme low_stock_default.)
    """
    return {k: raw.get(k, DEFAULTS[k]) for k in DEFAULTS.keys()}


def _coerce_types(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fusionne avec DEFAULTS et applique des validations/coercitions.
    """
    # Ne garder que les clés officielles avant fusion
    clean_in = _only_known_keys(raw or {})
    out = DEFAULTS.copy()
    out.update(clean_in)

    # Validations
    if out["theme"] not in ("auto", "light", "dark"):
        out["theme"] = "auto"

    out["sidebar_compact"] = bool(out.get("sidebar_compact"))

    if out["table_mode"] not in ("scroll", "stacked"):
        out["table_mode"] = "scroll"

    # Entiers >= 1
    try:
        out["default_shelf_days"] = max(
            1, int(out.get("default_shelf_days", DEFAULTS["default_shelf_days"]))
        )
    except Exception:
        out["default_shelf_days"] = DEFAULTS["default_shelf_days"]

    # Seuils DLC >= 0
    def _int_ge0(v, dflt):
        try:
            return max(0, int(v))
        except Exception:
            return dflt

    out["retention_days_warning"] = _int_ge0(
        out.get("retention_days_warning", DEFAULTS["retention_days_warning"]),
        DEFAULTS["retention_days_warning"],
    )
    out["retention_days_critical"] = _int_ge0(
        out.get("retention_days_critical", DEFAULTS["retention_days_critical"]),
        DEFAULTS["retention_days_critical"],
    )

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
            raw = json.load(f)

        # Détecte et prune les clés inconnues (legacy)
        unknown = set(raw.keys()) - set(DEFAULTS.keys())
        if unknown:
            LOGGER.info("Nettoyage des clés obsolètes dans settings.json: %s", sorted(unknown))
            cleaned = _coerce_types(raw)  # _coerce_types ne garde que les clés connues
            _atomic_write_json(SETTINGS_PATH, cleaned)
            return cleaned

        data = _coerce_types(raw)
        LOGGER.debug("Chargement settings: %s", data)
        return data

    except Exception as e:
        LOGGER.exception("Erreur de lecture settings.json: %s", e)
        # On ne casse pas l'UI : retourne defaults
        return DEFAULTS.copy()


def save_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enregistre uniquement les clés officielles, avec coercition/validation.
    Les clés non supportées sont ignorées silencieusement.
    """
    ensure_data_dir()
    try:
        # Filtre d'abord le payload pour ne garder que les clés connues
        filtered = _only_known_keys(payload or {})
        data = _coerce_types(filtered)
        _atomic_write_json(SETTINGS_PATH, data)
        LOGGER.info("Paramètres enregistrés: %s", data)
        return data
    except Exception as e:
        LOGGER.exception("Erreur d'écriture settings.json: %s", e)
        raise
