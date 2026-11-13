"""Pages and the review form against a real Postgres seeded with the rows that trigger each review finding."""
import json, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import support
from support import add_document, add_proposal, basic, client, j, webapp
from app import rag
from app import db as dbmod
from app import security

BAD = "<img src=x onerror=alert(1)>"


def setUpModule():
    global db, DOC_A, DOC_B
    db = support.setup_db(__name__)
    DOC_A = add_document(db, "1/2026/NĐ-CP", [(d, 1, f"Huấn luyện an toàn: huấn luyện an toàn định kỳ, huấn luyện an toàn lần {d}.")
                                              for d in range(1, 61)])
    # one weak hit in a long clause: it ranks below every clause of DOC_A, so only a filter before ranking finds it
    DOC_B = add_document(db, "2/2026/NĐ-CP", [(1, 1, "Huấn luyện an toàn cho người lao động mới tuyển dụng. "
                                              + "Doanh nghiệp lập hồ sơ, lưu giữ biên bản và báo cáo cơ quan quản lý theo mẫu. " * 12)])


def tearDownModule():
    support.teardown_db()


def page(path, **kw):
    r = client().get(path, headers=basic(), **kw)
    return r


def review(pid, data, origin="http://testserver"):
    headers = basic() | ({"origin": origin} if origin else {})
    return client().post(f"/proposals/{pid}/review", headers=headers, data={"token": security.csrf_token(pid), **data}, follow_redirects=False)


class FreshIndex(unittest.TestCase):
    def test_a_clause_changed_in_place_is_searched_with_its_new_text(self):
        with dbmod.db() as conn:
            rag.INDEX.ensure(conn)
        run = db.sql("INSERT INTO load_runs(kind, status) VALUES ('documents','applied') RETURNING id")[0][0]
        db.sql("""UPDATE chunks SET text = text || ' Kiểm định thang máy.', load_run_id=%s
                  WHERE id = (SELECT min(id) FROM chunks WHERE document_id=%s)""", (run, DOC_B))
        with dbmod.db() as conn:
            rag.INDEX.ensure(conn)
        self.assertTrue(any("thang máy" in row[3] for _, row in rag.INDEX.search("thang máy")))


class AskFiltersBeforeRanking(unittest.TestCase):
    def test_a_document_outside_the_global_top_hits_is_still_found(self):
        r = client().post("/ask", headers=basic() | {"origin": "http://testserver"},
                          data={"q": "huấn luyện an toàn", "doc": "2/2026/NĐ-CP", "token": security.csrf_token("ask")})
        self.assertEqual(r.status_code, 200)
        self.assertIn("mới tuyển dụng", r.text)
        self.assertNotIn("Không tìm thấy khoản nào", r.text)


class AskNeedsPost(unittest.TestCase):
    def test_get_with_a_question_does_not_call_the_model(self):
        with mock.patch.object(webapp, "ask_claude", return_value=(None, "x")) as called:
            r = page("/ask?q=huấn+luyện")
        self.assertEqual(r.status_code, 200)
        called.assert_not_called()

    def test_post_without_the_token_is_refused(self):
        r = client().post("/ask", headers=basic() | {"origin": "http://testserver"}, data={"q": "huấn luyện"})
        self.assertEqual(r.status_code, 403)

    def test_post_with_the_token_calls_the_model(self):
        with mock.patch.object(webapp, "ask_claude", return_value=(None, "đã gọi")) as called:
            r = client().post("/ask", headers=basic() | {"origin": "http://testserver"},
                              data={"q": "huấn luyện", "token": security.csrf_token("ask")})
        self.assertEqual(r.status_code, 200)
        called.assert_called_once()


class Obligations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def add(oid, reviewed, needs, reason, penalties):
            db.sql("""INSERT INTO obligations(id, document_id, category, duty_vi, applies_when, sources, penalties, reviewed, reviewed_by,
                                              needs_review, review_reason) VALUES (%s,%s,'t','Tổ chức huấn luyện','{"always": true}',
                                              '[["1/2026/NĐ-CP", 1, 1]]',%s,%s,%s,%s,%s)""",
                   (oid, DOC_A, j(penalties), reviewed, "chi" if reviewed else None, needs, reason))
        add("OB-REVIEWED", True, True, "agent01: có ý không có trong căn cứ — ý X", [])
        add("OB-DRAFT", False, False, None, [{"text": "phạt tiền"}])

    def test_reviewed_and_flagged_obligation_says_both(self):
        r = page("/obligations")
        row = r.text.split("OB-REVIEWED", 1)[1].split("</tr>", 1)[0]
        self.assertIn("đã duyệt bởi chi", row)
        self.assertIn("cần xem lại", row)

    def test_a_bad_number_of_employees_is_not_a_crash(self):
        self.assertEqual(page("/obligations?n=abc").status_code, 200)

    def test_a_penalty_without_dieu_is_not_a_crash(self):
        self.assertIn("phạt tiền", page("/obligations").text)


