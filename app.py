"""OSHVN demo web — view of what is in the Neon database, plus review of load proposals.

Pages: documents · one document (Điều › Khoản) · keyword search · obligations + rule engine · load log · proposals.
Environment: DATABASE_URL (role oshvn_web: reads tables; its only write is the review_proposal() function),
APP_PASSWORD (HTTP Basic; the user name is recorded as the reviewer).
"""
import difflib, hashlib, hmac, html, json, math, os, re, secrets, threading, time, unicodedata, urllib.error, urllib.request
from collections import Counter, deque, namedtuple
from urllib.parse import urlsplit
from contextlib import contextmanager

import psycopg
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic(auto_error=False)
E = html.escape
PUBLIC_PATHS = {"/healthz"}
LOGIN_FAILURES_ALLOWED = 10          # per client address, within LOGIN_WINDOW seconds
LOGIN_WINDOW = 900
FAILED_LOGINS, _login_lock = {}, threading.Lock()


def reviewer_name(raw):
    """The Basic-auth user name, recorded as the reviewer. Invisible and blank-looking characters (U+200B, Hangul
    fillers, braille blank…) are dropped; a name with no letter or digit left is no name."""
    def visible(ch):
        name = unicodedata.name(ch, "")
        return (ch.isprintable() and unicodedata.category(ch) not in ("Cf", "Cc", "Zs")
                and "FILLER" not in name and name != "BRAILLE PATTERN BLANK")
    s = unicodedata.normalize("NFKC", raw or "")
    s = " ".join("".join(ch if ch == " " or visible(ch) else "" for ch in s).split())
    return s if any(ch.isalnum() for ch in s) else ""


def client_key(request):
    """Who is guessing passwords. Behind Render's proxy the last X-Forwarded-For entry is the one the proxy added,
    so a client cannot choose it; entries to its left are whatever the client sent."""
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[-1].strip() if xff.strip() else (request.client.host if request.client else "?")


def auth(request: Request, c: HTTPBasicCredentials | None = Depends(security)):
    if request.url.path in PUBLIC_PATHS:
        return ""
    key, now = client_key(request), time.time()
    with _login_lock:
        fails = FAILED_LOGINS.get(key)
        while fails and now - fails[0] > LOGIN_WINDOW: fails.popleft()
        if fails is not None and not fails: del FAILED_LOGINS[key]
        if fails and len(fails) >= LOGIN_FAILURES_ALLOWED:
            raise HTTPException(429, "Sai mật khẩu quá nhiều lần — thử lại sau 15 phút")
    pw = os.environ.get("APP_PASSWORD")
    if not pw or c is None or not secrets.compare_digest(c.password.encode(), pw.encode()):
        if c is not None:
            with _login_lock: FAILED_LOGINS.setdefault(key, deque()).append(now)
        raise HTTPException(401, "Sai mật khẩu", headers={"WWW-Authenticate": "Basic"})
    with _login_lock: FAILED_LOGINS.pop(key, None)
    return reviewer_name(c.username)


# every route needs the password (except PUBLIC_PATHS): a new route cannot be public by forgetting a dependency
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, dependencies=[Depends(auth)])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(500, "Chưa đặt DATABASE_URL trên Render")
    return url


@contextmanager
def db():
    """Read-only: every transaction starts with BEGIN READ ONLY, which also holds through Neon's connection pooler."""
    with psycopg.connect(database_url(), connect_timeout=15) as conn:
        conn.read_only = True
        yield conn


@contextmanager
def writer():
    """The only writes this app makes: review_proposal() and review_proposal_items()."""
    with psycopg.connect(database_url(), autocommit=True, connect_timeout=15) as conn:
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
NAV = [("/", "Văn bản"), ("/ask", "Hỏi đáp"), ("/search", "Tìm kiếm"), ("/obligations", "Nghĩa vụ & rule engine"), ("/proposals", "Chờ duyệt"), ("/runs", "Nhật ký nạp")]


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


