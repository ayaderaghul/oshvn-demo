import json, math, os, re, threading, unicodedata, urllib.request
from collections import Counter, namedtuple

import psycopg

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
STAMP_SQL = "SELECT count(*) AS n, max(id) AS max_id, max(load_run_id) AS max_run FROM chunks WHERE source_kind='legal_article' AND NOT coalesce(retired,false)"


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
