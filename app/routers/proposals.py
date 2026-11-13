import hmac, json

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from app.db import db, writer
from app.rules import rule_text, src_label
from app.security import auth, csrf_token, same_origin
from app.views import E, STATUS_VI, agent_cell, counts, page, status_pill, word_diff

router = APIRouter()


@router.get("/proposals")
def proposals():
    with db() as conn:
        if conn.execute("SELECT to_regclass('public.load_proposals')").fetchone()[0] is None:
            return page("Chờ duyệt", "<h1>Chờ duyệt</h1><div class='panel'>Chưa có bảng đề xuất. Chạy <code>python loader.py migrate</code>.</div>", "/proposals")
        rows = conn.execute("""SELECT id, status, doc_code, file_name, created_at::timestamp(0), created_by, reviewed_by,
                                      report->'chunks' AS chunks, report->'accepted' AS accepted, jsonb_array_length(coalesce(report->'issues','[]')) AS n_issues,
                                      report->'agent'->>'verdict' AS verdict, report->'agent'->>'comment' AS comment, report->'agent'->>'route' AS route,
                                      coalesce(to_jsonb(lp)->>'kind', 'documents') AS kind,
                                      jsonb_array_length(coalesce(payload->'obligations','[]')) AS n_obligations,
                                      jsonb_array_length(coalesce(report->'rejected','[]')) AS n_rejected, report->>'flagged' AS flagged
                               FROM load_proposals lp ORDER BY (status='pending') DESC, id DESC LIMIT 100""").fetchall()
    t = ["<h1>Đề xuất chờ duyệt</h1><p class='muted'>Văn bản luật (agent00, <code>loader.py propose</code>) và nghĩa vụ (agent01). "
         "Duyệt ở đây, rồi chạy <code>python loader.py apply</code> để nạp.</p><div class='panel scroll'><table>"
         "<tr><th>#</th><th>Trạng thái</th><th>Văn bản</th><th>Thay đổi</th><th style='min-width:280px'>Nhận xét của agent</th><th>Ngoại lệ</th><th>Tạo</th><th>Duyệt</th></tr>"]
    for r in rows:
        t.append(f"<tr><td><a href='/proposals/{r[0]}'>#{r[0]}</a></td><td>{status_pill(r[1])}</td>"
                 f"<td><a href='/proposals/{r[0]}'><b>{E(r[2])}</b></a><br><span class='muted' style='font-size:.8rem'>{E(r[3] or '')}</span></td>"
                 + (f"<td><b>{r[14]}</b> nghĩa vụ</td><td style='font-size:.85rem'><span class='pill'>agent01</span> "
                    f"{r[14]} đạt kiểm tra · {r[15]} bị loại · <b>{E(str(r[16] or 0))}</b> có ý không có căn cứ</td>" if r[13] == "obligations" else
                    f"<td>{counts(r[7])}</td>" + agent_cell(r[10], r[11], r[12])) +
                 f"<td style='font-size:.82rem'>{E(', '.join(x.split(':')[0] for x in (r[8] or []))) or '—'}<br><span class='muted'>{r[9]} ghi chú parser</span></td>"
                 f"<td style='font-size:.82rem'>{r[4]}<br>{E(r[5] or '')}</td><td>{E(r[6] or '')}</td></tr>")
    t.append("</table></div>" if rows else "<tr><td colspan=8 class='muted'>Chưa có đề xuất nào.</td></tr></table></div>")
    return page("Chờ duyệt", "".join(t), "/proposals")


