ARG BUILD_FROM
FROM $BUILD_FROM

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/opt/app \
    PYTHONPATH=/opt/app \
    VENV_PATH=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# Dépendances système + venv
RUN apk add --no-cache python3 py3-pip

# App
WORKDIR ${APP_HOME}
COPY app ${APP_HOME}/

# Créer un virtualenv et y installer les deps Python
RUN python3 -m venv ${VENV_PATH} \
 && ${VENV_PATH}/bin/pip install --no-cache-dir "fastapi" "uvicorn[standard]" "jinja2"

# Script de démarrage
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8099
CMD ["/run.sh"]
