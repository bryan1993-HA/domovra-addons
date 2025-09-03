# config.py
import os
import time

# --- Seuils DLC --------------------------------------------------------------
# On privilégie les valeurs UI via settings_store. Si indisponible,
# fallback sur variables d'env (WARNING_DAYS / CRITICAL_DAYS) puis défauts.

try:
    from settings_store import load_settings  # type: ignore

    def get_retention_thresholds() -> tuple[int, int]:
        s = load_settings() or {}
        w = int(s.get("retention_days_warning", 30))
        c = int(s.get("retention_days_critical", 14))
        return w, c
except Exception:
    def _env_int(name: str, default: int) -> int:
        try:
            v = os.environ.get(name)
            return int(v) if v not in (None, "") else default
        except Exception:
            return default

    def get_retention_thresholds() -> tuple[int, int]:
        return _env_int("WARNING_DAYS", 30), _env_int("CRITICAL_DAYS", 14)

# Back-compat : certaines parties peuvent encore importer ces constantes
WARNING_DAYS, CRITICAL_DAYS = get_retention_thresholds()

# --- Base de données ---------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "/data/domovra.sqlite3")

# --- Timestamp de démarrage (utilisé par utils/jinja) ------------------------
try:
    START_TS = int(os.environ.get("START_TS") or int(time.time()))
except Exception:
    START_TS = int(time.time())
