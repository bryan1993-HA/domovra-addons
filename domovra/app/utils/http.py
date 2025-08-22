from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from ..settings_store import load_settings

def nocache_html(html: str) -> HTMLResponse:
    return HTMLResponse(html, headers={
        "Cache-Control":"no-store, no-cache, must-revalidate, max-age=0",
        "Pragma":"no-cache",
        "Expires":"0",
    })

def ingress_base(request: Request) -> str:
    base = request.headers.get("X-Ingress-Path") or "/"
    if not base.endswith("/"):
        base += "/"
    return base

def render(templates_env, name: str, **ctx) -> HTMLResponse:
    if "SETTINGS" not in ctx:
        ctx["SETTINGS"] = load_settings()
    tpl = templates_env.get_template(name)
    return nocache_html(tpl.render(**ctx))

def redirect(base: str, path: str, params: str | None = None) -> RedirectResponse:
    url = base + path
    if params:
        url = f"{url}?{params}"
    return RedirectResponse(url, status_code=303, headers={"Cache-Control":"no-store"})