@router.get("/proposals/{pid}")
def proposal(pid: int, err: str = ""):
    with db() as conn:
        k = conn.execute("SELECT coalesce(to_jsonb(lp)->>'kind','documents') AS kind FROM load_proposals lp WHERE id=%s", (pid,)).fetchone()
    if k and k.kind == "obligations":
        return obligation_proposal(pid, err)
    with db() as conn:
        r = conn.execute("""SELECT id, status, doc_code, file_name, options, report, payload->'result'->'chunks' AS chunks,
                                   payload->>'title' AS title, created_at::timestamp(0) AS created_at, created_by, reviewed_by, reviewed_at::timestamp(0) AS reviewed_at,
                                   review_note, apply_report, payload->>'dtype' AS dtype
                            FROM load_proposals WHERE id=%s""", (pid,)).fetchone()
        if not r:
            raise HTTPException(404)
        exists = conn.execute("SELECT id FROM legal_documents WHERE number=%s", (r[2],)).fetchone()
    rep, chunks = r[5] or {}, r[6] or []
    lab = STATUS_VI.get(r[1], (str(r[1]), ""))[0]
    # What the database held when the proposal was made (stored in the report), not what it holds now:
    # the page must read the same before and after review / apply, so it can be checked later (QC).
    was_new = rep.get("document") == "mới" if rep.get("document") else not exists
    c = rep.get("chunks") if isinstance(rep.get("chunks"), dict) else {}
    out = [f"<p><a href='/proposals'>← Danh sách đề xuất</a></p><div class='eyebrow'>Đề xuất #{r[0]}</div>",
           f"<h1>{E(r[2])} {status_pill(r[1])}</h1>",
           f"<p class='muted' style='margin:0 0 10px'>{E(r[7] or '')}</p>",
           f"<p class='muted' style='font-size:.85rem'>File {E(r[3] or '')} · tạo {r[8]} bởi {E(r[9] or '?')} · "
           f"tùy chọn: {E(json.dumps({k: v for k, v in (r[4] or {}).items() if v}, ensure_ascii=False))} · "
           + ("lúc đề xuất: văn bản mới, chưa có trong database" if was_new else "lúc đề xuất: văn bản đã có, đây là bản cập nhật")
           + (f" · <a href='/doc/{exists[0]}'>xem bản hiện có trong database</a>" if exists else "") + "</p>"]
    if err in REVIEW_ERRORS:
        out.append(f"<p class='err'>{E(REVIEW_ERRORS[err])}</p>")
    out.append(f"<div class='kpis' style='margin-bottom:12px'><div class='kpi'><b>{E(str(c.get('new', 0)))}</b>khoản mới</div>"
               f"<div class='kpi'><b>{E(str(c.get('changed', 0)))}</b>đổi chữ</div><div class='kpi'><b>{E(str(c.get('unchanged', 0)))}</b>không đổi</div>"
               f"<div class='kpi'><b>{E(str(c.get('retired', 0)))}</b>ngừng dùng</div></div>")
    # 0. agent00's notes (if the proposal came from the agent)
    ag = rep.get("agent")
    if ag:
        vlab, vcls = {"ok": ("có thể duyệt", "ok"), "check": ("cần xem kỹ", "no"), "reject": ("không nên nạp", "no")}.get(ag.get("verdict"), ("?", ""))
        o = ag.get("ocr") or {}
        nc = "".join(f"<tr><td>trang {E(str(x.get('page')))}</td><td><del>{E(', '.join(map(str, x.get('removed') or [])))}</del></td>"
                     f"<td><ins>{E(', '.join(map(str, x.get('added') or [])))}</ins></td></tr>" for x in o.get("number_changes", []))
        uns = "".join(f"<li>trang {E(str(u.get('page')))}: {E(str(u.get('note', '')))}</li>" for u in o.get("unsure", []))
        low = ", ".join(f"{E(str(w.get('word', '')))} <span class='muted'>(tr.{E(str(w.get('page')))})</span>" for w in o.get("low_conf", [])[:60])
        out.append(f"<div class='panel' style='border-color:var(--accent)'><h3 style='margin-top:0'>Nhận xét của agent00 "
                   f"<span class='pill {vcls}'>{vlab}</span></h3><p>{E(ag.get('comment', ''))}</p>"
                   f"<details><summary>Các bước agent đã làm ({len(ag.get('steps', []))})</summary><ol style='font-size:.88rem'>"
                   + "".join(f"<li>{E(x)}</li>" for x in ag.get("steps", [])) + "</ol></details>"
                   + (f"<h4>Văn bản OCR — đối chiếu với bản scan</h4><p class='muted' style='font-size:.85rem'>Những con số khác nhau giữa OCR thô và bản đã làm sạch. "
                      f"Mỗi dòng phải được kiểm tra trên bản scan.</p><div class='scroll'><table><tr><th>Trang</th><th>OCR thô</th><th>Sau khi làm sạch</th></tr>{nc or '<tr><td colspan=3 class=muted>Không có con số nào bị đổi.</td></tr>'}</table></div>"
                      + (f"<p style='font-size:.88rem'><b>Model không chắc:</b></p><ul style='font-size:.88rem'>{uns}</ul>" if uns else "")
                      + (f"<details><summary>Từ OCR độ tin cậy thấp ({len(o.get('low_conf', []))})</summary><p style='font-size:.85rem'>{low}</p></details>" if low else "")
                      if o else "")
                   + f"<p class='muted' style='font-size:.78rem;margin-bottom:0'>{E(ag.get('agent', ''))} · {E(ag.get('provider', ''))}/{E(ag.get('model', ''))} · "
                     f"{E(str(ag.get('calls', 0)))} lần gọi · {E(str(ag.get('tokens', 0)))} token. Nhận xét chỉ để tham khảo; kiểm tra tự động và người duyệt mới là quyết định.</p></div>")
    # 1. checks
    acc = set(rep.get("accepted") or [])
    rows = "".join(f"<tr><td>{'<span class=\"pill ok\">ĐẠT</span>' if ch['ok'] else ('<span class=\"pill no\">LỖI · chấp nhận</span>' if ch['name'] in acc else '<span class=\"pill no\">LỖI</span>')}</td>"
                   f"<td>{E(ch['name'])}</td><td style='font-size:.85rem'>{E(ch['detail'])}</td></tr>" for ch in rep.get("checks", []))
    out.append(f"<div class='panel'><h3 style='margin-top:0'>1. Kiểm tra tự động</h3><div class='scroll'><table>{rows}</table></div>"
               + ("<p class='muted' style='font-size:.85rem;margin-bottom:0'>Kiểm tra được chấp nhận là ngoại lệ đã biết. Hãy chắc rằng phần chưa gán chỉ là tiêu đề, căn cứ, nơi nhận.</p>" if acc else "") + "</div>")
    # 2. what changes in the database
    ch = rep.get("changes") or []
    if ch:
        items = []
        for x in ch:
            if x['key'][0] in (None, "None", ""):
                key = "Dòng dữ liệu mẫu cũ (tạo tay khi dựng pilot, không theo cấu trúc Điều/khoản)"
            elif str(x['key'][0]).startswith("PL"):
                key = f"Phụ lục {str(x['key'][0])[2:]}, mục {x['key'][1]}"
            else:
                key = f"Điều {x['key'][0]}" + (f", khoản {x['key'][1]}" if x['key'][1] else "")
            if x["change"] == "changed": body = word_diff(x.get("old"), x.get("new"))
            elif x["change"] == "new": body = f"<ins>{E(x.get('new', ''))}</ins>"
            else: body = f"<del>{E(x.get('old', ''))}</del>"
            tag = E({"changed": "đổi chữ", "new": "mới", "retired": "ngừng dùng"}.get(x.get("change"), str(x.get("change"))))
            items.append(f"<div class='art'><b>{E(key)}</b> <span class='pill'>{tag}</span><p class='law' style='font-size:.92rem'>{body}</p></div>")
        out.append(f"<div class='panel'><h3 style='margin-top:0'>2. Thay đổi so với database ({len(ch)})</h3>{''.join(items)}</div>")
    elif not was_new:
        out.append("<div class='panel'><h3 style='margin-top:0'>2. Thay đổi so với database</h3><p class='muted'>Không có khoản nào đổi chữ.</p></div>")
    # 3. parser notes
    iss = rep.get("issues") or []
    if iss:
        out.append(f"<div class='panel'><details><summary>3. Ghi chú của parser ({len(iss)}) — chỗ nên liếc qua</summary><ul style='font-size:.88rem'>"
                   + "".join(f"<li>{E(i)}</li>" for i in iss) + "</ul></details></div>")
    # 4. full parsed text
    byd, order = {}, []
    for x in chunks:
        k = str(x.get("dieu"))
        if k not in byd: byd[k] = []; order.append(k)
        byd[k].append(x)
    arts = []
    for k in order:
        x0 = byd[k][0]
        head = (x0.get("label") or f"Điều {k}") + ". " + (x0.get("dieu_title") or "")
        parts = "".join(f"<div class='k'><b>{E(x.get('item_label') or (('Khoản ' + str(x['khoan'])) if x.get('khoan') else 'Đoạn'))}</b>"
                        f"<p class='law'>{E(x.get('text', ''))}</p></div>" for x in byd[k])
        arts.append(f"<div class='art'><h3>{E(head)}</h3>{parts}</div>")
    out.append(f"<div class='panel'><details{' open' if was_new else ''}><summary>4. Toàn văn đã tách ({len(order)} điều/phụ lục, {len(chunks)} khoản)</summary>{''.join(arts)}</details></div>")
    # 5. decision
    if r[1] == "pending":
        tok = csrf_token(pid)
        out.append(f"""<div class='panel'><h3 style='margin-top:0'>5. Quyết định</h3>
<form method='post' action='/proposals/{pid}/review'><input type='hidden' name='token' value='{tok}'>
<label>Ghi chú (tùy chọn)<br><textarea name='note' placeholder='ví dụ: đã đối chiếu số hiệu viện dẫn với bản scan'></textarea></label>
<div class='row' style='margin-top:8px'><button name='decision' value='approved'>Duyệt — cho phép nạp</button>
<button class='ghost' name='decision' value='rejected'>Từ chối</button></div>
<p class='muted' style='font-size:.82rem'>Duyệt chưa ghi gì vào database. Văn bản chỉ được nạp khi chạy <code>python loader.py apply</code>.</p></form></div>""")
    else:
        out.append(f"<div class='panel'><h3 style='margin-top:0'>5. Quyết định</h3><p>{E(lab)}"
                   + (f" bởi <b>{E(r[10])}</b> lúc {r[11]}" if r[10] else "") + "</p>"
                   + (f"<p class='law'>{E(r[12])}</p>" if r[12] else "")
                   + (f"<p class='muted' style='font-size:.85rem'>Kết quả nạp: {E(json.dumps(r[13], ensure_ascii=False))}</p>" if r[13] else "") + "</div>")
    return page(f"Đề xuất #{pid}", "".join(out), "/proposals")


