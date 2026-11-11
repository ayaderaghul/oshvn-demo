#!/usr/bin/env python3
"""Drive oshvn-demo the way a reviewer does: a real uvicorn server, a throwaway Postgres, and stand-ins for Claude and
Voyage on the app's own ASK_API_BASE / VOYAGE_API_BASE settings.

  python .claude/skills/verify/scripts/verify.py up                    venv, database + seed, fake model server, app
  python .claude/skills/verify/scripts/verify.py doctor                is this run worth driving?
  python .claude/skills/verify/scripts/verify.py get PATH              logged-in GET; page saved as .html and .txt
  python .claude/skills/verify/scripts/verify.py review PID approved|rejected [--exclude ID ...] [--note TEXT]
  python .claude/skills/verify/scripts/verify.py ask "QUESTION" [--doc NUMBER]
  python .claude/skills/verify/scripts/verify.py raw METHOD PATH [--user U] [--password P] [--header K:V ...] [--form K=V ...]
  python .claude/skills/verify/scripts/verify.py sql "SELECT ..."      read-only query
  python .claude/skills/verify/scripts/verify.py calls                 what the app sent to the fake Claude / Voyage
  python .claude/skills/verify/scripts/verify.py down                  stop what this run started; evidence is kept

Every command takes --run ID before the subcommand (default: the latest live run). Evidence: verify_out/<run>/.
"""
import argparse, base64, datetime, html, json, os, re, secrets, socket, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]
OUT = ROOT / "verify_out"
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
LABEL = "oshvn.demo.verify=1"
sys.stdout.reconfigure(encoding="utf-8")


def die(msg):
    print(f"verify: {msg}", file=sys.stderr); sys.exit(1)


def sh(*cmd, check=True, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if check and r.returncode:
        die(f"{' '.join(map(str, cmd))} -> exit {r.returncode}\n{r.stdout}{r.stderr}")
    return r


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def run_dir(run):
    if run:
        d = OUT / run
    else:
        live = sorted(p for p in OUT.glob("*") if (p / "state.json").exists()) if OUT.exists() else []
        if not live: die("no live run: `verify.py up` first")
        d = live[-1]
    if not (d / "state.json").exists(): die(f"run {d.name} is not live")
    return d


def state(d):
    return json.loads((d / "state.json").read_text(encoding="utf-8"))


def step(d, slug):
    """The path prefix of the next evidence step: NNN-slug, numbered in run order. A step's files share one number."""
    n = len({p.name.split("-", 1)[0] for p in d.glob("[0-9][0-9][0-9]-*")}) + 1
    return d / f"{n:03d}-{slug}"


def save(d, slug, suffix, text):
    f = step(d, slug).with_name(step(d, slug).name + suffix)
    f.write_text(text, encoding="utf-8")
    return f


def page_text(body):
    body = re.sub(r"(?s)<style.*?</style>", "", body)
    body = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h[1-6]|table|details|summary)>", "\n", body)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", html.unescape(re.sub(r"<[^>]+>", " ", body)))).strip()


# ---------------------------------------------------------------- HTTP as the reviewer's browser sends it
def request(st, method, path, form=None, user="verify", password=None, headers=None, origin=True):
    if not path.startswith("/"):
        die(f"path must start with /, got {path!r}. Git Bash rewrites /paths into Windows paths: run with MSYS_NO_PATHCONV=1")
    url = st["base"] + urllib.parse.quote(path, safe="/?&=#%+:,")   # a browser percent-encodes Vietnamese letters too
    data = urllib.parse.urlencode(form, doseq=True).encode() if form is not None else None
    h = {"Authorization": "Basic " + base64.b64encode(f"{user}:{password or st['password']}".encode()).decode()}
    if data is not None:
        h["Content-Type"] = "application/x-www-form-urlencoded"
        if origin: h["Origin"] = st["base"]
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)   # local server: never via a proxy
    try:
        r = opener.open(req, timeout=120)
        return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # Windows reads a system proxy from the registry


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def record(d, slug, method, path, status, headers, body):
    loc = headers.get("location") or headers.get("Location")
    summary = f"{method} {path} -> {status}" + (f" Location: {loc}" if loc else "")
    hdrs = {k.lower(): v for k, v in headers.items()}
    shown = "\n".join(f"{k}: {hdrs[k]}" for k in ("x-frame-options", "content-security-policy", "x-content-type-options") if k in hdrs)
    base = step(d, slug)
    base.with_name(base.name + ".html").write_text(body, encoding="utf-8")
    f = base.with_name(base.name + ".txt")
    f.write_text(summary + "\n" + shown + "\n\n" + page_text(body), encoding="utf-8")
    print(summary); print(f"[{f.relative_to(ROOT)}]")
    return summary


