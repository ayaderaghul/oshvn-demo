import re

from fastapi import APIRouter, HTTPException, Query

from app.db import db
from app.views import E, agent_cell, counts, page, status_pill

router = APIRouter()


@router.get("/")
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
          SELECT count(*) AS n,
                 count(DISTINCT (document_id, locator->>'dieu')) FILTER (WHERE locator->>'dieu' ~ '^[0-9]+$') AS dieu,
                 count(*) FILTER (WHERE locator->>'kind' LIKE 'appendix%') AS pl
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


@router.get("/doc/{doc_id}")
def document(doc_id: int):
    with db() as conn:
        d = conn.execute("SELECT number, title_vi, type, check_report FROM legal_documents WHERE id=%s", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404)
        hist = []
        if conn.execute("SELECT to_regclass('public.load_proposals')").fetchone()[0]:
            hist = conn.execute("""SELECT id, status, file_name, created_at::timestamp(0), reviewed_by, reviewed_at::timestamp(0), review_note,
                                          report->'agent'->>'verdict' AS verdict, report->'agent'->>'comment' AS comment, report->'agent'->>'route' AS route, report->'chunks' AS chunks
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


@router.get("/search")
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
                         ts_headline('vi_simple', c.text, query, 'StartSel=<mark>,StopSel=</mark>,MaxFragments=2,MaxWords=40,MinWords=15') AS snip
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
