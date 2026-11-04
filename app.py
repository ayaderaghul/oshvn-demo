"""OSHVN demo web — read-only view of what is in the Neon database.

Pages: documents · one document (Điều › Khoản) · keyword search · obligations + rule engine · load log.
Environment: DATABASE_URL (read-only role), APP_PASSWORD (HTTP Basic, any user name).
"""
import html, json, os, re, secrets
from contextlib import contextmanager

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
security = HTTPBasic()
E = html.escape


def auth(c: HTTPBasicCredentials = Depends(security)):
    pw = os.environ.get("APP_PASSWORD")
    if not pw or not secrets.compare_digest(c.password.encode(), pw.encode()):
        raise HTTPException(401, "Sai mật khẩu", headers={"WWW-Authenticate": "Basic"})


@contextmanager
def db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(500, "Chưa đặt DATABASE_URL trên Render")
    with psycopg.connect(url, autocommit=True, connect_timeout=15) as conn:
        conn.execute("SET default_transaction_read_only = on")
        yield conn


CSS = """
:root{--bg:#f6f4ef;--panel:#fffdf8;--ink:#1d2321;--muted:#5d6763;--line:#e1ddd2;--accent:#b5401f;--soft:#f6e3da;--ok:#2f7a4c;--oks:#e1f0e6;--warn:#9a6a00;--warns:#f7ecd2;--code:#efece4}
@media (prefers-color-scheme:dark){:root{--bg:#141816;--panel:#1b201e;--ink:#e7e9e4;--muted:#9aa49f;--line:#2c3330;--accent:#f08a63;--soft:#3a2219;--ok:#6fcf97;--oks:#173023;--warn:#e7b84a;--warns:#33290f;--code:#232927;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,"Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:18px max(16px,env(safe-area-inset-left))}
nav{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--line);margin:8px 0 16px}
nav a{padding:8px 12px;color:var(--muted);text-decoration:none;font-weight:600;border-bottom:2px solid transparent}
nav a.on{color:var(--ink);border-color:var(--accent)}
h1{font-size:1.45rem;margin:.2rem 0}.eyebrow{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);font-weight:600}
.muted{color:var(--muted)}.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
th{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}.scroll{overflow-x:auto}
a{color:var(--accent)}.law{font-family:Georgia,"Noto Serif",serif;white-space:pre-wrap;margin:0}
.pill{display:inline-block;white-space:nowrap;margin:1px 0;font-size:.72rem;font-weight:600;padding:1px 8px;border-radius:999px;background:var(--code);color:var(--muted)}
.pill.ok{background:var(--oks);color:var(--ok)}.pill.no{background:var(--warns);color:var(--warn)}.pill.ac{background:var(--soft);color:var(--accent)}
form.row,.row{display:flex;gap:8px;flex-wrap:wrap;align-items:end}input,select{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink)}
button{font:inherit;font-weight:600;padding:8px 14px;border:0;border-radius:8px;background:var(--accent);color:#fff;cursor:pointer}
.grid{display:grid;grid-template-columns:260px minmax(0,1fr);gap:14px}@media(max-width:800px){.grid{grid-template-columns:1fr}}
.toc{max-height:75vh;overflow:auto;font-size:.85rem}.toc a{display:block;padding:3px 0;text-decoration:none;color:var(--ink)}.toc h4{margin:10px 0 2px;font-size:.7rem;color:var(--muted);text-transform:uppercase}
.art{border-top:1px solid var(--line);padding:10px 0}.art h3{margin:0 0 6px;font-size:1rem}
.k{display:grid;grid-template-columns:70px minmax(0,1fr);gap:10px;padding:6px 0}.k b{color:var(--accent);font-size:.8rem}
mark{background:#fde68a;color:inherit}.kpis{display:flex;gap:10px;flex-wrap:wrap}.kpi{background:var(--code);border-radius:8px;padding:8px 12px}.kpi b{display:block;font-size:1.3rem}
label.c{display:flex;gap:6px;align-items:center;font-size:.9rem}
"""
NAV = [("/", "Văn bản"), ("/search", "Tìm kiếm"), ("/obligations", "Nghĩa vụ & rule engine"), ("/runs", "Nhật ký nạp")]


def page(title, body, active="/"):
    nav = "".join(f'<a href="{h}" class="{"on" if h == active else ""}">{t}</a>' for h, t in NAV)
    return HTMLResponse(f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)} · OSHVN demo</title><style>{CSS}</style></head><body><div class="wrap">
