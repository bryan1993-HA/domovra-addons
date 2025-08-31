# domovra/app/config.py
import os

# Emplacement DB (add-on: exporté par run.sh ; fallback chemin persistant)
DB_PATH = os.environ.get("DB_PATH", "/data/domovra.sqlite3")


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return int(default)
        return int(str(raw).strip())
    except Exception:
        return int(default)


def get_retention_thresholds() -> tuple[int, int]:
    """
    Retourne (WARNING_DAYS, CRITICAL_DAYS) en priorité depuis /data/settings.json,
    sinon fallback sur variables d'environnement (héritées de l'add-on),
    sinon valeurs sûres (30 / 14).
    """
    # 1) Essaye via settings_store (UI Domovra)
    try:
        from settings_store import load_settings  # lazy import pour éviter les cycles
        s = load_settings() or {}
        w = s.get("retention_days_warning", None)
        c = s.get("retention_days_critical", None)
        if w is not None and c is not None:
            return int(w), int(c)
    except Exception:
        # on tombera sur les fallbacks ci-dessous
        pass

    # 2) Fallback : variables d'environnement (compat add-on)
    w_env = _env_int("WARNING_DAYS", 30)
    c_env = _env_int("CRITICAL_DAYS", 14)
    return w_env, c_env


# Back-compat : on laisse ces constantes pour les vieux imports,
# mais on préfère désormais appeler get_retention_thresholds() à l'usage.
WARNING_DAYS, CRITICAL_DAYS = get_retention_thresholds()
