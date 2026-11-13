import hmac

from fastapi import APIRouter, Form, HTTPException, Query, Request

from app.claude import ask_claude, check_answer, parse_answer
from app.db import db
from app.rag import INDEX, embed_query, fuse, vector_model, vector_rows
from app.security import csrf_token, same_origin
from app.templating import templates

router = APIRouter()


def doc_numbers(conn):
    return [r[0] for r in conn.execute("SELECT DISTINCT d.number FROM legal_documents d JOIN chunks c ON c.document_id=d.id ORDER BY 1").fetchall()]


@router.get("/ask")
def ask_page(request: Request, q: str = Query("", max_length=500), doc: str = Query("", max_length=40)):
    """Only the form: asking costs a model call, so it is a POST with a token, never a link."""
    with db() as conn:
        docs = doc_numbers(conn)
    return templates.TemplateResponse(request, "ask.html", {"q": q, "doc": doc, "docs": docs, "hits": None})


@router.post("/ask")
def ask(request: Request, q: str = Form("", max_length=500), doc: str = Form("", max_length=40), token: str = Form("")):
    if not same_origin(request) or not hmac.compare_digest(token, csrf_token("ask")):
        raise HTTPException(403, "Mã xác nhận không đúng — tải lại trang rồi thử lại")
    with db() as conn:
        INDEX.ensure(conn)
        docs = doc_numbers(conn)
        model, mode = vector_model(conn)
    ctx = {"q": q, "doc": doc, "docs": docs, "hits": None}
    if not q.strip():
        return templates.TemplateResponse(request, "ask.html", ctx)
    bm, vr = INDEX.search(q, k=40, doc=doc), []
    if model:
        vec, mode = embed_query(q, model)   # no database connection is held during the HTTP call
        if vec is not None:
            with db() as conn:
                vr, mode = vector_rows(conn, vec, model, doc)
    hits = fuse(bm, vr) if vr else [(sc, r, "từ khóa") for sc, r in bm[:12]]
    ctx |= {"hits": hits, "mode": mode, "err": None, "answer": None}
    if hits:
        out, ctx["err"] = ask_claude(q, hits)
        if out:
            a = parse_answer(out)
            usage = a["_usage"] if isinstance(a["_usage"], (list, tuple)) and len(a["_usage"]) == 3 else ("", 0, 0)
            ctx["answer"] = {"text": a["answer"], "not_found": a["not_found"], "usage": usage, "check": check_answer(a["answer"], a["used"], hits)}
    return templates.TemplateResponse(request, "ask.html", ctx)
