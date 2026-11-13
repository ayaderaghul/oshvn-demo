import re

from fastapi import APIRouter, HTTPException, Query, Request

from app.db import db
from app.templating import templates

router = APIRouter()


@router.get("/")
def documents(request: Request):
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
        tot = conn.execute("""
          SELECT count(*) AS n,
                 count(DISTINCT (document_id, locator->>'dieu')) FILTER (WHERE locator->>'dieu' ~ '^[0-9]+$') AS dieu,
                 count(*) FILTER (WHERE locator->>'kind' LIKE 'appendix%') AS pl
          FROM chunks WHERE source_kind='legal_article' AND NOT coalesce(retired,false)""").fetchone()
    return templates.TemplateResponse(request, "documents.html", {"rows": rows, "tot": tot})


@router.get("/doc/{doc_id}")
def document(request: Request, doc_id: int):
    with db() as conn:
        d = conn.execute("SELECT number, title_vi, type, check_report FROM legal_documents WHERE id=%s", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404)
        hist = []
        if conn.execute("SELECT to_regclass('public.load_proposals')").fetchone()[0]:
            hist = conn.execute("""SELECT id, status, file_name, created_at::timestamp(0), reviewed_by, reviewed_at::timestamp(0), review_note,
                                          report->'agent'->>'verdict' AS verdict, report->'agent'->>'comment' AS comment, report->'agent'->>'route' AS route, report->'chunks' AS chunks
                                   FROM load_proposals WHERE doc_code=%s AND coalesce(to_jsonb(load_proposals)->>'kind','documents')='documents'
                                   ORDER BY id DESC""", (d.number,)).fetchall()
        rows = conn.execute("""SELECT locator, text FROM chunks WHERE document_id=%s AND source_kind='legal_article' AND NOT coalesce(retired,false)
                               ORDER BY (locator->>'dieu' LIKE 'PL%%'), nullif(regexp_replace(locator->>'dieu','[^0-9]','','g'),'')::numeric,
                                        coalesce(nullif(regexp_replace(locator->>'khoan','[^0-9]','','g'),'')::numeric, 0),
                                        coalesce(nullif(regexp_replace(locator->>'seq','[^0-9]','','g'),'')::numeric, 0)""", (doc_id,)).fetchall()
    arts = {}
    for loc, text in rows:
        key = loc.get("dieu")
        if key not in arts:
            arts[key] = {"key": key, "loc": loc, "parts": []}
        arts[key]["parts"].append((loc, text.split("\n", 1)[1] if "\n" in text else text))
    return templates.TemplateResponse(request, "document.html", {"d": d, "hist": hist, "arts": list(arts.values())})


@router.get("/search")
def search(request: Request, q: str = Query("", max_length=300)):
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
    return templates.TemplateResponse(request, "search.html", {"q": q, "hits": hits})
