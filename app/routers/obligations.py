import json

from fastapi import APIRouter, Request

from app.db import db
from app.rules import FIELDS, SECTORS
from app.templating import templates

router = APIRouter()


@router.get("/obligations")
def obligations(request: Request):
    qp = request.query_params
    sector = qp.get("sector", "xd")
    try:
        n = min(max(int(qp.get("n") or 350), 1), 10_000_000)
    except ValueError:
        n = 350
    prof = {"sector": sector, "g36": bool(SECTORS.get(sector, SECTORS["khac"])[1]), "g37": bool(SECTORS.get(sector, SECTORS["khac"])[2]),
            "n": n, "role": qp.get("role", "contractor")}
    defaults = {"strict": True, "hazardous": True, "kcn": True}
    for f, _, t in FIELDS:
        if t == "bool":
            prof[f] = (qp.get(f) == "1") if "n" in qp else defaults.get(f, False)
    with db() as conn:
        rows = conn.execute("""SELECT id, topic, kind, duty_vi, action_vi, article_ref, penalties, change_note,
                                      explain_rule(applies_when, %s::jsonb) AS ex, reviewed, needs_review,
                                      to_jsonb(o)->>'reviewed_by' AS reviewed_by, review_reason
                               FROM obligations o WHERE sources IS NOT NULL ORDER BY id""", (json.dumps(prof),)).fetchall()
        rows = [r._replace(ex=r.ex if isinstance(r.ex, dict) else {}, penalties=r.penalties if isinstance(r.penalties, list) else [])
                for r in rows]
        sample = conn.execute("SELECT count(*) FROM obligations WHERE sources IS NULL").fetchone()[0]
    rows.sort(key=lambda r: (not r.ex.get("applies"), r.id))
    ctx = {"prof": prof, "rows": rows, "sample": sample, "applied": sum(1 for r in rows if r.ex.get("applies")),
           "sectors": SECTORS, "fields": FIELDS}
    return templates.TemplateResponse(request, "obligations.html", ctx)
