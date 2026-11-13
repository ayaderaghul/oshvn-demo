import hmac, json

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from app.db import db, writer
from app.security import auth, csrf_token, same_origin
from app.templating import templates

router = APIRouter()


@router.get("/proposals")
def proposals(request: Request):
    with db() as conn:
        if conn.execute("SELECT to_regclass('public.load_proposals')").fetchone()[0] is None:
            rows = None
        else:
            rows = conn.execute("""SELECT id, status, doc_code, file_name, created_at::timestamp(0) AS created_at, created_by, reviewed_by,
                                          report->'chunks' AS chunks, report->'accepted' AS accepted, jsonb_array_length(coalesce(report->'issues','[]')) AS n_issues,
                                          report->'agent'->>'verdict' AS verdict, report->'agent'->>'comment' AS comment, report->'agent'->>'route' AS route,
                                          coalesce(to_jsonb(lp)->>'kind', 'documents') AS kind,
                                          jsonb_array_length(coalesce(payload->'obligations','[]')) AS n_obligations,
                                          jsonb_array_length(coalesce(report->'rejected','[]')) AS n_rejected, report->>'flagged' AS flagged
                                   FROM load_proposals lp ORDER BY (status='pending') DESC, id DESC LIMIT 100""").fetchall()
    return templates.TemplateResponse(request, "proposals.html", {"rows": rows})


@router.get("/proposals/{pid}")
def proposal(request: Request, pid: int, err: str = ""):
    with db() as conn:
        k = conn.execute("SELECT coalesce(to_jsonb(lp)->>'kind','documents') AS kind FROM load_proposals lp WHERE id=%s", (pid,)).fetchone()
    if k and k.kind == "obligations":
        return obligation_proposal(request, pid, err)
    with db() as conn:
        r = conn.execute("""SELECT id, status, doc_code, file_name, options, report, payload->'result'->'chunks' AS chunks,
                                   payload->>'title' AS title, created_at::timestamp(0) AS created_at, created_by, reviewed_by, reviewed_at::timestamp(0) AS reviewed_at,
                                   review_note, apply_report, payload->>'dtype' AS dtype
                            FROM load_proposals WHERE id=%s""", (pid,)).fetchone()
        if not r:
            raise HTTPException(404)
        exists = conn.execute("SELECT id FROM legal_documents WHERE number=%s", (r.doc_code,)).fetchone()
    rep, chunks = r.report or {}, r.chunks or []
    # What the database held when the proposal was made (stored in the report), not what it holds now:
    # the page must read the same before and after review / apply, so it can be checked later (QC).
    was_new = rep.get("document") == "mới" if rep.get("document") else not exists
    by_dieu = {}
    for x in chunks:
        by_dieu.setdefault(str(x.get("dieu")), []).append(x)
    ctx = {"r": r, "rep": rep, "exists": exists, "was_new": was_new, "by_dieu": by_dieu, "n_chunks": len(chunks),
           "options": {k: v for k, v in (r.options or {}).items() if v}, "err_msg": REVIEW_ERRORS.get(err)}
    return templates.TemplateResponse(request, "proposal.html", ctx)


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


def source_key(s):
    return f"{s[0]}|{s[1]}|" + ("" if s[2] is None else str(s[2]))


def obligation_view(o, texts):
    amended = o.get("_amended_by") or []
    sources = []
    for s in o.get("sources", []):
        notes = [m for m in amended if m["source"] == s]
        sources.append({"ref": s, "text": texts.get(source_key(s)), "notes": notes,
                        "old": any(m["khoan"] is None or not m.get("diem") for m in notes)})
    shown, added = {tuple(x) for x in o.get("sources", [])}, []   # the amending clause's text, if the obligation did not already cite it
    for m in amended:
        if tuple(m["by"]) in shown: continue
        shown.add(tuple(m["by"]))
        added.append({"ref": m["by"], "text": texts.get(source_key(m["by"]), "")})
    return {"o": o, "sources": sources, "added": added}


def obligation_proposal(request, pid, err):
    with db() as conn:
        r = conn.execute("""SELECT id, status, doc_code, payload, report, created_at::timestamp(0) AS created_at, created_by, reviewed_by,
                                   reviewed_at::timestamp(0) AS reviewed_at, review_note, apply_report, to_jsonb(lp)->'excluded' AS excluded
                            FROM load_proposals lp WHERE id=%s""", (pid,)).fetchone()
    if not r: raise HTTPException(404)
    payload, rep = r.payload or {}, r.report or {}
    texts = payload.get("texts", {})
    ctx = {"r": r, "rep": rep, "ag": rep.get("agent", {}), "excluded": set(r.excluded or []), "err_msg": REVIEW_ERRORS.get(err),
           "obls": [obligation_view(o, texts) for o in payload.get("obligations", [])]}
    return templates.TemplateResponse(request, "obligation_proposal.html", ctx)
