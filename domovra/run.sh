# domovra/run.sh
#!/usr/bin/with-contenv bashio
set -euo pipefail

# Dossier persistant
mkdir -p /data

# La DB reste au même endroit
export DB_PATH="/data/domovra.sqlite3"

# ⚠️ Important :
# Les seuils WARNING_DAYS / CRITICAL_DAYS ne sont PLUS lus depuis l’add-on.
# Ils sont maintenant gérés dans l’UI Domovra (/settings) et stockés dans /data/settings.json.
# On n’exporte donc plus ces variables ici.

bashio::log.info "Starting Domovra (DB_PATH=${DB_PATH})"
cd /app

# Lancement de l’API (derrière Ingress)
# --proxy-headers recommandé derrière le proxy du Supervisor
exec python3 -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8099 \
  --proxy-headers
