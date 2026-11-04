"""OSHVN demo web — view of what is in the Neon database, plus review of load proposals.

Pages: documents · one document (Điều › Khoản) · keyword search · obligations + rule engine · load log · proposals.
Environment: DATABASE_URL (role oshvn_web: reads tables; its only write is the review_proposal() function),
APP_PASSWORD (HTTP Basic; the user name is recorded as the reviewer).
"""
import difflib, hashlib, hmac, html, json, os, re, secrets
from urllib.parse import quote
from contextlib import contextmanager

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
security = HTTPBasic()
E = html.escape


def auth(c: HTTPBasicCredentials = Depends(security)):
    pw = os.environ.get("APP_PASSWORD")
    if not pw or not secrets.compare_digest(c.password.encode(), pw.encode()):
        raise HTTPException(401, "Sai mật khẩu", headers={"WWW-Authenticate": "Basic"})
    return c.username.strip()


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
ins{background:var(--oks);color:var(--ok);text-decoration:none;border-radius:3px}del{background:var(--warns);color:var(--warn);border-radius:3px}
details>summary{cursor:pointer;font-weight:600}textarea{font:inherit;width:100%;min-height:70px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink)}
button.ghost{background:var(--code);color:var(--ink)}.err{background:var(--warns);color:var(--warn);padding:8px 12px;border-radius:8px}
"""
NAV = [("/", "Văn bản"), ("/search", "Tìm kiếm"), ("/obligations", "Nghĩa vụ & rule engine"), ("/proposals", "Chờ duyệt"), ("/runs", "Nhật ký nạp")]


def page(title, body, active="/"):
    nav = "".join(f'<a href="{h}" class="{"on" if h == active else ""}">{t}</a>' for h, t in NAV)
    return HTMLResponse(f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)} · OSHVN demo</title><style>{CSS}</style></head><body><div class="wrap">
<div class="eyebrow">OSHVN · bản demo dữ liệu từ Neon</div><nav>{nav}</nav>{body}
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
                 count(DISTINCT c.locator->>'dieu') FILTER (WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false)
                                                           AND c.locator->>'dieu' ~ '^[0-9]+$') AS dieu,
                 count(*) FILTER (WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false)
                                  AND c.locator->>'kind' LIKE 'appendix%%') AS pl
          FROM legal_documents d LEFT JOIN chunks c ON c.document_id=d.id
          GROUP BY d.id ORDER BY (count(c.*)=0), d.number""").fetchall()
        tot, tot_dieu, tot_pl = conn.execute("""
          SELECT count(*),
                 count(DISTINCT (document_id, locator->>'dieu')) FILTER (WHERE locator->>'dieu' ~ '^[0-9]+$'),
                 count(*) FILTER (WHERE locator->>'kind' LIKE 'appendix%%')
          FROM chunks WHERE source_kind='legal_article' AND NOT coalesce(retired,false)""").fetchone()
    body = [f"<h1>Văn bản trong database</h1><div class='kpis' style='margin:10px 0 14px'><div class='kpi'><b>{len(rows)}</b>văn bản</div><div class='kpi'><b>{tot_dieu:,}</b>điều</div>"
            f"<div class='kpi'><b>{tot - tot_pl:,}</b>khoản và đoạn</div><div class='kpi'><b>{tot_pl:,}</b>mục phụ lục</div></div>"
            "<p class='muted' style='font-size:.82rem;margin-top:-6px'>Khoản và đoạn: mỗi khoản, cộng đoạn mở đầu của Điều; Điều không chia khoản tính là một đoạn.</p>"]
    body.append("<div class='panel scroll'><table><tr><th>Số hiệu</th><th>Loại</th><th>Tên</th><th>Điều</th><th>Khoản và đoạn</th><th>Mục phụ lục</th><th>Vector</th><th>Nguồn</th></tr>")
    for r in rows:
        link = f"<a href='/doc/{r[0]}'>{E(r[1])}</a>" if r[7] else E(r[1])
        src = f"{E(r[6] or '')}<br><span class='muted'>{E(r[5] or 'dữ liệu mẫu')}</span>" if r[6] else "<span class='muted'>dữ liệu mẫu ban đầu</span>"
        body.append(f"<tr><td>{link}</td><td>{E(r[2] or '')}</td><td>{E((r[3] or '')[:140])}</td><td>{r[9]}</td><td>{r[7] - r[10]}</td><td>{r[10] or '—'}</td>"
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


# ---------------------------------------------------------------- review of load proposals
STATUS_VI = {"pending": ("Chờ duyệt", "no"), "approved": ("Đã duyệt — chờ nạp", "ok"), "rejected": ("Từ chối", ""),
             "applied": ("Đã nạp", "ok"), "superseded": ("Bị thay thế", ""), "failed": ("Lỗi khi nạp", "no")}


def csrf_token(pid):
    key = (os.environ.get("APP_PASSWORD") or "").encode()
    return hmac.new(key, f"proposal:{pid}".encode(), hashlib.sha256).hexdigest()[:32]


def word_diff(old, new):
    a, b = re.findall(r"\S+|\s+", old or ""), re.findall(r"\S+|\s+", new or "")
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal": out.append(E("".join(a[i1:i2])))
        if tag in ("delete", "replace"): out.append(f"<del>{E(''.join(a[i1:i2]))}</del>")
        if tag in ("insert", "replace"): out.append(f"<ins>{E(''.join(b[j1:j2]))}</ins>")
    return "".join(out)


VERDICT_VI = {"ok": ("có thể duyệt", "ok"), "check": ("cần xem kỹ", "no"), "reject": ("không nên nạp", "no")}


def agent_cell(verdict, comment, route):
    if not verdict:
        return "<td class='muted' style='font-size:.82rem'>— (tạo bằng loader.py propose)</td>"
    lab, cls = VERDICT_VI.get(verdict, (verdict, ""))
    how = {"ocr": "bản scan · OCR + Claude đọc ảnh", "parse": "file có chữ"}.get(route or "", route or "")
    text = comment or ""
    short = E(text[:260]) + ("…" if len(text) > 260 else "")
    return (f"<td style='font-size:.85rem'><span class='pill {cls}'>{lab}</span> <span class='muted'>{E(how)}</span><br>{short}</td>")


@app.get("/proposals", dependencies=[Depends(auth)])
def proposals():
    with db() as conn:
        if conn.execute("SELECT to_regclass('public.load_proposals')").fetchone()[0] is None:
            return page("Chờ duyệt", "<h1>Chờ duyệt</h1><div class='panel'>Chưa có bảng đề xuất. Chạy <code>python loader.py migrate</code>.</div>", "/proposals")
        rows = conn.execute("""SELECT id, status, doc_code, file_name, created_at::timestamp(0), created_by, reviewed_by,
                                      report->'chunks', report->'accepted', jsonb_array_length(coalesce(report->'issues','[]')),
                                      report->'agent'->>'verdict', report->'agent'->>'comment', report->'agent'->>'route',
                                      coalesce(to_jsonb(lp)->>'kind', 'documents'),
                                      jsonb_array_length(coalesce(payload->'obligations','[]')),
                                      jsonb_array_length(coalesce(report->'rejected','[]')), report->>'flagged'
                               FROM load_proposals lp ORDER BY (status='pending') DESC, id DESC LIMIT 100""").fetchall()
    t = ["<h1>Đề xuất chờ duyệt</h1><p class='muted'>Văn bản luật (agent00, <code>loader.py propose</code>) và nghĩa vụ (agent01). "
         "Duyệt ở đây, rồi chạy <code>python loader.py apply</code> để nạp.</p><div class='panel scroll'><table>"
         "<tr><th>#</th><th>Trạng thái</th><th>Văn bản</th><th>Thay đổi</th><th style='min-width:280px'>Nhận xét của agent</th><th>Ngoại lệ</th><th>Tạo</th><th>Duyệt</th></tr>"]
    for r in rows:
        lab, cls = STATUS_VI.get(r[1], (r[1], ""))
        c = r[7] or {}
        t.append(f"<tr><td><a href='/proposals/{r[0]}'>#{r[0]}</a></td><td><span class='pill {cls}'>{lab}</span></td>"
                 f"<td><a href='/proposals/{r[0]}'><b>{E(r[2])}</b></a><br><span class='muted' style='font-size:.8rem'>{E(r[3] or '')}</span></td>"
                 + (f"<td><b>{r[14]}</b> nghĩa vụ</td><td style='font-size:.85rem'><span class='pill'>agent01</span> "
                    f"{r[14]} đạt kiểm tra · {r[15]} bị loại · <b>{r[16] or 0}</b> có ý không có căn cứ</td>" if r[13] == "obligations" else
                    f"<td>{c.get('new', 0)} mới / {c.get('changed', 0)} đổi / {c.get('retired', 0)} ngừng</td>" + agent_cell(r[10], r[11], r[12])) +
                 f"<td style='font-size:.82rem'>{E(', '.join(x.split(':')[0] for x in (r[8] or []))) or '—'}<br><span class='muted'>{r[9]} ghi chú parser</span></td>"
                 f"<td style='font-size:.82rem'>{r[4]}<br>{E(r[5] or '')}</td><td>{E(r[6] or '')}</td></tr>")
    t.append("</table></div>" if rows else "<tr><td colspan=8 class='muted'>Chưa có đề xuất nào.</td></tr></table></div>")
    return page("Chờ duyệt", "".join(t), "/proposals")


@app.get("/proposals/{pid}", dependencies=[Depends(auth)])
def proposal(pid: int, err: str = ""):
    with db() as conn:
        k = conn.execute("SELECT coalesce(to_jsonb(lp)->>'kind','documents') FROM load_proposals lp WHERE id=%s", (pid,)).fetchone()
    if k and k[0] == "obligations":
        return obligation_proposal(pid, err)
    with db() as conn:
        r = conn.execute("""SELECT id, status, doc_code, file_name, options, report, payload->'result'->'chunks',
                                   payload->>'title', created_at::timestamp(0), created_by, reviewed_by, reviewed_at::timestamp(0),
                                   review_note, apply_report, payload->>'dtype'
                            FROM load_proposals WHERE id=%s""", (pid,)).fetchone()
        if not r:
            raise HTTPException(404)
        exists = conn.execute("SELECT id FROM legal_documents WHERE number=%s", (r[2],)).fetchone()
    rep, chunks = r[5] or {}, r[6] or []
    lab, cls = STATUS_VI.get(r[1], (r[1], ""))
    c = rep.get("chunks", {})
    out = [f"<p><a href='/proposals'>← Danh sách đề xuất</a></p><div class='eyebrow'>Đề xuất #{r[0]}</div>",
           f"<h1>{E(r[2])} <span class='pill {cls}' style='font-size:.8rem;vertical-align:middle'>{lab}</span></h1>",
           f"<p class='muted' style='margin:0 0 10px'>{E(r[7] or '')}</p>",
           f"<p class='muted' style='font-size:.85rem'>File {E(r[3] or '')} · tạo {r[8]} bởi {E(r[9] or '?')} · "
           f"tùy chọn: {E(json.dumps({k: v for k, v in (r[4] or {}).items() if v}, ensure_ascii=False))} · "
           + (f"<a href='/doc/{exists[0]}'>bản đang có trong database</a>" if exists else "văn bản mới, chưa có trong database") + "</p>"]
    if err:
        out.append(f"<p class='err'>{E(err)}</p>")
    out.append(f"<div class='kpis' style='margin-bottom:12px'><div class='kpi'><b>{c.get('new', 0)}</b>khoản mới</div>"
               f"<div class='kpi'><b>{c.get('changed', 0)}</b>đổi chữ</div><div class='kpi'><b>{c.get('unchanged', 0)}</b>không đổi</div>"
               f"<div class='kpi'><b>{c.get('retired', 0)}</b>ngừng dùng</div></div>")
    # 0. agent00's notes (if the proposal came from the agent)
    ag = rep.get("agent")
    if ag:
        vlab, vcls = {"ok": ("có thể duyệt", "ok"), "check": ("cần xem kỹ", "no"), "reject": ("không nên nạp", "no")}.get(ag.get("verdict"), ("?", ""))
        o = ag.get("ocr") or {}
        nc = "".join(f"<tr><td>trang {x['page']}</td><td><del>{E(', '.join(x['removed']))}</del></td><td><ins>{E(', '.join(x['added']))}</ins></td></tr>"
                     for x in o.get("number_changes", []))
        uns = "".join(f"<li>trang {u['page']}: {E(u['note'])}</li>" for u in o.get("unsure", []))
        low = ", ".join(f"{E(w['word'])} <span class='muted'>(tr.{w['page']})</span>" for w in o.get("low_conf", [])[:60])
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
                     f"{ag.get('calls', 0)} lần gọi · {ag.get('tokens', 0)} token. Nhận xét chỉ để tham khảo; kiểm tra tự động và người duyệt mới là quyết định.</p></div>")
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
            tag = {"changed": "đổi chữ", "new": "mới", "retired": "ngừng dùng"}[x["change"]]
            items.append(f"<div class='art'><b>{E(key)}</b> <span class='pill'>{tag}</span><p class='law' style='font-size:.92rem'>{body}</p></div>")
        out.append(f"<div class='panel'><h3 style='margin-top:0'>2. Thay đổi so với database ({len(ch)})</h3>{''.join(items)}</div>")
    elif exists:
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
    out.append(f"<div class='panel'><details{' open' if not exists else ''}><summary>4. Toàn văn đã tách ({len(order)} điều/phụ lục, {len(chunks)} khoản)</summary>{''.join(arts)}</details></div>")
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
        out.append(f"<div class='panel'><h3 style='margin-top:0'>5. Quyết định</h3><p>{lab}"
                   + (f" bởi <b>{E(r[10])}</b> lúc {r[11]}" if r[10] else "") + "</p>"
                   + (f"<p class='law'>{E(r[12])}</p>" if r[12] else "")
                   + (f"<p class='muted' style='font-size:.85rem'>Kết quả nạp: {E(json.dumps(r[13], ensure_ascii=False))}</p>" if r[13] else "") + "</div>")
    return page(f"Đề xuất #{pid}", "".join(out), "/proposals")


