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
    "theme": "auto",                 # auto | light | dark
    "sidebar_compact": False,        # bool

    # Toasts (désormais persistés)
    "toast_duration": 3000,          # int >= 500
    "toast_ok": "#4caf50",           # hex #rgb | #rrggbb
    "toast_warn": "#ffb300",
    "toast_error": "#ef5350",

    # Seuils DLC gérés par l'UI
    "retention_days_warning": 30,
    "retention_days_critical": 14,
}

def _is_hex_color(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    if not s.startswith("#"):
        return False
    h = s[1:]
    return len(h) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in h)

def _coerce_types(raw: Dict[str, Any]) -> Dict[str, Any]:
    clean_in = _only_known_keys(raw or {})
    out = DEFAULTS.copy()
    out.update(clean_in)

    # Theme
    if out["theme"] not in ("auto", "light", "dark"):
        out["theme"] = "auto"

    # Sidebar compact
    out["sidebar_compact"] = bool(out.get("sidebar_compact", False))

    # Toasts
    try:
        out["toast_duration"] = max(500, int(out.get("toast_duration", DEFAULTS["toast_duration"])))
    except Exception:
        out["toast_duration"] = DEFAULTS["toast_duration"]

    for k in ("toast_ok", "toast_warn", "toast_error"):
        v = str(out.get(k, DEFAULTS[k])).strip()
        out[k] = v if _is_hex_color(v) else DEFAULTS[k]

    # Seuils DLC >= 0
    def _int_ge0(v, dflt):
        try:
            return max(0, int(v))
        except Exception:
            return dflt

    out["retention_days_warning"] = _int_ge0(out.get("retention_days_warning", DEFAULTS["retention_days_warning"]), DEFAULTS["retention_days_warning"])
    out["retention_days_critical"] = _int_ge0(out.get("retention_days_critical", DEFAULTS["retention_days_critical"]), DEFAULTS["retention_days_critical"])

    # Garde-fou logique
    if out["retention_days_critical"] > out["retention_days_warning"]:
        out["retention_days_critical"] = out["retention_days_warning"]

    return out


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
    (Évite de réécrire des clés obsolètes.)
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
