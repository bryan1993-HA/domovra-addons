import os, time

WARNING_DAYS  = int(os.environ.get("WARNING_DAYS",  "30"))
CRITICAL_DAYS = int(os.environ.get("CRITICAL_DAYS", "14"))
DB_PATH       = os.environ.get("DB_PATH", "/data/domovra.sqlite3")

START_TS = os.environ.get("START_TS") or str(int(time.time()))