@app.post("/proposals/{pid}/review")
async def review(pid: int, request: Request, user: str = Depends(auth)):
    form = await request.form()
    origin = request.headers.get("origin")
    if origin and origin.split("://", 1)[-1] != request.headers.get("host"):
        raise HTTPException(403, "Sai nguồn gửi")
    if not hmac.compare_digest(str(form.get("token", "")), csrf_token(pid)):
        raise HTTPException(403, "Mã xác nhận không đúng — tải lại trang rồi thử lại")
    decision = form.get("decision")
    if decision not in ("approved", "rejected"):
        raise HTTPException(400)
    if not user:
        return RedirectResponse(f"/proposals/{pid}?err=" + quote("Đăng nhập với tên của bạn (ô tên đăng nhập) để ghi người duyệt."), 303)
    url = os.environ.get("DATABASE_URL")
    try:
        with psycopg.connect(url, autocommit=True, connect_timeout=15) as conn:   # the only write this app makes
            if form.get("items") == "1":   # obligations proposal: reviewer may drop single obligations
                excl = [x for x in form.getlist("exclude") if re.fullmatch(r"[A-Za-z0-9.\-]{1,40}", str(x))]
                conn.execute("SELECT review_proposal_items(%s, %s, %s, %s, %s::jsonb)",
                             (pid, decision, user, str(form.get("note", ""))[:2000], json.dumps(excl)))
            else:
                conn.execute("SELECT review_proposal(%s, %s, %s, %s)", (pid, decision, user, str(form.get("note", ""))[:2000]))
    except psycopg.Error as e:
        msg = (e.diag.message_primary if getattr(e, "diag", None) else None) or "không ghi được quyết định"
        return RedirectResponse(f"/proposals/{pid}?err=" + quote(msg), 303)
    return RedirectResponse(f"/proposals/{pid}", 303)


