from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse

app = FastAPI()

HTML = """
<html>
  <head><meta charset="utf-8"><title>Domovra</title></head>
  <body>
    <h1>Bienvenue sur Domovra !</h1>
    <p>Votre gestionnaire de stock domotique est prêt 🚀</p>
  </body>
</html>
"""

@app.get("/ping", response_class=PlainTextResponse)
def ping():
    return "ok"

# Racines possibles (Ingress peut appeler //)
@app.get("/", response_class=HTMLResponse)
@app.get("//", response_class=HTMLResponse)
def root():
    return HTML

# Fallback: tout autre chemin → redirige vers la racine
@app.get("/{path:path}", include_in_schema=False)
def fallback(path: str):
    return RedirectResponse("/")
