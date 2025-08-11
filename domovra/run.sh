#!/usr/bin/with-contenv bashio
set -e

WARNING_DAYS=$(bashio::config 'retention_days_warning')
CRITICAL_DAYS=$(bashio::config 'retention_days_critical')
export WARNING_DAYS CRITICAL_DAYS

# Dossier de données (persiste dans les backups HA)
export DB_PATH="/data/domovra.sqlite3"

# Lancer l'app FastAPI (Ingress)
exec uvicorn main:app --host 0.0.0.0 --port 8099 --app-dir /opt/app