@app.get("/")
def documents():
    with db() as conn:
        rows = conn.execute("""
          SELECT d.id, d.number, d.type, d.title_vi, d.status, d.parser_version, d.source_file,
                 count(c.*) FILTER (WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false)) AS n,
                 count(c.embedding) FILTER (WHERE NOT coalesce(c.retired,false)) AS emb,
                 count(DISTINCT c.locator->>'dieu') FILTER (WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false)
                                                           AND c.locator->>'dieu' ~ '^[0-9]+$') AS dieu,
                 count(*) FILTER (WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false)
                                  AND c.locator->>'kind' LIKE 'appendix%') AS pl
          FROM legal_documents d LEFT JOIN chunks c ON c.document_id=d.id
          GROUP BY d.id ORDER BY (count(c.*)=0), d.number""").fetchall()
        tot, tot_dieu, tot_pl = conn.execute("""
          SELECT count(*),
                 count(DISTINCT (document_id, locator->>'dieu')) FILTER (WHERE locator->>'dieu' ~ '^[0-9]+$'),
                 count(*) FILTER (WHERE locator->>'kind' LIKE 'appendix%')
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


@app.get("/doc/{doc_id}")
def document(doc_id: int):
    with db() as conn:
        d = conn.execute("SELECT number, title_vi, type, check_report FROM legal_documents WHERE id=%s", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404)
        hist = []
        if conn.execute("SELECT to_regclass('public.load_proposals')").fetchone()[0]:
            hist = conn.execute("""SELECT id, status, file_name, created_at::timestamp(0), reviewed_by, reviewed_at::timestamp(0), review_note,
                                          report->'agent'->>'verdict', report->'agent'->>'comment', report->'agent'->>'route', report->'chunks'
                                   FROM load_proposals WHERE doc_code=%s AND coalesce(to_jsonb(load_proposals)->>'kind','documents')='documents'
                                   ORDER BY id DESC""", (d[0],)).fetchall()
        rows = conn.execute("""SELECT locator, text FROM chunks WHERE document_id=%s AND source_kind='legal_article' AND NOT coalesce(retired,false)
                               ORDER BY (locator->>'dieu' LIKE 'PL%%'), nullif(regexp_replace(locator->>'dieu','[^0-9]','','g'),'')::numeric,
                                        coalesce(nullif(regexp_replace(locator->>'khoan','[^0-9]','','g'),'')::numeric, 0),
                                        coalesce(nullif(regexp_replace(locator->>'seq','[^0-9]','','g'),'')::numeric, 0)""", (doc_id,)).fetchall()
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
        toc.append(f"<a href='#d{E(str(k))}'>{E(loc.get('label') or 'Đ.' + str(k))} {E(loc.get('dieu_title') or '')}</a>")
    main = []
    for k in order:
        loc = arts[k]["loc"]
        main.append(f"<div class='art' id='d{E(str(k))}'><h3>{E(loc.get('label') or 'Điều ' + str(k))}. {E(loc.get('dieu_title') or '')}</h3>")
        for pl, t in arts[k]["parts"]:
            tag = f"{'Mục' if pl.get('kind') == 'appendix_item' else 'Khoản'} {pl['khoan']}" if pl.get("khoan") else ("Mở đầu" if pl.get("kind") == "lead" else "Đoạn")
            main.append(f"<div class='k'><b>{E(tag)}</b><p class='law'>{E(t)}</p></div>")
        main.append("</div>")
    checks = "".join(f"<span class='pill {'ok' if c['ok'] else 'no'}' title='{E(c['detail'])}'>{'ĐẠT' if c['ok'] else 'LỖI'} · {E(c['name'])}</span> "
                     for c in (d[3] or []))
    hrows = "".join(
        f"<tr><td><a href='/proposals/{h[0]}'>#{h[0]}</a></td><td>{status_pill(h[1])}</td>"
        f"<td style='font-size:.82rem'>{E(h[2] or '')}<br><span class='muted'>{h[3]}</span></td>"
        f"<td style='font-size:.82rem'>{counts(h[10])}</td>"
        + agent_cell(h[7], h[8], h[9], full=True)
        + f"<td style='font-size:.82rem'>{E(h[4] or '—')}<br><span class='muted'>{h[5] or ''}</span>"
        + (f"<br><i>{E(h[6])}</i>" if h[6] else "") + "</td></tr>" for h in hist)
    history = (f"<div class='panel'><details><summary>Lịch sử nạp và duyệt ({len(hist)} đề xuất) — nhận xét của agent và người duyệt</summary>"
               f"<div class='scroll'><table><tr><th>#</th><th>Trạng thái</th><th>File</th><th>Thay đổi</th><th style='min-width:280px'>Nhận xét của agent</th><th>Người duyệt</th></tr>"
               f"{hrows}</table></div></details></div>") if hist else ""
    body = (f"<h1>{E(d[0])}</h1><p class='muted' style='margin:0 0 8px'>{E(d[1] or '')}</p><p>{checks}</p>{history}"
            f"<div class='grid'><div class='panel toc'>{''.join(toc)}</div><div class='panel'>{''.join(main) or '<p class=muted>Chưa có khoản nào.</p>'}</div></div>")
    return page(d[0], body, "/")


@app.get("/search")
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
        res.append(f"<div class='art'><a href='/doc/{did}#d{E(str(loc.get('dieu')))}'><b>{E(num)} · {E(ref)}</b></a> <span class='muted'>{E(loc.get('dieu_title') or '')}</span>"
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
    reason = (reason.replace('"contractor"', "nhà thầu").replace('"owner"', "chủ đầu tư").replace('"none"', "không tham gia XD")
              .replace("applies to every employer", "áp dụng cho mọi người sử dụng lao động"))
    for en, vi in (("needs", "cần"), ("true", "có"), ("false", "không")):
        reason = re.sub(rf"\b{en}\b", vi, reason)
    return reason


def penalty_label(p):
    if not isinstance(p, dict): return str(p)
    return (f"Đ{p.get('dieu', '?')}" + (f" k{p['khoan']}" if p.get("khoan") is not None else "") + f": {p.get('text', '')}")


@app.get("/obligations")
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


@app.get("/runs")
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


# ---------------------------------------------------------------- review of load proposals
STATUS_VI = {"pending": ("Chờ duyệt", "no"), "approved": ("Đã duyệt — chờ nạp", "ok"), "rejected": ("Từ chối", ""),
             "applied": ("Đã nạp", "ok"), "superseded": ("Bị thay thế", ""), "failed": ("Lỗi khi nạp", "no")}


def status_pill(status):
    lab, cls = STATUS_VI.get(status, (str(status), ""))
    return f"<span class='pill {cls}'>{E(lab)}</span>"


def counts(c):
    c = c if isinstance(c, dict) else {}
    return E(f"{c.get('new', 0)} mới / {c.get('changed', 0)} đổi / {c.get('retired', 0)} ngừng")


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


def agent_cell(verdict, comment, route, full=False):
    if not verdict:
        return "<td class='muted' style='font-size:.82rem'>— (tạo bằng loader.py propose)</td>"
    lab, cls = VERDICT_VI.get(verdict, ("?", ""))
    how = {"ocr": "bản scan · OCR + Claude đọc ảnh", "parse": "file có chữ"}.get(route or "", route or "")
    text = comment or ""
    short = E(text) if full else E(text[:260]) + ("…" if len(text) > 260 else "")
    return (f"<td style='font-size:.85rem'><span class='pill {cls}'>{lab}</span> <span class='muted'>{E(how)}</span><br>{short}</td>")


@app.get("/proposals")
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
        t.append(f"<tr><td><a href='/proposals/{r[0]}'>#{r[0]}</a></td><td>{status_pill(r[1])}</td>"
                 f"<td><a href='/proposals/{r[0]}'><b>{E(r[2])}</b></a><br><span class='muted' style='font-size:.8rem'>{E(r[3] or '')}</span></td>"
                 + (f"<td><b>{r[14]}</b> nghĩa vụ</td><td style='font-size:.85rem'><span class='pill'>agent01</span> "
                    f"{r[14]} đạt kiểm tra · {r[15]} bị loại · <b>{E(str(r[16] or 0))}</b> có ý không có căn cứ</td>" if r[13] == "obligations" else
                    f"<td>{counts(r[7])}</td>" + agent_cell(r[10], r[11], r[12])) +
                 f"<td style='font-size:.82rem'>{E(', '.join(x.split(':')[0] for x in (r[8] or []))) or '—'}<br><span class='muted'>{r[9]} ghi chú parser</span></td>"
                 f"<td style='font-size:.82rem'>{r[4]}<br>{E(r[5] or '')}</td><td>{E(r[6] or '')}</td></tr>")
    t.append("</table></div>" if rows else "<tr><td colspan=8 class='muted'>Chưa có đề xuất nào.</td></tr></table></div>")
    return page("Chờ duyệt", "".join(t), "/proposals")


@app.get("/proposals/{pid}")
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


def same_origin(request):
    """A form post from this site: browsers send Origin (or at least Referer) on POST, and it must name this host."""
    src = request.headers.get("origin") or request.headers.get("referer")
    return bool(src) and urlsplit(src).netloc == request.headers.get("host")


@app.post("/proposals/{pid}/review")
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


# ---------------------------------------------------------------- Hỏi đáp (RAG): BM25 over all clauses + Claude answer with citations
# Same retrieval as the tra cứu page: accent-insensitive, syllable unigrams + bigrams, BM25 (19/20 on the NĐ 39 question set).
STOP = set("cac cua va la co cho duoc trong theo tai voi nhung mot khi thi de ve tu den nay do sau day phai ai gi nao the bao nhieu khong".split())


def _norm(t):
    t = unicodedata.normalize("NFD", t.lower().replace("đ", "d"))
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def _tokens(t):
    w = re.findall(r"[a-z0-9]+", _norm(t))
    return [x for x in w if x not in STOP] + [a + "_" + b for a, b in zip(w, w[1:])]


Snapshot = namedtuple("Snapshot", "stamp rows tf lens avg idf")
# load_run_id moves on every in-place text change and every retire / revive, which count and max(id) do not see
STAMP_SQL = "SELECT count(*), max(id), max(load_run_id) FROM chunks WHERE source_kind='legal_article' AND NOT coalesce(retired,false)"


class Index:
    """In-memory BM25 over every live clause. Rebuilt when the database changes. A search reads one immutable
    snapshot, so a rebuild running at the same time can never mix two builds."""
    def __init__(self):
        self.lock, self.snap = threading.Lock(), Snapshot(None, [], [], [], 1, {})

    def ensure(self, conn):
        if tuple(conn.execute(STAMP_SQL).fetchone()) == self.snap.stamp: return
        with self.lock:
            stamp = tuple(conn.execute(STAMP_SQL).fetchone())
            if stamp == self.snap.stamp: return   # another request rebuilt it while this one waited
            rows = conn.execute("""SELECT d.id, d.number, c.locator, c.text FROM chunks c JOIN legal_documents d ON d.id=c.document_id
                                   WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false)""").fetchall()
            tf = [Counter(_tokens(r[3])) for r in rows]
            lens = [sum(t.values()) for t in tf]
            df = Counter(t for x in tf for t in x); N = len(rows)
            self.snap = Snapshot(stamp, rows, tf, lens, (sum(lens) / len(lens)) if rows else 1,
                                 {t: math.log(1 + (N - n + .5) / (n + .5)) for t, n in df.items()})

    def search(self, q, k=12, doc="", k1=1.2, b=0.75):
        s, qt, sc = self.snap, set(_tokens(q)), []
        for i, tf in enumerate(s.tf):
            if doc and s.rows[i][1] != doc: continue   # filter before ranking: a small document is not crowded out
            v = sum(s.idf[t] * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * s.lens[i] / s.avg)) for t in qt if t in tf)
            if v > 0: sc.append((v, i))
        return [(v, s.rows[i]) for v, i in sorted(sc, reverse=True)[:k]]


INDEX = Index()


def vector_model(conn):
    """(model, None) when the clauses have Voyage vectors and VOYAGE_API_KEY is set, else (None, why not)."""
    models = [r[0] for r in conn.execute("SELECT DISTINCT embedding_model FROM chunks WHERE embedding IS NOT NULL").fetchall()]
    if not models:
        return None, "chưa có vector (chạy loader.py embed) — chỉ tìm theo từ khóa"
    if len(models) > 1 or not str(models[0]).startswith("voyage:"):
        return None, f"vector trong database là {models}, trang này chỉ dùng vector Voyage — chỉ tìm theo từ khóa"
    if not os.environ.get("VOYAGE_API_KEY"):
        return None, "chưa đặt VOYAGE_API_KEY trên Render — chỉ tìm theo từ khóa"
    return models[0].split(":", 1)[1], None


def embed_query(q, model):
    """The question embedded with the SAME model that embedded the clauses. Called with no database connection open."""
    body = json.dumps({"input": [q], "model": model, "input_type": "query", "output_dimension": 1024}).encode()
    req = urllib.request.Request(os.environ.get("VOYAGE_API_BASE", "https://api.voyageai.com") + "/v1/embeddings", body,
                                 {"Authorization": f"Bearer {os.environ.get('VOYAGE_API_KEY')}", "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=15))["data"][0]["embedding"], None
    except Exception as e:
        return None, f"Voyage API lỗi ({str(e)[:120]}) — chỉ tìm theo từ khóa"


def vector_rows(conn, vec, model, doc="", k=30):
    try:
        rows = conn.execute("""SELECT d.id, d.number, c.locator, c.text, 1 - (c.embedding <=> %s::vector) AS sim
                               FROM chunks c JOIN legal_documents d ON d.id=c.document_id
                               WHERE c.source_kind='legal_article' AND NOT coalesce(c.retired,false) AND c.embedding IS NOT NULL
                                 AND (%s = '' OR d.number = %s)
                               ORDER BY c.embedding <=> %s::vector LIMIT %s""",
                            ("[" + ",".join(f"{x:.6f}" for x in vec) + "]", doc, doc) + ("[" + ",".join(f"{x:.6f}" for x in vec) + "]", k)).fetchall()
    except (psycopg.Error, TypeError, ValueError) as e:
        conn.rollback()
        return [], f"tìm theo nghĩa lỗi ({str(e)[:120]}) — chỉ tìm theo từ khóa"
    return rows, f"từ khóa (BM25) + theo nghĩa ({model})"


def fuse(bm25_hits, vec_rows, k=12):
    """Reciprocal rank fusion: a clause ranked high by either method comes first; found by both counts most."""
    score, row, how = {}, {}, {}
    for rank, (_, r) in enumerate(bm25_hits):
        key = (r[1], json.dumps(r[2], sort_keys=True)); score[key] = score.get(key, 0) + 1 / (60 + rank); row[key] = r; how.setdefault(key, set()).add("từ khóa")
    for rank, r in enumerate(vec_rows):
        key = (r[1], json.dumps(r[2], sort_keys=True)); score[key] = score.get(key, 0) + 1 / (60 + rank); row.setdefault(key, r[:4]); how.setdefault(key, set()).add("theo nghĩa")
    best = sorted(score, key=lambda x: -score[x])[:k]
    return [(score[x] * 1000, row[x], " + ".join(sorted(how[x]))) for x in best]
ASK_LOG, ASK_LOCK = deque(), threading.Lock()   # times of model calls in this process, for the hourly limit


def ask_limit():
    try:
        return max(0, int(os.environ.get("ASK_LIMIT_PER_HOUR", "60")))
    except ValueError:
        return 60


def reserve_ask():
    """Take one slot of the hourly limit, atomically. Returns the slot, or None when the limit is reached."""
    now = time.time()
    with ASK_LOCK:
        while ASK_LOG and now - ASK_LOG[0] > 3600: ASK_LOG.popleft()
        if len(ASK_LOG) >= ask_limit(): return None
        ASK_LOG.append(now)
        return now


def release_ask(slot):
    """A call that failed does not count against the limit."""
    with ASK_LOCK:
        try: ASK_LOG.remove(slot)
        except ValueError: pass


def _ref(loc, num):
    return f"{num} " + (loc.get("ref") or (loc.get("label") or f"Điều {loc.get('dieu')}") + (f", khoản {loc['khoan']}" if loc.get("khoan") else ""))


def _numbers(t):
    return re.findall(r"\d+(?:[/.,]\d+)*", t)


def _same_number(n):
    """1.000.000, 1,000,000 and 1000000 are one number; 1,5 and 1.5 are one number."""
    if re.fullmatch(r"\d{1,3}(?:([.,])\d{3})(?:\1\d{3})*", n):
        return re.sub(r"[.,]", "", n)
    return n.replace(",", ".")


def _small_int(x):
    if isinstance(x, bool): return None
    if isinstance(x, int): return x if abs(x) < 10**6 else None
    if isinstance(x, str) and x.strip().isascii() and x.strip().isdigit() and len(x.strip()) <= 6: return int(x.strip())
    return None


def parse_answer(out):
    """The model's JSON, coerced to {answer: str, used: [int], not_found: str} whatever it returned."""
    out = out if isinstance(out, dict) else {}
    text = lambda x: "" if x is None else x if isinstance(x, str) else str(x)
    used = out.get("used") if isinstance(out.get("used"), list) else []
    return {"answer": text(out.get("answer")), "used": [n for n in map(_small_int, used) if n is not None],
            "not_found": text(out.get("not_found")), "_usage": out.get("_usage", ("", 0, 0))}


