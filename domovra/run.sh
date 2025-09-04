# domovra/run.sh
#!/usr/bin/with-contenv bash
set -euo pipefail

# --------- Préparation ---------
mkdir -p /data
export DB_PATH="/data/domovra.sqlite3"

echo "[Domovra] DB_PATH=${DB_PATH}"

# Trouve le répertoire applicatif
if [ -d "/opt/app" ]; then
  APP_DIR="/opt/app"
elif [ -d "/app" ]; then
  APP_DIR="/app"
else
  echo "[Domovra] ERREUR: répertoire applicatif introuvable (/opt/app ou /app manquant)"
  exit 1
fi
cd "$APP_DIR"

# ✅ Exporte la version depuis config.json si dispo (fallback ENV)
if [ -z "${DOMOVRA_VERSION:-}" ] && [ -f "$APP_DIR/config.json" ]; then
  DOMOVRA_VERSION="$(python3 - <<'PY' "$APP_DIR/config.json" 2>/dev/null || true)
import json, sys
try:
    with open(sys.argv[1], 'r', encoding='utf-8') as f:
        print(json.load(f).get('version',''))
except Exception:
    pass
PY
"
  export DOMOVRA_VERSION
  echo "[Domovra] Version détectée: ${DOMOVRA_VERSION:-n/a}"
else
  echo "[Domovra] Version (ENV): ${DOMOVRA_VERSION:-n/a}"
fi

# Détermine le module à lancer (app.main:app prioritaire)
if [ -f "$APP_DIR/app/main.py" ]; then
  MODULE="app.main:app"
elif [ -f "$APP_DIR/main.py" ]; then
  MODULE="main:app"
else
  echo "[Domovra] ERREUR: impossible de trouver main.py (ni app/main.py ni main.py)"
  exit 1
fi
echo "[Domovra] Module = ${MODULE}"
echo "[Domovra] APP_DIR = ${APP_DIR}"

# Trouve uvicorn (venv ou global)
if [ -x "/opt/venv/bin/uvicorn" ]; then
  UVICORN="/opt/venv/bin/uvicorn"
else
  UVICORN="$(command -v uvicorn || true)"
fi

# --------- Lancement ---------
if [ -n "${UVICORN:-}" ]; then
  exec "${UVICORN}" "${MODULE}" \
    --host 0.0.0.0 \
    --port 8099 \
    --app-dir "${APP_DIR}" \
    --proxy-headers
else
  echo "[Domovra] uvicorn binaire introuvable, fallback python -m uvicorn"
  exec python3 -m uvicorn "${MODULE}" \
    --host 0.0.0.0 \
    --port 8099 \
    --app-dir "${APP_DIR}" \
    --proxy-headers
fi
