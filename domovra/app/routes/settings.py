from flask import Blueprint, render_template, request, redirect, url_for
from ..settings_store import load_settings, save_settings

bp = Blueprint("settings", __name__, url_prefix="/settings")

@bp.get("/")
def page():
    settings = load_settings()
    return render_template("settings.html", SETTINGS=settings)

@bp.post("/save")
def save():
    form = request.form

    new_vals = {
        "theme": form.get("theme", "auto"),
        "table_mode": form.get("table_mode", "scroll"),
        "sidebar_compact": (form.get("sidebar_compact") == "on"),
        "default_shelf_days": int(form.get("default_shelf_days") or 90),
        "low_stock_default": int(form.get("low_stock_default") or 1),
    }
    save_settings(new_vals)
    return redirect(url_for("settings.page"))
