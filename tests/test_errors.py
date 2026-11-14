"""Error reports: what reaches Sentry when a page fails, and what must not."""
import json
import os
import unittest
from unittest import mock

import sentry_sdk
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport
from support import PASSWORD, basic

from app import errors, main
from app.routers import ask as ask_router

DB_URL = "postgresql://oshvn_review:db-pass-123456@ep-x.neon.tech/neondb"
QUESTION = "cau-hoi-rieng-tu"


class Capture(Transport):
    sent = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.headers.get("type") == "event":
                Capture.sent.append(item.payload.json)


class Reports(unittest.TestCase):
    def setUp(self):
        Capture.sent = []
        self.env = mock.patch.dict(os.environ, {"DATABASE_URL": DB_URL, "RENDER_GIT_COMMIT": "abc123"})
        self.env.start()
        sentry_sdk.init(**errors.options("http://key@127.0.0.1:9/1"), transport=Capture)
        main.app.middleware_stack = None
        self.client = TestClient(main.app, base_url="http://testserver", raise_server_exceptions=False)

    def tearDown(self):
        sentry_sdk.init(dsn=None)
        main.app.middleware_stack = None
        self.env.stop()

    def fail_ask(self, exc):
        with mock.patch.object(ask_router, "db", side_effect=exc):
            r = self.client.get(f"/ask?q={QUESTION}", headers=basic(user="Nguyen Chi") | {"cf-connecting-ip": "203.0.113.9",
                                                                                         "cookie": "sid=cookie-value"})
        sentry_sdk.flush()
        return r

    def test_a_failing_page_is_reported_with_its_stack_route_and_release(self):
        self.assertEqual(self.fail_ask(RuntimeError("boom")).status_code, 500)
        self.assertEqual(len(Capture.sent), 1)
        event = Capture.sent[0]
        exc = event["exception"]["values"][-1]
        self.assertEqual((exc["type"], exc["value"]), ("RuntimeError", "boom"))
        self.assertIn("ask_page", [f["function"] for f in exc["stacktrace"]["frames"]])
        self.assertEqual(event["request"]["url"], "http://testserver/ask")
        self.assertEqual((event["release"], event["environment"]), ("abc123", "production"))

    def test_a_report_carries_no_login_question_address_or_secret(self):
        self.fail_ask(RuntimeError(f"connection to {DB_URL} failed, password {PASSWORD}"))
        sent = json.dumps(Capture.sent[0], ensure_ascii=False)
        for leaked in ("db-pass-123456", PASSWORD, QUESTION, "Nguyen Chi", "203.0.113.9", "cookie-value", "Basic ", "uthorization"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, sent)
        self.assertIn("postgresql://oshvn_review:[secret]@ep-x.neon.tech/neondb", sent)
        self.assertNotIn("vars", json.dumps(Capture.sent[0]["exception"]))

    def test_wrong_passwords_and_missing_pages_are_not_reported(self):
        self.client.get("/", headers=basic(password="wrong"))
        self.client.get("/no-such-page", headers=basic())
        sentry_sdk.flush()
        self.assertEqual(Capture.sent, [])

    def test_a_missing_database_url_is_reported(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": ""}):
            self.assertEqual(self.client.get("/", headers=basic()).status_code, 500)
        sentry_sdk.flush()
        self.assertEqual(len(Capture.sent), 1)


class Off(unittest.TestCase):
    def test_nothing_is_set_up_without_a_dsn(self):
        with mock.patch.dict(os.environ, {"SENTRY_DSN": ""}), mock.patch.object(sentry_sdk, "init") as init:
            errors.init()
        init.assert_not_called()


class Scrub(unittest.TestCase):
    def test_long_error_text_is_cut(self):
        event = errors.scrub({"exception": {"values": [{"type": "E", "value": "x" * 5000}]}})
        self.assertLess(len(event["exception"]["values"][0]["value"]), 700)


if __name__ == "__main__":
    unittest.main()
