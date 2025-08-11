ARG BUILD_FROM
FROM $BUILD_FROM

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/opt/app \
    PYTHONPATH=/opt/app

# Dépendances de base
RUN apk add --no-cache python3 py3-pip

WORKDIR ${APP_HOME}
COPY app ${APP_HOME}/
RUN pip3 install --no-cache-dir fastapi uvicorn[standard] jinja2

# Script de démarrage
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8099
CMD ["/run.sh"]