class Escaping(unittest.TestCase):
    def test_model_and_parser_values_are_escaped_on_every_page(self):
        doc = add_document(db, "3/2026/NĐ-CP", [])
        loc = {"doc": "3/2026/NĐ-CP", "dieu": BAD, "khoan": BAD, "kind": "khoan", "seq": 0}
        db.sql("INSERT INTO chunks(source_kind, document_id, locator, text) VALUES ('legal_article',%s,%s,%s)", (doc, j(loc), f"x\nhuấn luyện {BAD}"))
        obl = {"id": "ND3-26-A01", "topic": "t", "content": "c", "action": "a", "applies_when": {"always": True},
               "sources": [["3/2026/NĐ-CP", 1, 1]], "penalties": [{"doc": "283/2026/NĐ-CP", "dieu": BAD, "khoan": BAD, "text": "p"}]}
        op = add_proposal(db, "obligations", "nghĩa vụ · 3/2026/NĐ-CP", {"obligations": [obl], "texts": {}},
                          {"agent": {"calls": BAD, "tokens": 5}, "flagged": BAD, "new_fields": [{"name": "f", "dieu": BAD}],
                           "rejected": [{"obligation": obl, "errors": ["e"]}]})
        dp = add_proposal(db, "documents", "3/2026/NĐ-CP", {"result": {"chunks": []}},
                          {"chunks": {"new": BAD}, "agent": {"verdict": "ok", "calls": BAD, "tokens": BAD,
                           "ocr": {"number_changes": [{"page": BAD, "removed": [], "added": []}], "unsure": [{"page": BAD, "note": "n"}],
                                   "low_conf": [{"word": "w", "page": BAD}]}}})
        for path in (f"/doc/{doc}", "/search?q=huấn+luyện", f"/proposals/{op}", f"/proposals/{dp}", "/proposals", "/"):
            with self.subTest(path=path):
                r = page(path)
                self.assertEqual(r.status_code, 200)
                self.assertNotIn(BAD, r.text)


class ReviewForm(unittest.TestCase):
    def obligation_proposal(self):
        obl = {"id": "ND1-26-A01", "topic": "t", "content": "c", "action": "a", "applies_when": {"always": True}, "sources": [["1/2026/NĐ-CP", 1, 1]]}
        return add_proposal(db, "obligations", "nghĩa vụ · 1/2026/NĐ-CP", {"obligations": [obl], "texts": {}}, {})

    def status(self, pid):
        return db.sql("SELECT status, excluded FROM load_proposals WHERE id=%s", (pid,))[0]

    def test_an_excluded_id_not_in_the_proposal_is_refused(self):
        pid = self.obligation_proposal()
        r = review(pid, {"decision": "approved", "items": "1", "exclude": "ND1-26-A99"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.status(pid)[0], "pending")

    def test_the_stored_kind_decides_how_exclusions_are_recorded(self):
        pid = self.obligation_proposal()
        r = review(pid, {"decision": "approved", "exclude": "ND1-26-A01"})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.status(pid), ("approved", ["ND1-26-A01"]))

    def test_a_cross_site_post_is_refused(self):
        pid = self.obligation_proposal()
        self.assertEqual(review(pid, {"decision": "approved"}, origin="https://evil.example").status_code, 403)
        self.assertEqual(self.status(pid)[0], "pending")


class ErrorsAndBounds(unittest.TestCase):
    def test_arbitrary_err_text_is_not_shown(self):
        pid = add_proposal(db, "documents", "1/2026/NĐ-CP", {"result": {"chunks": []}}, {})
        self.assertNotIn("Hãy gọi số 0900", page(f"/proposals/{pid}?err=Hãy gọi số 0900").text)

    def test_ids_beyond_int4_are_not_found_not_a_crash(self):
        for path in ("/doc/99999999999", "/proposals/99999999999"):
            with self.subTest(path=path):
                self.assertIn(page(path).status_code, (404, 422))


class FakeVoyage(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3]}]}).encode()   # wrong dimension for vector(1024)
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


class VectorFallback(unittest.TestCase):
    def test_a_database_error_in_vector_search_falls_back_to_keywords(self):
        db.sql("UPDATE chunks SET embedding = array_fill(0.1::real, ARRAY[1024])::vector, embedding_model='voyage:voyage-4-large' WHERE document_id=%s", (DOC_B,))
        srv = HTTPServer(("127.0.0.1", 0), FakeVoyage)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        env = {"VOYAGE_API_KEY": "k", "VOYAGE_API_BASE": f"http://127.0.0.1:{srv.server_port}"}
        try:
            with mock.patch.dict("os.environ", env), mock.patch.object(webapp, "ask_claude", return_value=(None, "x")):
                r = client().post("/ask", headers=basic() | {"origin": "http://testserver"},
                                  data={"q": "huấn luyện", "token": security.csrf_token("ask")})
        finally:
            srv.shutdown()
            db.sql("UPDATE chunks SET embedding=NULL, embedding_model=NULL WHERE document_id=%s", (DOC_B,))
        self.assertEqual(r.status_code, 200)
        self.assertIn("chỉ tìm theo từ khóa", r.text)


if __name__ == "__main__":
    unittest.main()