def token_from(st, path):
    status, _, body = request(st, "GET", path)
    m = re.search(r"name='token' value='([0-9a-f]+)'", body)
    if not m: die(f"no form token on {path} (status {status}): the proposal is not pending, or the page changed")
    return m.group(1)


# ---------------------------------------------------------------- stand-in for Claude and Voyage
class FakeModels(BaseHTTPRequestHandler):
    log_file = None

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        if self.path.endswith("/v1/embeddings"):
            reply = {"data": [{"index": 0, "embedding": [0.1] * 1024}], "usage": {"total_tokens": 8}}
        else:
            prompt = body["messages"][0]["content"]
            first = re.search(r"\[1\][^\n]*\n([^\n]+)", prompt)
            sentence = (first.group(1) if first else "").split("\n")[0][:300]
            answer = f"Theo [1]: {sentence}"
            if "SAI SỐ" in prompt:   # lets a journey check the warning for a number that is not in the cited clause
                answer += " Thời hạn là 99 ngày [1]."
            reply = {"content": [{"type": "text", "text": json.dumps({"answer": answer, "used": [1], "not_found": ""}, ensure_ascii=False)}],
                     "usage": {"input_tokens": len(prompt) // 4, "output_tokens": 60}}
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"path": self.path, "model": body.get("model"), "input": str(body.get("input") or body.get("messages"))[:300]},
                               ensure_ascii=False) + "\n")
        out = json.dumps(reply, ensure_ascii=False).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out)))
        self.end_headers(); self.wfile.write(out)

    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"fake-models ok")

    def log_message(self, *a):
        pass


def cmd_fake(a):
    FakeModels.log_file = a.log
    HTTPServer(("127.0.0.1", a.port), FakeModels).serve_forever()


# ---------------------------------------------------------------- lifecycle
def spawn(args, log, env=None):
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(args, cwd=ROOT, env=env, stdout=open(log, "a", encoding="utf-8"), stderr=subprocess.STDOUT,
                            creationflags=flags, start_new_session=(os.name != "nt")).pid


