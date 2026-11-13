import json

from fastapi import APIRouter, Request

from app.db import db
from app.rules import FIELDS, SECTORS, nice, penalty_label
from app.views import E, page

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
                                      to_jsonb(o)->>'reviewed_by', review_reason
                               FROM obligations o WHERE sources IS NOT NULL ORDER BY id""", (json.dumps(prof),)).fetchall()
        rows = [r[:8] + ((r[8] if isinstance(r[8], dict) else {}),) + r[9:] for r in rows]
        sample = conn.execute("SELECT count(*) FROM obligations WHERE sources IS NULL").fetchone()[0]
    form = ["<form class='panel' method='get'><div class='row' style='margin-bottom:8px'>",
            "<label>Ngành<br><select name='sector'>" + "".join(f"<option value='{k}' {'selected' if k == sector else ''}>{E(v[0])}</option>" for k, v in SECTORS.items()) + "</select></label>",
            f"<label>Số lao động<br><input name='n' type='number' min='1' value='{prof['n']}' style='width:110px'></label>",
            "<label>Vai trò<br><select name='role'>" + "".join(f"<option value='{k}' {'selected' if k == prof['role'] else ''}>{v}</option>" for k, v in
                                                     (("contractor", "Nhà thầu thi công"), ("owner", "Chủ đầu tư"), ("none", "Không tham gia XD"))) + "</select></label></div><div class='row'>"]
    for f, l, t in FIELDS:
        if t == "bool":
            form.append(f"<label class='c'><input type='checkbox' name='{f}' value='1' {'checked' if prof[f] else ''}>{E(l)}</label>")
    form.append("<button>Áp dụng</button></div></form>")
    ap = [r for r in rows if r[8].get("applies")]
    table = ["<div class='panel scroll'><table><tr><th>Mã</th><th>Chủ đề</th><th>Điều khoản</th><th>Nội dung</th><th>Vì sao</th><th>Phạt</th></tr>"]
    for r in sorted(rows, key=lambda r: (not r[8].get("applies"), r[0])):
        why = (r[8].get("reasons") if r[8].get("applies") else r[8].get("missing")) or []
        pen = "<br>".join(E(penalty_label(p)) for p in (r[6] if isinstance(r[6], list) else [])[:2])
        tag = "<span class='pill ok'>Áp dụng</span>" if r[8].get("applies") else "<span class='pill'>N/A</span>"
        if r[9]: tag += f" <span class='pill ok'>đã duyệt bởi {E(r[11] or '?')}</span>"
        if r[10]: tag += f" <span class='pill no' title='{E(r[12] or '')}'>cần xem lại</span>"
        if r[7]: tag += " <span class='pill no'>đã thay đổi</span>"
        table.append(f"<tr style='{'' if r[8].get('applies') else 'opacity:.55'}'><td>{E(r[0])}<br>{tag}</td><td>{E(r[1] or '')}</td><td style='font-size:.82rem'>{E(r[5] or '')}</td>"
                     f"<td>{E(r[3] or '')}<br><span class='muted' style='font-size:.85rem'>→ {E(r[4] or '')}</span></td>"
                     f"<td style='font-size:.82rem'>{'<br>'.join(E(nice(w)) for w in why)}</td><td style='font-size:.8rem'>{pen}</td></tr>")
    table.append("</table></div>")
    head = (f"<h1>Nghĩa vụ và rule engine</h1><p class='muted'>Mỗi nghĩa vụ được kiểm tra bằng hàm <code>explain_rule()</code> chạy trong Postgres với hồ sơ bên dưới. Không dùng AI.</p>"
            + "".join(form)
            + f"<div class='kpis' style='margin-bottom:12px'><div class='kpi'><b>{len(ap)}</b>áp dụng</div><div class='kpi'><b>{len(rows) - len(ap)}</b>không áp dụng</div></div>")
    if not rows:
        head += f"<div class='panel'>Chưa có nghĩa vụ nào có căn cứ (<code>sources</code>). Nạp bằng <code>python loader.py obligations data/obligations.json</code>. ({sample} nghĩa vụ mẫu cũ không hiển thị.)</div>"
    return page("Nghĩa vụ", head + ("".join(table) if rows else ""), "/obligations")