REVIEW_ERRORS = {"name": "Đăng nhập với tên của bạn (ô tên đăng nhập) để ghi người duyệt.",
                 "db": "Không ghi được quyết định: đề xuất có thể đã được duyệt hoặc bị thay thế. Tải lại trang."}


@router.post("/proposals/{pid}/review")
async def review(pid: int, request: Request, user: str = Depends(auth)):
    form = await request.form()
    if not same_origin(request):
        raise HTTPException(403, "Sai nguồn gửi")
    if not hmac.compare_digest(str(form.get("token", "")), csrf_token(pid)):
        raise HTTPException(403, "Mã xác nhận không đúng — tải lại trang rồi thử lại")
    decision = form.get("decision")
    if decision not in ("approved", "rejected"):
        raise HTTPException(400)
    if not user:
        return RedirectResponse(f"/proposals/{pid}?err=name", 303)
    note, excl = str(form.get("note", ""))[:2000], sorted({str(x) for x in form.getlist("exclude")})
    return await run_in_threadpool(record_review, pid, decision, user, note, excl)


def record_review(pid, decision, user, note, excl):
    try:
        with writer() as conn:
            row = conn.execute("SELECT coalesce(to_jsonb(lp)->>'kind','documents'), payload FROM load_proposals lp WHERE id=%s", (pid,)).fetchone()
            if not row:
                raise HTTPException(404)
            if row[0] == "obligations":   # the stored kind decides, not a field of the form
                ids = {str(o.get("id")) for o in (row[1] or {}).get("obligations", []) if isinstance(o, dict)}
                unknown = [x for x in excl if x not in ids]
                if unknown:
                    raise HTTPException(400, "Mã nghĩa vụ không có trong đề xuất: " + ", ".join(unknown[:5]))
                conn.execute("SELECT review_proposal_items(%s, %s, %s, %s, %s::jsonb)", (pid, decision, user, note, json.dumps(excl)))
            elif excl:
                raise HTTPException(400, "Đề xuất văn bản không loại được từng mục")
            else:
                conn.execute("SELECT review_proposal(%s, %s, %s, %s)", (pid, decision, user, note))
    except psycopg.Error:
        return RedirectResponse(f"/proposals/{pid}?err=db", 303)
    return RedirectResponse(f"/proposals/{pid}", 303)


