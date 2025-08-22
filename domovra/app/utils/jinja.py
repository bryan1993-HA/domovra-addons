from jinja2 import Environment, FileSystemLoader, select_autoescape
from .assets import asset_ver, ensure_hashed_asset
from ..config import START_TS

def _pretty_num(x) -> str:
    try:
        f = float(x)
    except Exception:
        return str(x)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    s = f"{f:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"

def pluralize_fr(unit: str, qty) -> str:
    try:
        q = float(qty)
    except Exception:
        q = qty
    try:
        is_one = abs(float(q) - 1.0) < 1e-9
    except Exception:
        is_one = (q == 1)
    if not unit:
        return unit
    u = str(unit)
    if is_one:
        return u
    invariants = {"kg","g","mg","l","L","ml","cl","m","cm","mm","%","°C","°F"}
    if u in invariants:
        return u
    irregulars = {
        "pièce":"pièces","piece":"pieces","sachet":"sachets","boîte":"boîtes","boite":"boites",
        "bouteille":"bouteilles","canette":"canettes","paquet":"paquets","tranche":"tranches",
        "gousse":"gousses","pot":"pots","brique":"briques","barquette":"barquettes",
        "œuf":"œufs","oeuf":"oeufs","unité":"unités","unite":"unites","pack":"packs",
        "lot":"lots","bocal":"bocaux","journal":"journaux"
    }
    if u in irregulars.values() or u.endswith(("s","x")):
        return u
    if u in irregulars:
        return irregulars[u]
    if u.endswith("al"):
        return u[:-2] + "aux"
    if u.endswith("eau"):
        return u + "x"
    return u + "s"

def fmt_qty(qty, unit: str) -> dict:
    try:
        q = float(qty or 0)
    except Exception:
        q = 0.0
    u = (unit or "").strip()
    if u == "l":
        u = "L"
    if u == "g":
        if q >= 1000:
            q /= 1000.0
            u = "kg"
        return {"v": _pretty_num(q), "u": u}
    if u == "ml":
        if q >= 1000:
            q /= 1000.0
            u = "L"
        return {"v": _pretty_num(q), "u": u}
    if u in ("kg","L"):
        return {"v": _pretty_num(q), "u": u}
    return {"v": _pretty_num(q), "u": u}

def build_jinja_env():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape()
    )
    # globals
    env.globals["asset_ver"] = asset_ver
    env.globals["ASSET_VER"] = asset_ver("static/css/domovra.css")
    env.globals["ASSET_CSS_PATH"] = ensure_hashed_asset("static/css/domovra.css")
    env.globals["START_TS"] = START_TS
    env.globals["fmt_qty"] = fmt_qty
    # filters
    env.filters["pretty_num"] = _pretty_num
    env.filters["pluralize_fr"] = pluralize_fr
    return env