def kill(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try: os.killpg(pid, 15)
        except ProcessLookupError: pass


def alive(pid):
    if os.name == "nt":
        return str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    try: os.kill(pid, 0); return True
    except OSError: return False


def wait_for(fn, what, seconds=60):
    for _ in range(seconds * 2):
        try:
            if fn(): return
        except Exception:
            pass
        time.sleep(0.5)
    die(f"{what} did not become ready")


def cmd_up(a):
    if sh("docker", "info", check=False).returncode:
        die("Docker is not running. Start Docker Desktop and wait until `docker info` succeeds.")
    if not VENV_PY.exists():
        print("creating .venv and installing requirements.txt …")
        sh(sys.executable, "-m", "venv", str(ROOT / ".venv"))
        sh(str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt"))
    run = a.run or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = OUT / run; d.mkdir(parents=True, exist_ok=True)
    db_port, fake_port, app_port = free_port(), free_port(), free_port()
    st = {"run": run, "container": f"oshvn-demo-verify-{run}", "db_port": db_port, "fake_port": fake_port, "app_port": app_port,
          "base": f"http://127.0.0.1:{app_port}", "password": secrets.token_urlsafe(18),
          "db_url": f"postgresql://postgres:verify@127.0.0.1:{db_port}/verify", "pids": {}}
    (d / "state.json").write_text(json.dumps(st, indent=1), encoding="utf-8")

    sh("docker", "run", "-d", "--name", st["container"], "--label", LABEL, "-e", "POSTGRES_PASSWORD=verify", "-e", "POSTGRES_DB=verify",
       "-p", f"127.0.0.1:{db_port}:5432", "pgvector/pgvector:pg17")
    ok = [0]
    def db_ready():   # the image's init server restarts once: require two successes in a row from outside the container
        r = sh("docker", "exec", st["container"], "psql", "-U", "postgres", "-h", "127.0.0.1", "-d", "verify", "-c", "SELECT 1", check=False)
        ok[0] = ok[0] + 1 if r.returncode == 0 else 0
        return ok[0] >= 2
    wait_for(db_ready, "postgres", 120)
    for f in (ROOT / "tests" / "fixtures" / "schema.sql", SKILL / "fixtures" / "seed.sql"):
        sh("docker", "exec", "-i", st["container"], "psql", "-U", "postgres", "-d", "verify", "-v", "ON_ERROR_STOP=1", "-q",
           input=f.read_text(encoding="utf-8"))

    st["pids"]["fake"] = spawn([sys.executable, str(Path(__file__).resolve()), "fake", "--port", str(fake_port), "--log", str(d / "model-calls.jsonl")],
                               d / "fake.log")
    env = {**os.environ, "DATABASE_URL": st["db_url"], "APP_PASSWORD": st["password"],
           "ANTHROPIC_API_KEY": "verify-fake", "ASK_API_BASE": f"http://127.0.0.1:{fake_port}",
           "VOYAGE_API_KEY": "verify-fake", "VOYAGE_API_BASE": f"http://127.0.0.1:{fake_port}", "PYTHONIOENCODING": "utf-8"}
    st["pids"]["app"] = spawn([str(VENV_PY), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(app_port)], d / "app.log", env)
    (d / "state.json").write_text(json.dumps(st, indent=1), encoding="utf-8")
    wait_for(lambda: DIRECT.open(f"http://127.0.0.1:{fake_port}/", timeout=2).status == 200, "fake model server")
    # ready means usable: the logged-in home page lists the seeded document, not just that /healthz answers
    wait_for(lambda: "1/2026/NĐ-CP" in request(st, "GET", "/")[2], "app", 90)
    print(f"ready: run {run} · app {st['base']} · user any name, password in verify_out/{run}/state.json")


def cmd_doctor(a):
    d = run_dir(a.run); st = state(d); problems = []
    for name, pid in st["pids"].items():
        if not alive(pid): problems.append(f"{name} process {pid} is not running (see verify_out/{st['run']}/{name}.log)")
    r = sh("docker", "inspect", "-f", "{{.State.Running}} {{index .Config.Labels \"oshvn.demo.verify\"}}", st["container"], check=False)
    if r.stdout.split()[:2] != ["true", "1"]: problems.append(f"container {st['container']} not running or not labelled {LABEL}")
    if not st["base"].startswith("http://127.0.0.1:"): problems.append("app URL is not local")
    try:
        if DIRECT.open(st["base"] + "/healthz", timeout=5).read() != b"ok": problems.append("/healthz did not answer ok")
        status, _, body = request(st, "GET", "/")
        if status != 200 or "1/2026/NĐ-CP" not in body: problems.append(f"logged-in / gave {status} without the seeded document")
    except Exception as e:
        problems.append(f"app unreachable: {e}")
    print(f"run {st['run']} · {st['base']} · db {st['container']} · fake models :{st['fake_port']}")
    for p in problems: print("PROBLEM:", p)
    print("doctor: OK" if not problems else "doctor: NOT OK"); sys.exit(1 if problems else 0)


def cmd_get(a):
    d = run_dir(a.run); st = state(d)
    record(d, a.slug or "get", "GET", a.path, *request(st, "GET", a.path))


def cmd_review(a):
    d = run_dir(a.run); st = state(d)
    form = {"token": token_from(st, f"/proposals/{a.pid}"), "decision": a.decision, "note": a.note or "", "exclude": a.exclude or []}
    record(d, a.slug or f"review-{a.pid}", "POST", f"/proposals/{a.pid}/review", *request(st, "POST", f"/proposals/{a.pid}/review", form))


def cmd_ask(a):
    d = run_dir(a.run); st = state(d)
    form = {"q": a.question, "doc": a.doc or "", "token": token_from(st, "/ask")}
    record(d, a.slug or "ask", "POST", "/ask", *request(st, "POST", "/ask", form))


def cmd_raw(a):
    d = run_dir(a.run); st = state(d)
    form = dict(x.split("=", 1) for x in a.form) if a.form else None
    headers = dict(x.split(":", 1) for x in a.header) if a.header else None
    record(d, a.slug or "raw", a.method, a.path,
           *request(st, a.method, a.path, form, user=a.user, password=a.password, headers=headers, origin=not a.no_origin))


def cmd_sql(a):
    d = run_dir(a.run); st = state(d)
    r = sh("docker", "exec", "-i", st["container"], "psql", "-U", "postgres", "-d", "verify", "-X", "-q", "-c",
           f"BEGIN READ ONLY; {a.query}; ROLLBACK;")
    f = save(d, a.slug or "sql", ".txt", f"$ {a.query}\n{r.stdout}")
    print(r.stdout.rstrip()); print(f"[{f.relative_to(ROOT)}]")


def cmd_calls(a):
    d = run_dir(a.run)
    f = d / "model-calls.jsonl"
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    print(f"{len(lines)} call(s) to the fake Claude / Voyage")
    for ln in lines: print(" ", ln[:240])


def cmd_down(a):
    d = run_dir(a.run); st = state(d)
    for name, pid in st["pids"].items():
        kill(pid); print(f"stopped {name} ({pid})")
    r = sh("docker", "inspect", "-f", "{{index .Config.Labels \"oshvn.demo.verify\"}}", st["container"], check=False)
    if r.returncode: print(f"container {st['container']} already gone")
    elif r.stdout.strip() != "1": die(f"{st['container']} is not labelled {LABEL}; refusing to remove it")
    else: sh("docker", "rm", "-f", "-v", st["container"]); print(f"removed {st['container']}")
    (d / "state.json").rename(d / "state.down.json")
    print(f"evidence kept in {d.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up"); sub.add_parser("doctor"); sub.add_parser("calls"); sub.add_parser("down")
    p = sub.add_parser("get"); p.add_argument("path"); p.add_argument("--slug")
    p = sub.add_parser("review"); p.add_argument("pid", type=int); p.add_argument("decision", choices=["approved", "rejected"])
    p.add_argument("--exclude", action="append"); p.add_argument("--note"); p.add_argument("--slug")
    p = sub.add_parser("ask"); p.add_argument("question"); p.add_argument("--doc"); p.add_argument("--slug")
    p = sub.add_parser("raw"); p.add_argument("method"); p.add_argument("path"); p.add_argument("--user", default="verify")
    p.add_argument("--password"); p.add_argument("--header", action="append"); p.add_argument("--form", action="append")
    p.add_argument("--no-origin", action="store_true", help="POST without Origin, as a cross-site or scripted client"); p.add_argument("--slug")
    p = sub.add_parser("sql"); p.add_argument("query"); p.add_argument("--slug")
    p = sub.add_parser("fake", help=argparse.SUPPRESS); p.add_argument("--port", type=int); p.add_argument("--log")
    a = ap.parse_args()
    {"up": cmd_up, "doctor": cmd_doctor, "get": cmd_get, "review": cmd_review, "ask": cmd_ask, "raw": cmd_raw,
     "sql": cmd_sql, "calls": cmd_calls, "down": cmd_down, "fake": cmd_fake}[a.cmd](a)


if __name__ == "__main__":
    main()