<div class="eyebrow">OSHVN · bản demo đọc dữ liệu từ Neon · chỉ đọc</div><nav>{nav}</nav>{body}
<p class="muted" style="font-size:.8rem;margin-top:24px">Dữ liệu luật do bộ tách tự động; nghĩa vụ là bản nháp chưa được chuyên gia OSHVN duyệt.</p>
</div></body></html>""")


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.get("/", dependencies=[Depends(auth)])
def documents():
    with db() as conn:
        rows = conn.execute("""
          SELECT d.id, d.number, d.type, d.title_vi, d.status, d.parser_version, d.source_file,
                 count(c.*) FILTER (WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false)) AS n,
                 count(c.embedding) FILTER (WHERE NOT coalesce(c.retired,false)) AS emb,
                 count(DISTINCT c.locator->>'dieu') FILTER (WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false)) AS dieu
          FROM legal_documents d LEFT JOIN chunks c ON c.document_id=d.id
          GROUP BY d.id ORDER BY (count(c.*)=0), d.number""").fetchall()
        tot = conn.execute("SELECT count(*) FROM chunks WHERE source_kind='legal_article' AND NOT coalesce(retired,false)").fetchone()[0]
    body = [f"<h1>Văn bản trong database</h1><div class='kpis' style='margin:10px 0 14px'><div class='kpi'><b>{len(rows)}</b>văn bản</div><div class='kpi'><b>{tot:,}</b>khoản</div></div>"]
    body.append("<div class='panel scroll'><table><tr><th>Số hiệu</th><th>Loại</th><th>Tên</th><th>Điều</th><th>Khoản</th><th>Vector</th><th>Nguồn</th></tr>")
    for r in rows:
        link = f"<a href='/doc/{r[0]}'>{E(r[1])}</a>" if r[7] else E(r[1])
        src = f"{E(r[6] or '')}<br><span class='muted'>{E(r[5] or 'dữ liệu mẫu')}</span>" if r[6] else "<span class='muted'>dữ liệu mẫu ban đầu</span>"
        body.append(f"<tr><td>{link}</td><td>{E(r[2] or '')}</td><td>{E((r[3] or '')[:140])}</td><td>{r[9]}</td><td>{r[7]}</td>"
                    f"<td>{r[8]}</td><td style='font-size:.8rem'>{src}</td></tr>")
    body.append("</table></div>")
    return page("Văn bản", "".join(body), "/")


@app.get("/doc/{doc_id}", dependencies=[Depends(auth)])
def document(doc_id: int):
    with db() as conn:
        d = conn.execute("SELECT number, title_vi, type, check_report FROM legal_documents WHERE id=%s", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404)
        rows = conn.execute("""SELECT locator, text FROM chunks WHERE document_id=%s AND source_kind='legal_article' AND NOT coalesce(retired,false)
                               ORDER BY (locator->>'dieu' LIKE 'PL%%'), nullif(regexp_replace(locator->>'dieu','[^0-9]','','g'),'')::int, coalesce((locator->>'khoan')::int, 0), coalesce((locator->>'seq')::int,0)""", (doc_id,)).fetchall()
    arts, order = {}, []
    for loc, text in rows:
        key = loc.get("dieu")
        if key not in arts:
            arts[key] = {"loc": loc, "parts": []}; order.append(key)
        arts[key]["parts"].append((loc, text.split("\n", 1)[1] if "\n" in text else text))
    toc, lastch = [], None
    for k in order:
        loc = arts[k]["loc"]
        group = "Phụ lục" if loc.get("kind") == "appendix_item" else loc.get("chuong")
        if group != lastch:
            lastch = group
            head = "Phụ lục" if group == "Phụ lục" else (f"Chương {group} · {loc.get('chuong_title') or ''}" if group else "")
            if head: toc.append(f"<h4>{E(head)}</h4>")
        toc.append(f"<a href='#d{k}'>{E(loc.get('label') or 'Đ.' + str(k))} {E(loc.get('dieu_title') or '')}</a>")
    main = []
    for k in order:
        loc = arts[k]["loc"]
        main.append(f"<div class='art' id='d{k}'><h3>{E(loc.get('label') or 'Điều ' + str(k))}. {E(loc.get('dieu_title') or '')}</h3>")
        for pl, t in arts[k]["parts"]:
            tag = f"{'Mục' if pl.get('kind') == 'appendix_item' else 'Khoản'} {pl['khoan']}" if pl.get("khoan") else ("Mở đầu" if pl.get("kind") == "lead" else "Đoạn")
            main.append(f"<div class='k'><b>{tag}</b><p class='law'>{E(t)}</p></div>")
        main.append("</div>")
    checks = "".join(f"<span class='pill {'ok' if c['ok'] else 'no'}' title='{E(c['detail'])}'>{'ĐẠT' if c['ok'] else 'LỖI'} · {E(c['name'])}</span> "
                     for c in (d[3] or []))
    body = (f"<h1>{E(d[0])}</h1><p class='muted' style='margin:0 0 8px'>{E(d[1] or '')}</p><p>{checks}</p>"
            f"<div class='grid'><div class='panel toc'>{''.join(toc)}</div><div class='panel'>{''.join(main) or '<p class=muted>Chưa có khoản nào.</p>'}</div></div>")
    return page(d[0], body, "/")


@app.get("/search", dependencies=[Depends(auth)])
def search(q: str = Query("", max_length=300)):
    hits = []
    if q.strip():
        with db() as conn:
            hits = conn.execute("""
              SELECT d.id, d.number, c.locator, ts_rank(c.tsv, query) AS rank,
                     ts_headline('vi_simple', c.text, query, 'StartSel=<mark>,StopSel=</mark>,MaxFragments=2,MaxWords=40,MinWords=15') AS snip
              FROM chunks c JOIN legal_documents d ON d.id=c.document_id,
                   websearch_to_tsquery('vi_simple', %s) query
              WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false) AND c.tsv @@ query
              ORDER BY rank DESC LIMIT 20""", (q,)).fetchall()
            if not hits:   # all words did not match together: fall back to any word
                anyq = " OR ".join(w for w in re.findall(r"\w+", q) if len(w) > 1)
                hits = conn.execute("""
                  SELECT d.id, d.number, c.locator, ts_rank(c.tsv, query) AS rank,
                         ts_headline('vi_simple', c.text, query, 'StartSel=<mark>,StopSel=</mark>,MaxFragments=2,MaxWords=40,MinWords=15')
                  FROM chunks c JOIN legal_documents d ON d.id=c.document_id, websearch_to_tsquery('vi_simple', %s) query
                  WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false) AND c.tsv @@ query
                  ORDER BY rank DESC LIMIT 20""", (anyq,)).fetchall() if anyq else []
    res = []
    for did, num, loc, rank, snip in hits:
        snip = E(snip).replace("&lt;mark&gt;", "<mark>").replace("&lt;/mark&gt;", "</mark>")
        ref = loc.get("ref") or ((loc.get("label") or f"Điều {loc.get('dieu')}") + (f", khoản {loc['khoan']}" if loc.get("khoan") else ""))
        res.append(f"<div class='art'><a href='/doc/{did}#d{loc.get('dieu')}'><b>{E(num)} · {E(ref)}</b></a> <span class='muted'>{E(loc.get('dieu_title') or '')}</span>"
                   f"<p class='law' style='font-size:.92rem'>{snip}</p></div>")
    body = (f"<h1>Tìm kiếm từ khóa</h1><p class='muted'>Tìm trên toàn bộ khoản luật, không phân biệt dấu. Tìm theo nghĩa (vector) sẽ có khi tạo embedding.</p>"
            f"<form class='row panel' method='get'><input name='q' value='{E(q)}' style='flex:1;min-width:220px' placeholder='ví dụ: khám sức khỏe định kỳ'><button>Tìm</button></form>"
            + (f"<div class='panel'><p class='muted' style='margin:0'>{len(hits)} kết quả</p>{''.join(res)}</div>" if q.strip() else ""))
    return page("Tìm kiếm", body, "/search")


FIELDS = [("sector", "Ngành", "select"), ("n", "Số lao động", "number"), ("role", "Vai trò trong dự án", "role"),
          ("strict", "Có thiết bị nghiêm ngặt", "bool"), ("hazardous", "Có việc nặng nhọc, độc hại", "bool"),
          ("kcn", "Công trình trong KCN", "bool"), ("main", "Nhà thầu chính có thầu phụ", "bool"),
          ("danger", "Vùng nguy hiểm vượt ngoài công trường", "bool"), ("lease_in", "Dùng lao động thuê lại", "bool"),
          ("lease_out", "Là DN cho thuê lại", "bool"), ("elderly", "Dùng người cao tuổi việc nặng", "bool"),
          ("state", "Tập đoàn / TCT nhà nước", "bool"), ("selftrain", "Tự huấn luyện ATVSLĐ", "bool")]
SECTORS = {"xd": ("Thi công công trình xây dựng", 1, 0), "kl": ("Sản xuất kim loại", 1, 1), "hc": ("Sản xuất hóa chất", 1, 1),
           "det": ("Dệt, may, da, giày", 0, 1), "vlxd": ("Sản xuất vật liệu xây dựng", 0, 1), "khac": ("Ngành khác", 0, 0)}
LABEL = {f: l for f, l, _ in FIELDS} | {"g36": "Ngành thuộc Điều 36 khoản 1 NĐ 39", "g37": "Ngành thuộc Điều 37 khoản 1 NĐ 39"}


def nice(reason):
    for k, v in sorted(LABEL.items(), key=lambda x: -len(x[0])):
        reason = re.sub(rf"^{k}\b", v, reason)
    return (reason.replace('"contractor"', "nhà thầu").replace('"owner"', "chủ đầu tư").replace('"none"', "không tham gia XD")
            .replace("applies to every employer", "áp dụng cho mọi người sử dụng lao động").replace("needs", "cần").replace("true", "có").replace("false", "không"))


@app.get("/obligations", dependencies=[Depends(auth)])
def obligations(request: Request):
    qp = request.query_params
    sector = qp.get("sector", "xd")
    prof = {"sector": sector, "g36": bool(SECTORS.get(sector, SECTORS["khac"])[1]), "g37": bool(SECTORS.get(sector, SECTORS["khac"])[2]),
            "n": int(qp.get("n") or 350), "role": qp.get("role", "contractor")}
    defaults = {"strict": True, "hazardous": True, "kcn": True}
    for f, _, t in FIELDS:
        if t == "bool":
            prof[f] = (qp.get(f) == "1") if "n" in qp else defaults.get(f, False)
    with db() as conn:
        rows = conn.execute("""SELECT id, topic, kind, duty_vi, action_vi, article_ref, penalties, change_note,
                                      explain_rule(applies_when, %s::jsonb) AS ex, reviewed, needs_review
                               FROM obligations WHERE sources IS NOT NULL ORDER BY id""", (json.dumps(prof),)).fetchall()
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
    ap = [r for r in rows if r[8]["applies"]]
    table = ["<div class='panel scroll'><table><tr><th>Mã</th><th>Chủ đề</th><th>Điều khoản</th><th>Nội dung</th><th>Vì sao</th><th>Phạt</th></tr>"]
    for r in sorted(rows, key=lambda r: (not r[8]["applies"], r[0])):
        why = r[8]["reasons"] if r[8]["applies"] else r[8]["missing"]
        pen = "<br>".join(E(f"Đ{p['dieu']} k{p['khoan']}: {p['text']}") for p in (r[6] or [])[:2])
        tag = "<span class='pill ok'>Áp dụng</span>" if r[8]["applies"] else "<span class='pill'>N/A</span>"
        if r[10]: tag += " <span class='pill no'>cần xem lại</span>"
        if r[7]: tag += " <span class='pill no'>đã thay đổi</span>"
        table.append(f"<tr style='{'' if r[8]['applies'] else 'opacity:.55'}'><td>{E(r[0])}<br>{tag}</td><td>{E(r[1] or '')}</td><td style='font-size:.82rem'>{E(r[5] or '')}</td>"
                     f"<td>{E(r[3] or '')}<br><span class='muted' style='font-size:.85rem'>→ {E(r[4] or '')}</span></td>"
                     f"<td style='font-size:.82rem'>{'<br>'.join(E(nice(w)) for w in why)}</td><td style='font-size:.8rem'>{pen}</td></tr>")
    table.append("</table></div>")
    head = (f"<h1>Nghĩa vụ và rule engine</h1><p class='muted'>Mỗi nghĩa vụ được kiểm tra bằng hàm <code>explain_rule()</code> chạy trong Postgres với hồ sơ bên dưới. Không dùng AI.</p>"
            + "".join(form)
            + f"<div class='kpis' style='margin-bottom:12px'><div class='kpi'><b>{len(ap)}</b>áp dụng</div><div class='kpi'><b>{len(rows) - len(ap)}</b>không áp dụng</div></div>")
    if not rows:
        head += f"<div class='panel'>Chưa có nghĩa vụ nào có căn cứ (<code>sources</code>). Nạp bằng <code>python loader.py obligations data/obligations.json</code>. ({sample} nghĩa vụ mẫu cũ không hiển thị.)</div>"
    return page("Nghĩa vụ", head + ("".join(table) if rows else ""), "/obligations")


@app.get("/runs", dependencies=[Depends(auth)])
def runs():
    with db() as conn:
        rows = conn.execute("SELECT id, kind, status, started_at::timestamp(0), created_by, report FROM load_runs ORDER BY id DESC LIMIT 50").fetchall()
    t = ["<h1>Nhật ký nạp</h1><div class='panel scroll'><table><tr><th>#</th><th>Loại</th><th>Kết quả</th><th>Lúc</th><th>Người</th><th>Chi tiết</th></tr>"]
    for r in rows:
        rep = r[5] or {}
        det = rep.get("file", "")
        if "chunks" in rep:
            c = rep["chunks"]; det += f" — {c['new']} mới, {c['changed']} đổi, {c['unchanged']} không đổi, {c['retired']} ngừng"
        if rep.get("reason"): det += f" — {rep['reason']}"
        cls = {"applied": "ok", "rejected": "no", "dry_run": ""}.get(r[2], "")
        t.append(f"<tr><td>{r[0]}</td><td>{E(r[1])}</td><td><span class='pill {cls}'>{E(r[2])}</span></td><td>{r[3]}</td><td>{E(r[4] or '')}</td><td style='font-size:.85rem'>{E(det)}</td></tr>")
    t.append("</table></div>")
    return page("Nhật ký nạp", "".join(t), "/runs")
