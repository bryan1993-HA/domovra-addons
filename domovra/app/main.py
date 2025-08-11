from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <html>
        <head>
            <title>Domovra</title>
        </head>
        <body>
            <h1>Bienvenue sur Domovra !</h1>
            <p>Votre gestionnaire de stock domotique est prêt 🚀</p>
        </body>
    </html>
    """
