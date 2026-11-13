"""Run oshvn-demo under instrumentation against the verify skill's database and fake models.

Starts its own run with `verify.py up`, serves the app in this process (so the heap is visible), drives a fixed load,
then `verify.py down`. Writes to verify_out/<run>/observe/: trace.json (Chrome trace format, open in
https://ui.perfetto.dev), heap-*.snapshot (tracemalloc dumps), and report.txt (latency per route, time split, heap
growth by source line).

usage: .venv python observe.py [--bad-logins N]   N wrong passwords from distinct addresses per phase (default 11000,
                                                   just over LOGIN_TRACKED_MAX, so the second phase shows the cap)
"""
import argparse, base64, contextvars, gc, json, os, re, socket, statistics, subprocess, sys, threading, time, tracemalloc
import urllib.error, urllib.parse, urllib.request
from collections import defaultdict
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--bad-logins", type=int, default=11000)
ARGS = ap.parse_args()
REPO = Path(__file__).resolve().parents[4]
VERIFY = [sys.executable, str(Path(__file__).resolve().with_name("verify.py"))]

up = subprocess.run(VERIFY + ["up"], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
m = re.search(r"ready: run (\S+)", up.stdout + up.stderr)
if not m:
    sys.exit("verify up failed:\n" + up.stdout + up.stderr)
RUN = m.group(1)
OUT = REPO / "verify_out" / RUN / "observe"
OUT.mkdir(parents=True, exist_ok=True)
st = json.loads((REPO / "verify_out" / RUN / "state.json").read_text(encoding="utf-8"))
fake = f"http://127.0.0.1:{st['fake_port']}"
os.environ |= {"DATABASE_URL": st["db_url"], "APP_PASSWORD": st["password"], "ANTHROPIC_API_KEY": "verify-fake",
               "ASK_API_BASE": fake, "VOYAGE_API_KEY": "verify-fake", "VOYAGE_API_BASE": fake, "ASK_LIMIT_PER_HOUR": "100000"}

tracemalloc.start(15)
sys.path.insert(0, str(REPO))
import jinja2, psycopg, uvicorn  # noqa: E402
from app import claude, main, rag, security  # noqa: E402

EVENTS, REQ = [], contextvars.ContextVar("req", default=0)
T0 = time.perf_counter()
SPANS = defaultdict(lambda: defaultdict(float))
COUNTS = defaultdict(lambda: defaultdict(int))


def us():
    return (time.perf_counter() - T0) * 1e6


def span(cat, name, fn, *a, **kw):
    rid, start = REQ.get(), us()
    try:
        return fn(*a, **kw)
    finally:
        dur = us() - start
        EVENTS.append({"ph": "X", "pid": 1, "tid": rid, "ts": start, "dur": dur, "name": name, "cat": cat})
        SPANS[rid][cat] += dur
        COUNTS[rid][cat] += 1


_connect, _execute, _render, _urlopen = psycopg.connect, psycopg.Cursor.execute, jinja2.Template.render, urllib.request.urlopen
psycopg.connect = lambda *a, **kw: span("db.connect", "connect", _connect, *a, **kw)
psycopg.Cursor.execute = lambda self, q, *a, **kw: span("db.query", " ".join(str(q).split())[:70], _execute, self, q, *a, **kw)
jinja2.Template.render = lambda self, *a, **kw: span("render", f"render {self.name}", _render, self, *a, **kw)
urllib.request.urlopen = lambda req, *a, **kw: span("http.out", "POST " + urllib.parse.urlsplit(getattr(req, "full_url", req)).path,
                                                    _urlopen, req, *a, **kw)

NEXT, ROUTE = [0], {}


async def traced(scope, receive, send):
    if scope["type"] != "http":
        return await main.app(scope, receive, send)
    NEXT[0] += 1
    rid = NEXT[0]
    REQ.set(rid)
    path = re.sub(r"/\d+", "/{id}", scope["path"])
    status = [0]

    async def send2(msg):
        if msg["type"] == "http.response.start":
            status[0] = msg["status"]
        await send(msg)
    start = us()
    try:
        await main.app(scope, receive, send2)
    finally:
        dur = us() - start
        name = f"{scope['method']} {path} {status[0]}"
        ROUTE[rid] = (name, dur)
        EVENTS.append({"ph": "X", "pid": 1, "tid": rid, "ts": start, "dur": dur, "name": name, "cat": "request"})


with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]
server = uvicorn.Server(uvicorn.Config(traced, host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
while not server.started:
    time.sleep(0.05)
BASE = f"http://127.0.0.1:{PORT}"
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
AUTH = "Basic " + base64.b64encode(f"observe:{st['password']}".encode()).decode()


def call(method, path, headers=None, form=None, auth=AUTH):
    h = {"Authorization": auth} | (headers or {})
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    if data is not None:
        h |= {"Content-Type": "application/x-www-form-urlencoded", "Origin": BASE}
    try:
        with DIRECT.open(urllib.request.Request(BASE + urllib.parse.quote(path, safe="/?=&"), data, h, method=method)) as r:
            r.read(); return r.status
    except urllib.error.HTTPError as e:
        e.read(); return e.code


PAGES = ["/", "/doc/1", "/search?q=huấn luyện", "/obligations", "/runs", "/proposals", "/proposals/1", "/proposals/2", "/ask"]
ASK_TOKEN = security.csrf_token("ask")


def pages(n):
    for _ in range(n):
        for p in PAGES:
            call("GET", p)


def asks(n):
    for i in range(n):
        call("POST", "/ask", form={"q": f"huấn luyện an toàn lần {i}", "doc": "", "token": ASK_TOKEN})


def bad_logins(n, offset):
    bad = "Basic " + base64.b64encode(b"x:wrong").decode()
    for i in range(offset, offset + n):
        call("GET", "/", headers={"cf-connecting-ip": f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}"}, auth=bad)


def snap(label):
    gc.collect()
    s = tracemalloc.take_snapshot().filter_traces([tracemalloc.Filter(False, __file__), tracemalloc.Filter(False, tracemalloc.__file__)])
    s.dump(str(OUT / f"heap-{label}.snapshot"))
    cur = sum(t.size for t in s.traces)
    state = {"FAILED_LOGINS keys": len(security.FAILED_LOGINS), "ASK_LOG entries": len(claude.ASK_LOG),
             "INDEX rows": len(rag.INDEX.snap[1])}
    return s, cur, state


report = []
try:
    N = ARGS.bad_logins
    pages(2); asks(3)
    sA = snap("A-warm"); phases = [("A warm",) + sA[1:]]
    pages(20); asks(100)
    sB = snap("B-after-pages-and-asks"); phases.append(("B after 180 page views + 100 asks",) + sB[1:])
    bad_logins(N, 0)
    sC = snap(f"C-after-{N}-bad-logins"); phases.append((f"C after {N} wrong passwords from distinct IPs",) + sC[1:])
    bad_logins(N, N)
    sD = snap(f"D-after-{2 * N}-bad-logins"); phases.append((f"D after {2 * N} wrong passwords from distinct IPs",) + sD[1:])
finally:
    server.should_exit = True
    subprocess.run(VERIFY + ["--run", RUN, "down"], cwd=REPO, capture_output=True)

trace_events = [e for e in EVENTS if ROUTE.get(e["tid"], ("",))[0].split(" ")[-1] != "401"] + \
               [e for e in EVENTS if ROUTE.get(e["tid"], ("",))[0].endswith("401")][:200]
(OUT / "trace.json").write_text(json.dumps({"traceEvents": trace_events, "displayTimeUnit": "ms"}), encoding="utf-8")

by_route = defaultdict(list)
for rid, (name, dur) in ROUTE.items():
    by_route[name].append(rid)
report.append(f"run {RUN} · {len(ROUTE)} requests\n")
report.append(f"{'route':42} {'n':>5} {'p50 ms':>7} {'p95 ms':>7} {'conn/req':>8} {'sql/req':>7} {'conn%':>5} {'sql%':>4} {'render%':>7} {'model%':>6}")
for name, rids in sorted(by_route.items()):
    d = sorted(ROUTE[r][1] / 1000 for r in rids)
    tot = sum(ROUTE[r][1] for r in rids) or 1
    pct = lambda cat: 100 * sum(SPANS[r][cat] for r in rids) / tot  # noqa: E731
    report.append(f"{name:42} {len(d):>5} {statistics.median(d):>7.1f} {d[int(0.95 * (len(d) - 1))]:>7.1f} "
                  f"{sum(COUNTS[r]['db.connect'] for r in rids) / len(rids):>8.1f} {sum(COUNTS[r]['db.query'] for r in rids) / len(rids):>7.1f} "
                  f"{pct('db.connect'):>5.0f} {pct('db.query'):>4.0f} {pct('render'):>7.0f} {pct('http.out'):>6.0f}")

report.append("\nheap (tracemalloc, after gc)")
for label, cur, state in phases:
    report.append(f"  {label:58} {cur / 1024:>9.0f} KiB   {state}")


def growth(a, b, title):
    report.append(f"\n{title}: top growth by source line")
    for stat in b.compare_to(a, "lineno")[:12]:
        fr = stat.traceback[0]
        report.append(f"  {stat.size_diff / 1024:>+9.1f} KiB {stat.count_diff:>+8} blocks  {fr.filename.replace(str(REPO), '.')}:{fr.lineno}")


growth(sA[0], sB[0], "A -> B (normal use)")
growth(sC[0], sD[0], f"C -> D ({N} more wrong passwords from new IPs)")
(OUT / "report.txt").write_text("\n".join(report), encoding="utf-8")
print("\n".join(report))
print(f"\nwrote {OUT}")
