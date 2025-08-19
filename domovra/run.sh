#!/usr/bin/with-contenv bashio
set -e

WARNING_DAYS=$(bashio::config 'retention_days_warning')
CRITICAL_DAYS=$(bashio::config 'retention_days_critical')
export WARNING_DAYS CRITICAL_DAYS

export DB_PATH="/data/domovra.sqlite3"

# Lancer Uvicorn depuis le venv
exec /opt/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8099 --app-dir /opt/app
