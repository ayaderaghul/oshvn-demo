import hmac, re

from fastapi import APIRouter, Form, HTTPException, Query, Request

from app.claude import _ref, ask_claude, check_answer, parse_answer
from app.db import db
from app.rag import INDEX, embed_query, fuse, vector_model, vector_rows
from app.security import csrf_token, same_origin
from app.views import E, page

router = APIRouter()


def ask_form(q="", doc="", docs=()):
    opts = "".join(f"<option value='{E(d)}' {'selected' if d == doc else ''}>{E(d)}</option>" for d in docs)
    return f"""<h1>Hỏi đáp</h1><p class='muted'>Tìm các khoản liên quan trong toàn bộ văn bản đã nạp (BM25, không phân biệt dấu), rồi Claude trả lời
<b>chỉ dựa trên các khoản đó</b>, kèm số khoản làm căn cứ. Dành cho chuyên gia kiểm tra chất lượng tra cứu — không phải tư vấn pháp lý.</p>
<form class='row panel' method='post' action='/ask'><input type='hidden' name='token' value='{csrf_token("ask")}'>
<input name='q' value='{E(q)}' maxlength='500' style='flex:1;min-width:260px' placeholder='ví dụ: công ty xây dựng 120 người có phải thành lập hội đồng ATVSLĐ không?'>
<select name='doc'><option value=''>Mọi văn bản</option>{opts}</select><button>Hỏi</button></form>"""


def doc_numbers():
    with db() as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT d.number FROM legal_documents d JOIN chunks c ON c.document_id=d.id ORDER BY 1").fetchall()]


@router.get("/ask")
def ask_page(q: str = Query("", max_length=500), doc: str = Query("", max_length=40)):
    """Only the form: asking costs a model call, so it is a POST with a token, never a link."""
    return page("Hỏi đáp", ask_form(q, doc, doc_numbers()), "/ask")


@router.post("/ask")
def ask(request: Request, q: str = Form("", max_length=500), doc: str = Form("", max_length=40), token: str = Form("")):
    if not same_origin(request) or not hmac.compare_digest(token, csrf_token("ask")):
        raise HTTPException(403, "Mã xác nhận không đúng — tải lại trang rồi thử lại")
    with db() as conn:
        INDEX.ensure(conn)
        docs = [r[0] for r in conn.execute("SELECT DISTINCT d.number FROM legal_documents d JOIN chunks c ON c.document_id=d.id ORDER BY 1").fetchall()]
        model, mode = vector_model(conn)
    body = [ask_form(q, doc, docs)]
    if not q.strip():
        return page("Hỏi đáp", "".join(body), "/ask")
    bm, vr = INDEX.search(q, k=40, doc=doc), []
    if model:
        vec, mode = embed_query(q, model)   # no database connection is held during the HTTP call
        if vec is not None:
            with db() as conn:
                vr, mode = vector_rows(conn, vec, model, doc)
    hits = fuse(bm, vr) if vr else [(sc, r, "từ khóa") for sc, r in bm[:12]]
    if not hits:
        body.append("<div class='panel'>Không tìm thấy khoản nào chứa các từ trong câu hỏi.</div>")
        return page("Hỏi đáp", "".join(body), "/ask")
    out, err = ask_claude(q, hits)
    if err:
        body.append(f"<p class='err'>{E(err)}</p>")
    if out:
        a = parse_answer(out)
        chk = check_answer(a["answer"], a["used"], hits)
        ans = re.sub(r"\[([0-9]{1,6})\]", lambda m: f"<a href='#s{m.group(1)}'>[{m.group(1)}]</a>", E(a["answer"]))
        usage = a["_usage"] if isinstance(a["_usage"], (list, tuple)) and len(a["_usage"]) == 3 else ("", 0, 0)
        warn = ""
        if chk["bad_cite"]: warn += f"<p class='err'>Câu trả lời dẫn khoản không có trong kết quả tìm: {E(', '.join(map(str, chk['bad_cite'])))}</p>"
        if chk["bad_num"]: warn += f"<p class='err'>Con số không có trong các khoản được dẫn: {E(', '.join(chk['bad_num']))} — kiểm tra lại với nguyên văn.</p>"
        if chk["no_cite"]: warn += "<p class='err'>Câu trả lời không dẫn khoản nào — không dùng được nếu chưa đối chiếu nguyên văn.</p>"
        body.append(f"""<div class='panel' style='border-color:var(--accent)'><h3 style='margin-top:0'>Trả lời</h3>
<p class='law' style='font-family:inherit;font-size:1rem'>{ans}</p>{warn}
{f"<p class='muted'><b>Không tìm thấy căn cứ:</b> {E(a['not_found'])}</p>" if a['not_found'] else ''}
<p class='muted' style='font-size:.78rem;margin-bottom:0'>{E(str(usage[0]))} · {E(str(usage[1]))} token vào, {E(str(usage[2]))} token ra. Câu trả lời do model viết từ các khoản bên dưới;
chuyên gia cần đối chiếu nguyên văn. Văn bản sửa đổi chỉ được tính nếu khoản sửa đổi nằm trong kết quả tìm.</p></div>""")
    rows = []
    for i, (score, (did, num, loc, text), how) in enumerate(hits, 1):
        rows.append(f"<div class='art' id='s{i}'><b>[{i}] <a href='/doc/{did}#d{E(str(loc.get('dieu')))}'>{E(_ref(loc, num))}</a></b> "
                    f"<span class='muted'>{E(loc.get('dieu_title') or '')}</span> <span class='pill{' ok' if '+' in how else ''}'>{E(how)}</span>"
                    f"<p class='law' style='font-size:.9rem'>{E(text.split(chr(10), 1)[-1][:1800])}</p></div>")
    body.append(f"<div class='panel'><h3 style='margin-top:0'>Các khoản tìm được ({len(hits)})</h3>"
                f"<p class='muted' style='font-size:.82rem'>Cách tìm: {E(mode or '')}</p>{''.join(rows)}</div>")
    return page("Hỏi đáp", "".join(body), "/ask")
