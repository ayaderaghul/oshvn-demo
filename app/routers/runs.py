from fastapi import APIRouter

from app.db import db
from app.views import E, page

router = APIRouter()


@router.get("/runs")
def runs():
    with db() as conn:
        rows = conn.execute("SELECT id, kind, status, started_at::timestamp(0), created_by, report FROM load_runs ORDER BY id DESC LIMIT 50").fetchall()
    t = ["<h1>Nhật ký nạp</h1><div class='panel scroll'><table><tr><th>#</th><th>Loại</th><th>Kết quả</th><th>Lúc</th><th>Người</th><th>Chi tiết</th></tr>"]
    for r in rows:
        rep = r[5] or {}
        det = rep.get("file", "")
        if "chunks" in rep:
            c = rep["chunks"] if isinstance(rep["chunks"], dict) else {}
            det += f" — {c.get('new', 0)} mới, {c.get('changed', 0)} đổi, {c.get('unchanged', 0)} không đổi, {c.get('retired', 0)} ngừng"
        if rep.get("reason"): det += f" — {rep['reason']}"
        cls = {"applied": "ok", "rejected": "no", "dry_run": ""}.get(r[2], "")
        t.append(f"<tr><td>{r[0]}</td><td>{E(r[1])}</td><td><span class='pill {cls}'>{E(r[2])}</span></td><td>{r[3]}</td><td>{E(r[4] or '')}</td><td style='font-size:.85rem'>{E(det)}</td></tr>")
    t.append("</table></div>")
    return page("Nhật ký nạp", "".join(t), "/runs")
