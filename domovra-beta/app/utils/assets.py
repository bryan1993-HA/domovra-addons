import os, hashlib, shutil
from functools import lru_cache

# BASE_DIR = racine du dossier app/ (où se trouvent templates/static)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))

def _abs_path(relpath: str) -> str:
    p = relpath.lstrip("/\\")
    return os.path.join(BASE_DIR, p)

def _file_hash(abs_path: str) -> str:
    h = hashlib.md5()
    with open(abs_path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:10]

@lru_cache(maxsize=256)
def _version_for(abs_path: str, mtime: float) -> str:
    return _file_hash(abs_path)

def asset_ver(relpath: str) -> str:
    abs_path = _abs_path(relpath)
    try:
        mtime = os.path.getmtime(abs_path)
    except FileNotFoundError:
        return "dev"
    return _version_for(abs_path, mtime)

def ensure_hashed_asset(src_rel: str) -> str:
    abs_src = _abs_path(src_rel)
    hv = asset_ver(src_rel)
    if hv == "dev":
        return src_rel

    dirname, basename = os.path.split(src_rel)
    name, ext = os.path.splitext(basename)
    hashed_name = f"{name}-{hv}{ext}"
    dst_rel = os.path.join(dirname, hashed_name)
    abs_dst = _abs_path(dst_rel)

    if (not os.path.isfile(abs_dst)) or (os.path.getsize(abs_dst) != os.path.getsize(abs_src)):
        os.makedirs(os.path.dirname(abs_dst), exist_ok=True)
        shutil.copy2(abs_src, abs_dst)

    # Nettoyage best effort
    try:
        abs_dir = _abs_path(dirname)
        for fname in os.listdir(abs_dir):
            if fname.startswith(name + "-") and fname.endswith(ext) and fname != hashed_name:
                try:
                    os.remove(os.path.join(abs_dir, fname))
                except Exception:
                    pass
    except Exception:
        pass

    return dst_rel