# ---------------------------------------------------------------- obligations proposals (agent01)
OPS_VI = {"=": "=", "!=": "≠", ">=": "≥", "<": "<", "<=": "≤", "in": "thuộc"}


def rule_text(r):
    """applies_when → plain Vietnamese, e.g. 'n ≥ 50 VÀ (Ngành thi công xây dựng HOẶC …)'."""
    if not isinstance(r, dict): return "?"
    if r.get("always"): return "mọi doanh nghiệp"
    if "all" in r: return " VÀ ".join(f"({rule_text(x)})" if ("any" in x) else rule_text(x) for x in r["all"])
    if "any" in r: return " HOẶC ".join(rule_text(x) for x in r["any"])
    if "not" in r: return f"KHÔNG ({rule_text(r['not'])})"
    f, op, v = r.get("field"), r.get("op"), r.get("value")
    name = LABEL.get(f, f)
    if v is True and op == "=": return name
    if v is False and op == "=": return f"không: {name}"
    return f"{name} {OPS_VI.get(op, op)} {json.dumps(v, ensure_ascii=False)}"


def src_label(s):
    return f"{s[0]} Điều {s[1]}" + (f" khoản {s[2]}" if s[2] is not None else "")


def obligation_proposal(pid, err):
    with db() as conn:
        r = conn.execute("""SELECT id, status, doc_code, payload, report, created_at::timestamp(0), created_by, reviewed_by,
                                   reviewed_at::timestamp(0), review_note, apply_report, to_jsonb(lp)->'excluded'
                            FROM load_proposals lp WHERE id=%s""", (pid,)).fetchone()
    if not r: raise HTTPException(404)
    payload, rep = r[3] or {}, r[4] or {}
    obls, texts, excluded = payload.get("obligations", []), payload.get("texts", {}), set(r[11] or [])
    lab, cls = STATUS_VI.get(r[1], (r[1], ""))
    ag = rep.get("agent", {})
    pending = r[1] == "pending"
    out = [f"<p><a href='/proposals'>← Danh sách đề xuất</a></p><div class='eyebrow'>Đề xuất #{r[0]} · nghĩa vụ</div>",
           f"<h1>{E(r[2])} <span class='pill {cls}' style='font-size:.8rem;vertical-align:middle'>{lab}</span></h1>",
           f"<p class='muted' style='font-size:.85rem'>Tạo {r[5]} bởi {E(r[6] or '?')} · {E(ag.get('agent', ''))} · soạn bằng {E(ag.get('draft_model', ''))}, "
           f"lọc và kiểm chứng bằng {E(ag.get('filter_model', ''))} · {ag.get('calls', 0)} lần gọi · {ag.get('tokens', 0):,} token</p>"]
    if err: out.append(f"<p class='err'>{E(err)}</p>")
    out.append(f"<div class='kpis' style='margin-bottom:12px'><div class='kpi'><b>{len(obls)}</b>nghĩa vụ đạt kiểm tra</div>"
               f"<div class='kpi'><b>{rep.get('flagged', 0)}</b>có ý không có căn cứ</div><div class='kpi'><b>{len(rep.get('rejected', []))}</b>bị loại tự động</div>"
               f"<div class='kpi'><b>{len(rep.get('new_fields', []))}</b>đề nghị trường hồ sơ mới</div></div>")
    out.append("<div class='panel' style='font-size:.9rem'><b>Cách duyệt.</b> Mỗi nghĩa vụ đặt cạnh nguyên văn căn cứ. Đọc nội dung, điều kiện áp dụng và mức phạt; "
               "ý có viền vàng là ý model kiểm chứng cho là <b>không có trong căn cứ</b>. Nghĩa vụ chưa ổn thì tick <b>Loại</b>; phần còn lại được nạp khi duyệt.</div>")
    if pending:
        out.append(f"<form method='post' action='/proposals/{pid}/review'><input type='hidden' name='token' value='{csrf_token(pid)}'><input type='hidden' name='items' value='1'>")
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
        pens = "".join(f"<li>{E(p.get('doc', ''))} Điều {p.get('dieu')}" + (f" khoản {p.get('khoan')}" if p.get('khoan') else "")
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
        out.append(f"<div class='panel'><h3 style='margin-top:0'>Quyết định</h3><p>{lab}" + (f" bởi <b>{E(r[7])}</b> lúc {r[8]}" if r[7] else "")
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
                   + "".join(f"<li><code>{E(str(x.get('name')))}</code> — {E(str(x.get('meaning', '')))} <span class='muted'>(Điều {x.get('dieu')}: {E(str(x.get('why', '')))})</span></li>" for x in nf)
                   + "</ul></details></div>")
    lg = rep.get("log", [])
    if lg:
        out.append(f"<div class='panel'><details><summary>Nhật ký agent01 ({len(lg)} điều)</summary><ul style='font-size:.85rem'>" + "".join(f"<li>{E(x)}</li>" for x in lg) + "</ul></details></div>")
    return page(f"Đề xuất #{pid}", "".join(out), "/proposals")