def check_answer(answer, used, hits):
    """Citations outside the hits, numbers not in a cited clause, and an answer that cites nothing at all."""
    cited = {int(x) for x in re.findall(r"\[([0-9]{1,6})\]", answer)} | set(used)
    bad_cite = sorted(c for c in cited if c < 1 or c > len(hits))
    src = {_same_number(n) for c in cited if 1 <= c <= len(hits)
           for n in _numbers(hits[c - 1][1][3] + " " + _ref(hits[c - 1][1][2], hits[c - 1][1][1]))}   # text + its own reference
    plain = re.sub(r"\[[0-9]+\]", " ", answer)          # citation marks are not numbers to check
    bad_num = sorted({n for n in _numbers(plain) if _same_number(n) not in src
                      and not all(_same_number(p) in src for p in re.split(r"[,;]", n))})   # "5,7" may be a list
    return {"bad_cite": bad_cite, "bad_num": bad_num, "no_cite": not cited}


def ask_claude(question, hits):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None, "Chưa đặt ANTHROPIC_API_KEY trên Render — chỉ hiện các khoản tìm được, chưa có câu trả lời."
    slot = reserve_ask()
    if slot is None:
        return None, f"Đã đủ {ask_limit()} câu hỏi trong một giờ (giới hạn ASK_LIMIT_PER_HOUR). Thử lại sau."
    sources = "\n\n".join(f"[{i + 1}] {_ref(h[1][2], h[1][1])}\n{h[1][3][:2500]}" for i, h in enumerate(hits))
    user = (f"Câu hỏi của chuyên gia an toàn, vệ sinh lao động:\n{question}\n\nCác khoản luật tìm được (đánh số):\n{sources}\n\n"
            "Trả lời bằng tiếng Việt, ngắn gọn, CHỈ dựa vào các khoản trên. Sau mỗi ý ghi số khoản làm căn cứ, ví dụ [2] hoặc [1][4]. "
            "Mọi con số (thời hạn, số người, mức phạt) phải chép đúng từ khoản được dẫn. Nếu các khoản trên không đủ để trả lời, nói rõ "
            "phần nào không tìm thấy căn cứ, không đoán. Lưu ý: mức phạt trong NĐ 283/2026 là mức cho cá nhân; tổ chức bị phạt gấp 2 lần, "
            "trừ khi điều đó ghi rõ là tổ chức.\n"
            'Trả JSON: {"answer": "...", "used": [số các khoản đã dẫn], "not_found": "phần không có căn cứ, hoặc rỗng"}')
    model = os.environ.get("ASK_MODEL", "claude-sonnet-5-5")
    body = {"model": model, "max_tokens": 2500, "system": "Bạn là trợ lý tra cứu pháp luật ATVSLĐ của OSHVN. Chỉ trả lời bằng một đối tượng JSON.",
            "messages": [{"role": "user", "content": user}]}
    base = os.environ.get("ASK_API_BASE", "https://api.anthropic.com")
    req = urllib.request.Request(base + "/v1/messages", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        release_ask(slot)
        return None, f"Claude API báo lỗi {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
    except Exception as e:
        release_ask(slot)
        return None, f"Không gọi được Claude API: {e}"
    text = "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict) and b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        out = json.loads(m.group(0) if m else text)
    except json.JSONDecodeError:
        return None, "Câu trả lời của model không đúng định dạng — thử lại."
    if not isinstance(out, dict):
        return None, "Câu trả lời của model không đúng định dạng — thử lại."
    u = data.get("usage", {}); out["_usage"] = (model, u.get("input_tokens", 0), u.get("output_tokens", 0))
    return out, None


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


@app.get("/ask")
def ask_page(q: str = Query("", max_length=500), doc: str = Query("", max_length=40)):
    """Only the form: asking costs a model call, so it is a POST with a token, never a link."""
    return page("Hỏi đáp", ask_form(q, doc, doc_numbers()), "/ask")


@app.post("/ask")
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
