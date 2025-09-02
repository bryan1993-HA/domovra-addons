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
  # uvicorn binaire dispo
  exec "${UVICORN}" "${MODULE}" \
    --host 0.0.0.0 \
    --port 8099 \
    --app-dir "${APP_DIR}" \
    --proxy-headers
else
  # fallback via python -m uvicorn
  echo "[Domovra] uvicorn binaire introuvable, fallback python -m uvicorn"
  exec python3 -m uvicorn "${MODULE}" \
    --host 0.0.0.0 \
    --port 8099 \
    --app-dir "${APP_DIR}" \
    --proxy-headers
fi
