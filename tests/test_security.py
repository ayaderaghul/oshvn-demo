"""Checks that need no database: authentication, security headers, CSRF origin, pure helpers."""
import os, threading, unittest
from collections import Counter

from support import basic, client, webapp


class EveryRouteNeedsThePassword(unittest.TestCase):
    def test_all_routes_but_healthz_answer_401_without_credentials(self):
        c = client()
        for route in webapp.app.routes:
            path = getattr(route, "path", "")
            if not path or path == "/healthz":
                continue
            url = path.replace("{doc_id}", "1").replace("{pid}", "1")
            for method in getattr(route, "methods", {"GET"}) - {"HEAD"}:
                with self.subTest(method=method, path=path):
                    self.assertEqual(c.request(method, url).status_code, 401)

    def test_healthz_is_public(self):
        self.assertEqual(client().get("/healthz").text, "ok")


class SecurityHeaders(unittest.TestCase):
    def test_pages_refuse_framing_and_sniffing(self):
        for r in (client().get("/healthz"), client().get("/")):
            with self.subTest(status=r.status_code):
                self.assertEqual(r.headers.get("x-frame-options"), "DENY")
                self.assertIn("frame-ancestors 'none'", r.headers.get("content-security-policy", ""))
                self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")


class Login(unittest.TestCase):
    def setUp(self):
        webapp.FAILED_LOGINS.clear()

    def test_repeated_wrong_passwords_are_throttled(self):
        c = client()
        codes = [c.get("/", headers=basic(password="wrong")).status_code for _ in range(webapp.LOGIN_FAILURES_ALLOWED + 1)]
        self.assertEqual(codes[:-1], [401] * webapp.LOGIN_FAILURES_ALLOWED)
        self.assertEqual(codes[-1], 429)

    def test_reviewer_name_loses_invisible_characters(self):
        self.assertEqual(webapp.reviewer_name("​chi‍ "), "chi")
        self.assertEqual(webapp.reviewer_name("Nguyễn  Chi"), "Nguyễn Chi")
        for blank in ("​‍", "ㅤ⠀", "ᅟﾠ", " 　 "):
            with self.subTest(name=repr(blank)):
                self.assertEqual(webapp.reviewer_name(blank), "")

    def test_one_client_is_one_counter_whatever_proxy_hop_it_came_through(self):
        # production, 2026-11-11: the same client reached the app with a different last X-Forwarded-For hop per
        # connection, so a counter keyed on that hop never reached the limit for a guesser who reconnects
        c = client()
        codes = [c.get("/", headers=basic(password="wrong") | {"cf-connecting-ip": "93.41.0.110",
                                                                "x-forwarded-for": f"93.41.0.110, 172.68.0.{i}"}).status_code
                 for i in range(webapp.LOGIN_FAILURES_ALLOWED + 1)]
        self.assertEqual(codes[-1], 429)

    def test_a_locked_out_client_does_not_lock_out_another(self):
        c = client()
        for i in range(webapp.LOGIN_FAILURES_ALLOWED + 1):
            c.get("/", headers=basic(password="wrong") | {"cf-connecting-ip": "93.41.0.110", "x-forwarded-for": "172.68.0.9"})
        other = {"cf-connecting-ip": "198.51.100.7", "x-forwarded-for": "172.68.0.9"}
        self.assertEqual(c.get("/", headers=basic(password="wrong") | other).status_code, 401)
        self.assertEqual(c.get("/no-such-page", headers=basic() | other).status_code, 404)   # past the login, not 429

    def test_a_forged_forwarded_for_does_not_change_the_counter(self):
        c = client()
        codes = [c.get("/", headers=basic(password="wrong") | {"cf-connecting-ip": "93.41.0.110",
                                                                "x-forwarded-for": f"10.0.0.{i}"}).status_code
                 for i in range(webapp.LOGIN_FAILURES_ALLOWED + 1)]
        self.assertEqual(codes[-1], 429)

    def test_requests_without_credentials_leave_no_trace(self):
        c = client()
        for i in range(20):
            c.get("/", headers={"cf-connecting-ip": f"192.0.2.{i}"})
        self.assertEqual(webapp.FAILED_LOGINS, {})

    def test_a_correct_login_clears_the_failures(self):
        c = client()
        for _ in range(webapp.LOGIN_FAILURES_ALLOWED - 1):
            c.get("/healthz-x", headers=basic(password="wrong"))
        c.get("/healthz-x", headers=basic())
        self.assertEqual(webapp.FAILED_LOGINS, {})


