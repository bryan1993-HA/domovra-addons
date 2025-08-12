import json, os, threading

# Fichier persistant (volume /data de l'add-on)
SETTINGS_PATH = os.environ.get("DOMOVRA_SETTINGS_PATH", "/data/settings.json")
_lock = threading.Lock()

DEFAULTS = {
    "theme": "auto",            # auto | light | dark
    "table_mode": "scroll",     # scroll | stacked
    "sidebar_compact": False,   # menu latéral compact au démarrage
    "default_shelf_days": 90,   # valeur par défaut lors création produit
    "low_stock_default": 1      # seuil stock faible par défaut
}

def _ensure_dir():
    d = os.path.dirname(SETTINGS_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)

def load_settings():
    """Lit le fichier /data/settings.json, fusionne avec DEFAULTS et réécrit si besoin."""
    with _lock:
        data = {}
        try:
            if os.path.isfile(SETTINGS_PATH):
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
        except Exception:
            data = {}
        merged = {**DEFAULTS, **data}
        try:
            _ensure_dir()
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return merged

def save_settings(new_values: dict):
    """Écrit les nouvelles valeurs fusionnées dans /data/settings.json et les renvoie."""
    with _lock:
        current = load_settings()
        current.update({k: v for k, v in (new_values or {}).items() if k in DEFAULTS})
        _ensure_dir()
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        return current
