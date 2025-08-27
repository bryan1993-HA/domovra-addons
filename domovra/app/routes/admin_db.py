from __future__ import annotations
order_by: str | None = Query(None),
desc: bool = Query(True),

"""Exporte la table au format CSV (UTF-8, séparateur ',')."""
with _conn() as c:
exists = c.execute(
"SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name=?",
(table,),
).fetchone()["n"]
if not exists:
raise HTTPException(status_code=404, detail=f"Table '{table}' introuvable")


cols_rows = c.execute(f"PRAGMA table_info({table})").fetchall()
columns = [r["name"] for r in cols_rows]


order = order_by if order_by in columns else None
order_sql = f" ORDER BY {order} {'DESC' if desc else 'ASC'}" if order else " ORDER BY rowid DESC"


rows = c.execute(f"SELECT * FROM {table}{order_sql}").fetchall()


# buffer CSV
buf = io.StringIO()
writer = csv.DictWriter(buf, fieldnames=columns)
writer.writeheader()
for r in rows:
writer.writerow(dict(r))
buf.seek(0)


return StreamingResponse(
iter([buf.getvalue().encode("utf-8")]),
media_type="text/csv",
headers={"Content-Disposition": f"attachment; filename={table}.csv"},
)