def obligation_proposal(pid, err):
    with db() as conn:
        r = conn.execute("""SELECT id, status, doc_code, payload, report, created_at::timestamp(0), created_by, reviewed_by,
                                   reviewed_at::timestamp(0), review_note, apply_report, to_jsonb(lp)->'excluded' AS excluded
                            FROM load_proposals lp WHERE id=%s""", (pid,)).fetchone()
    if not r: raise HTTPException(404)
    payload, rep = r[3] or {}, r[4] or {}
    obls, texts, excluded = payload.get("obligations", []), payload.get("texts", {}), set(r[11] or [])
    lab = STATUS_VI.get(r[1], (str(r[1]), ""))[0]
    ag = rep.get("agent", {})
    pending = r[1] == "pending"
    tokens = ag.get("tokens", 0)
    out = [f"<p><a href='/proposals'>← Danh sách đề xuất</a></p><div class='eyebrow'>Đề xuất #{r[0]} · nghĩa vụ</div>",
           f"<h1>{E(r[2])} {status_pill(r[1])}</h1>",
           f"<p class='muted' style='font-size:.85rem'>Tạo {r[5]} bởi {E(r[6] or '?')} · {E(ag.get('agent', ''))} · soạn bằng {E(ag.get('draft_model', ''))}, "
           f"lọc và kiểm chứng bằng {E(ag.get('filter_model', ''))} · {E(str(ag.get('calls', 0)))} lần gọi · "
           f"{E(f'{tokens:,}' if isinstance(tokens, int) else str(tokens))} token</p>"]
    if err in REVIEW_ERRORS: out.append(f"<p class='err'>{E(REVIEW_ERRORS[err])}</p>")
    out.append(f"<div class='kpis' style='margin-bottom:12px'><div class='kpi'><b>{len(obls)}</b>nghĩa vụ đạt kiểm tra</div>"
               f"<div class='kpi'><b>{E(str(rep.get('flagged', 0)))}</b>có ý không có căn cứ</div><div class='kpi'><b>{len(rep.get('rejected', []))}</b>bị loại tự động</div>"
               f"<div class='kpi'><b>{len(rep.get('new_fields', []))}</b>đề nghị trường hồ sơ mới</div></div>")
    out.append("<div class='panel' style='font-size:.9rem'><b>Cách duyệt.</b> Mỗi nghĩa vụ đặt cạnh nguyên văn căn cứ. Đọc nội dung, điều kiện áp dụng và mức phạt; "
               "ý có viền vàng là ý model kiểm chứng cho là <b>không có trong căn cứ</b>. Nghĩa vụ chưa ổn thì tick <b>Loại</b>; phần còn lại được nạp khi duyệt.</div>")
    if pending:
        out.append(f"<form method='post' action='/proposals/{pid}/review'><input type='hidden' name='token' value='{csrf_token(pid)}'>")
    for o in obls:
        v = o.get("_verify") or {}
        uns, inf = v.get("unsupported") or [], v.get("inferred") or []
        am = o.get("_amended_by") or []
        def src_block(s):
            notes = [m for m in am if m["source"] == s]
            badge = "".join(f"<br><span class='pill no' style='white-space:normal'>{E(m['action'])}{(' điểm ' + E(m['diem'])) if m.get('diem') else ''} bởi {E(src_label(m['by']))}</span>" for m in notes)
            old = "opacity:.6;" if any(m["khoan"] is None or not m.get("diem") for m in notes) else ""
            return (f"<div class='k' style='grid-template-columns:150px minmax(0,1fr)'><b>{E(src_label(s))}{badge}</b><p class='law' style='font-size:.85rem;{old}'>"
                    f"{E((texts.get(f'{s[0]}|{s[1]}|' + ('' if s[2] is None else str(s[2]))) or '(không có nguyên văn)').split(chr(10), 1)[-1][:2500])}</p></div>")
        shown = {tuple(x) for x in o.get("sources", [])}
        srcs = "".join(src_block(s) for s in o.get("sources", []))
        for m in am:   # the amending clause's text, if the obligation did not already cite it
            if tuple(m["by"]) in shown: continue
            shown.add(tuple(m["by"]))
            t = texts.get(f"{m['by'][0]}|{m['by'][1]}|" + ("" if m["by"][2] is None else str(m["by"][2])), "")
            srcs += (f"<div class='k' style='grid-template-columns:150px minmax(0,1fr)'><b>{E(src_label(m['by']))}<br><span class='pill ok'>nội dung mới</span></b>"
                     f"<p class='law' style='font-size:.85rem'>{E(t.split(chr(10), 1)[-1][:3000])}</p></div>")
        pens = "".join(f"<li>{E(str(p.get('doc', '')))} Điều {E(str(p.get('dieu')))}" + (f" khoản {E(str(p.get('khoan')))}" if p.get('khoan') else "")
                       + (f" điểm {E(str(p.get('diem')))}" if p.get('diem') else "") + f": {E(p.get('text', ''))}</li>" for p in o.get("penalties") or [])
        flag = "border-color:var(--warn)" if uns else ""
        tick = (f"<label class='c' style='float:right'><input type='checkbox' name='exclude' value='{E(o['id'])}'> Loại</label>" if pending else
                ("<span class='pill no' style='float:right'>đã loại</span>" if o["id"] in excluded else ""))
        out.append(f"""<div class='panel' style='{flag}'>{tick}<h3 style='margin:0 0 4px'>{E(o['id'])} · {E(o.get('topic', ''))}
<span class='pill'>{E(o.get('kind', ''))}{(' · ' + E(o['freq'])) if o.get('freq') else ''}</span></h3>
<div class='grid' style='grid-template-columns:minmax(0,1fr) minmax(0,1fr)'><div>
<p style='margin:.3rem 0'><b>Nghĩa vụ:</b> {E(o.get('content', ''))}</p>
<p style='margin:.3rem 0'><b>Hành động:</b> {E(o.get('action', ''))}</p>
<p style='margin:.3rem 0'><b>Bằng chứng:</b> {E('; '.join(o.get('evidence') or []))}</p>
<p style='margin:.3rem 0'><b>Áp dụng khi:</b> {E(rule_text(o.get('applies_when')))}</p>
{f"<p style='margin:.3rem 0'><b>Tính cho DN:</b> {E(o['calc'])}</p>" if o.get('calc') else ''}
{f"<p style='margin:.3rem 0'><b>Thay đổi:</b> {E(o['change_note'])}</p>" if o.get('change_note') else ''}
<p style='margin:.3rem 0'><b>Mức phạt:</b></p><ul style='margin:0;font-size:.88rem'>{pens or '<li class=muted>không ghi</li>'}</ul>
{''.join(f"<p class='err' style='margin:.4rem 0;font-size:.85rem'>Không có trong căn cứ: {E(x)}</p>" for x in uns)}
{''.join(f"<p class='muted' style='margin:.2rem 0;font-size:.82rem'>Suy diễn: {E(x)}</p>" for x in inf)}
</div><div style='border-left:1px solid var(--line);padding-left:12px'><p class='muted' style='margin:0 0 4px;font-size:.75rem;text-transform:uppercase'>Nguyên văn căn cứ</p>{srcs}</div></div></div>""")
    if pending:
        out.append("""<div class='panel'><h3 style='margin-top:0'>Quyết định</h3><label>Ghi chú (tùy chọn)<br><textarea name='note'></textarea></label>
<div class='row' style='margin-top:8px'><button name='decision' value='approved'>Duyệt — nạp các nghĩa vụ không bị tick Loại</button>
<button class='ghost' name='decision' value='rejected'>Từ chối cả đề xuất</button></div>
<p class='muted' style='font-size:.82rem'>Duyệt chưa ghi gì vào database. Nghĩa vụ chỉ được nạp khi chạy <code>python loader.py apply</code>,
và được đánh dấu là đã được bạn duyệt — lần chạy agent01 sau sẽ không ghi đè lên chúng.</p></div></form>""")
    else:
        out.append(f"<div class='panel'><h3 style='margin-top:0'>Quyết định</h3><p>{E(lab)}" + (f" bởi <b>{E(r[7])}</b> lúc {r[8]}" if r[7] else "")
                   + (f" · loại {len(excluded)} nghĩa vụ" if excluded else "") + "</p>" + (f"<p class='law'>{E(r[9])}</p>" if r[9] else "")
                   + (f"<p class='muted' style='font-size:.85rem'>Kết quả nạp: {E(json.dumps(r[10], ensure_ascii=False))}</p>" if r[10] else "") + "</div>")
    rj = rep.get("rejected", [])
    if rj:
        out.append(f"<div class='panel'><details><summary>Bị loại tự động ({len(rj)}) — không được nạp</summary><ul style='font-size:.88rem'>"
                   + "".join(f"<li><b>{E(x['obligation'].get('id', ''))}</b> {E(x['obligation'].get('content', '')[:160])}<br><span class='err'>{E('; '.join(x['errors']))}</span></li>" for x in rj)
                   + "</ul></details></div>")
    nf = rep.get("new_fields", [])
    if nf:
        out.append(f"<div class='panel'><details open><summary>Đề nghị thêm trường hồ sơ doanh nghiệp ({len(nf)})</summary><p class='muted' style='font-size:.85rem'>"
                   "Model gặp điều kiện áp dụng không diễn đạt được bằng các trường hiện có. Thêm trường là việc của người, không phải của agent.</p><ul style='font-size:.88rem'>"
                   + "".join(f"<li><code>{E(str(x.get('name')))}</code> — {E(str(x.get('meaning', '')))} <span class='muted'>(Điều {E(str(x.get('dieu')))}: {E(str(x.get('why', '')))})</span></li>" for x in nf)
                   + "</ul></details></div>")
    lg = rep.get("log", [])
    if lg:
        out.append(f"<div class='panel'><details><summary>Nhật ký agent01 ({len(lg)} điều)</summary><ul style='font-size:.85rem'>" + "".join(f"<li>{E(x)}</li>" for x in lg) + "</ul></details></div>")
    return page(f"Đề xuất #{pid}", "".join(out), "/proposals")
