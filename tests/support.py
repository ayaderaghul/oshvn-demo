"""A throwaway Postgres (Docker, pgvector) with tests/fixtures/schema.sql, and a TestClient logged in to the app."""
import base64, json, os, socket, subprocess, sys, time, unittest, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PASSWORD = "test-password"
os.environ["APP_PASSWORD"] = PASSWORD
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("VOYAGE_API_KEY", None)

from app import main as webapp  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def basic(user="chi", password=PASSWORD):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def client():
    return TestClient(webapp.app, base_url="http://testserver")


def docker_ok():
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


class Database:
    def __init__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]
        self.name = f"oshvn-demo-test-{uuid.uuid4().hex[:8]}"
        subprocess.run(["docker", "run", "-d", "--rm", "--name", self.name, "--label", "oshvn.demo.test=1",
                        "-e", "POSTGRES_PASSWORD=t", "-e", "POSTGRES_DB=t", "-p", f"127.0.0.1:{self.port}:5432",
                        "pgvector/pgvector:pg17"], check=True, capture_output=True)
        self.url = f"postgresql://postgres:t@127.0.0.1:{self.port}/t"
        ok = 0
        for _ in range(90):
            r = subprocess.run(["docker", "exec", self.name, "psql", "-U", "postgres", "-h", "127.0.0.1", "-d", "t", "-c", "SELECT 1"],
                               capture_output=True)
            ok = ok + 1 if r.returncode == 0 else 0
            if ok == 2: break
            time.sleep(1)
        subprocess.run(["docker", "exec", "-i", self.name, "psql", "-U", "postgres", "-d", "t", "-v", "ON_ERROR_STOP=1", "-q"],
                       input=(ROOT / "tests" / "fixtures" / "schema.sql").read_bytes(), check=True, capture_output=True)
        os.environ["DATABASE_URL"] = self.url

    def sql(self, query, params=None):
        import psycopg
        with psycopg.connect(self.url, autocommit=True) as conn:
            cur = conn.execute(query, params)
            return cur.fetchall() if cur.description else None

    def stop(self):
        subprocess.run(["docker", "rm", "-f", "-v", self.name], capture_output=True)


DB = None


def setup_db(test_module):
    global DB
    if not docker_ok():
        raise unittest.SkipTest("Docker is not running")
    DB = Database()
    return DB


def teardown_db():
    if DB: DB.stop()


def j(x):
    return json.dumps(x, ensure_ascii=False)


def add_document(db, number, clauses):
    """clauses: list of (dieu, khoan, text). Returns the document id."""
    run = db.sql("INSERT INTO load_runs(kind, status) VALUES ('documents','applied') RETURNING id")[0][0]
    did = db.sql("INSERT INTO legal_documents(number, type, title_vi, load_run_id) VALUES (%s,'decree','t',%s) RETURNING id",
                 (number, run))[0][0]
    for seq, (dieu, khoan, text) in enumerate(clauses):
        loc = {"doc": number, "dieu": dieu, "khoan": khoan, "kind": "khoan", "seq": seq, "dieu_title": "Tiêu đề",
               "chuong": "I", "chuong_title": "CHUNG", "ref": f"Điều {dieu}, khoản {khoan}"}
        db.sql("INSERT INTO chunks(source_kind, document_id, locator, text, text_sha256, load_run_id) VALUES ('legal_article',%s,%s,%s,'x',%s)",
               (did, j(loc), f"Điều {dieu}. Tiêu đề — Khoản {khoan}\n{text}", run))
    return did


def add_proposal(db, kind, doc_code, payload, report, status="pending", excluded=None):
    return db.sql("""INSERT INTO load_proposals(doc_code, file_name, source_sha256, parser_version, options, payload, report, status, kind, excluded)
                     VALUES (%s,'f.docx','s','p','{}',%s,%s,%s,%s,%s) RETURNING id""",
                  (doc_code, j(payload), j(report), status, kind, j(excluded) if excluded is not None else None))[0][0]