class ReviewOrigin(unittest.TestCase):
    def setUp(self):
        webapp.FAILED_LOGINS.clear()

    def test_review_post_without_origin_or_referer_is_refused(self):
        r = client().post("/proposals/1/review", headers=basic(), data={"token": webapp.csrf_token(1), "decision": "approved"})
        self.assertEqual(r.status_code, 403)

    def test_referer_of_another_site_is_refused_and_of_this_site_is_accepted(self):
        class R:
            def __init__(self, h): self.headers = h
        self.assertFalse(webapp.same_origin(R({"host": "app.example", "referer": "https://evil.example/x"})))
        self.assertTrue(webapp.same_origin(R({"host": "app.example", "referer": "https://app.example/proposals/1"})))
        self.assertFalse(webapp.same_origin(R({"host": "app.example", "origin": "null"})))


class AgentCell(unittest.TestCase):
    def test_an_unknown_verdict_is_not_written_into_the_page(self):
        self.assertNotIn("<img", webapp.agent_cell("<img src=x onerror=1>", "c", "parse"))


class Nice(unittest.TestCase):
    def test_words_inside_other_words_are_left_alone(self):
        self.assertEqual(webapp.nice("trueness falsely needsy"), "trueness falsely needsy")

    def test_whole_words_are_translated(self):
        self.assertEqual(webapp.nice("strict = true"), "Có thiết bị nghiêm ngặt = có")


HITS = [(1.0, (1, "1/2026/NĐ-CP", {"dieu": 2, "khoan": 1}, "Điều 2 — Khoản 1\nPhạt tiền từ 1.000.000 đồng đến 5.000.000 đồng."), "từ khóa")]


class AnswerChecks(unittest.TestCase):
    def test_model_output_of_the_wrong_shape_is_coerced_not_a_crash(self):
        a = webapp.parse_answer({"answer": ["x"], "used": "1", "not_found": 3})
        self.assertEqual((a["answer"], a["used"], a["not_found"]), ("['x']", [], "3"))
        self.assertEqual(webapp.parse_answer({"answer": "a", "used": [1, "2", "²", None, True]})["used"], [1, 2])

    def test_thousands_written_with_commas_match_dots_in_the_source(self):
        chk = webapp.check_answer("Phạt từ 1,000,000 đồng [1].", [1], HITS)
        self.assertEqual(chk["bad_num"], [])

    def test_a_number_not_in_the_cited_clause_is_reported(self):
        self.assertEqual(webapp.check_answer("Phạt 7.000.000 đồng [1].", [1], HITS)["bad_num"], ["7.000.000"])

    def test_an_answer_that_cites_nothing_is_flagged(self):
        self.assertTrue(webapp.check_answer("Có, phải thành lập.", [], HITS)["no_cite"])

    def test_a_citation_outside_the_hits_is_reported(self):
        self.assertEqual(webapp.check_answer("Xem [3].", [], HITS)["bad_cite"], [3])

    def test_a_huge_citation_number_is_not_a_crash(self):
        self.assertTrue(webapp.check_answer("Xem [" + "9" * 5000 + "].", [], HITS)["no_cite"])
        self.assertEqual(webapp.parse_answer({"answer": "a", "used": ["9" * 5000, 10 ** 5000]})["used"], [])

    def test_a_list_of_clause_numbers_is_not_a_false_alarm(self):
        hits = [(1.0, (1, "1/2026/NĐ-CP", {"dieu": 2}, "Theo khoản 5 và khoản 7 Điều 2."), "từ khóa")]
        self.assertEqual(webapp.check_answer("Xem khoản 5,7 [1].", [1], hits)["bad_num"], [])


class FakeConn:
    def __init__(self, rows_by_stamp):
        self.rows_by_stamp, self.stamp = rows_by_stamp, 0

    def execute(self, sql, params=None):
        class R:
            def __init__(s, v): s.v = v
            def fetchone(s): return s.v
            def fetchall(s): return s.v
        if "count(*)" in sql:
            return R((self.stamp, self.stamp, self.stamp))
        return R(self.rows_by_stamp[self.stamp % 2])


class IndexSnapshot(unittest.TestCase):
    def test_search_never_mixes_two_builds(self):
        a = [(1, "A", {"dieu": i}, f"huấn luyện an toàn {i}") for i in range(300)]
        b = [(2, "B", {"dieu": i}, "khám sức khỏe") for i in range(5)]
        conn, idx, errors = FakeConn({0: a, 1: b}), webapp.Index(), []
        stop = threading.Event()

        def rebuild():
            while not stop.is_set():
                conn.stamp += 1; idx.ensure(conn)

        def search():
            try:
                for _ in range(300):
                    for _, row in idx.search("huấn luyện"):
                        if "huấn luyện" not in row[3]: errors.append(row)
            except Exception as e:
                errors.append(repr(e))

        idx.ensure(conn)
        t = threading.Thread(target=rebuild); t.start()
        readers = [threading.Thread(target=search) for _ in range(4)]
        [r.start() for r in readers]; [r.join() for r in readers]
        stop.set(); t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
