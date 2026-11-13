from fastapi import APIRouter, Request

from app.db import db
from app.templating import templates

router = APIRouter()


@router.get("/runs")
def runs(request: Request):
    with db() as conn:
        rows = conn.execute("SELECT id, kind, status, started_at::timestamp(0) AS started_at, created_by, report FROM load_runs ORDER BY id DESC LIMIT 50").fetchall()
    return templates.TemplateResponse(request, "runs.html", {"rows": rows})
