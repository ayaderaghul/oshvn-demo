---
name: verify
description: Drive the oshvn-demo review web app (FastAPI, server-rendered HTML, no JavaScript) the way a reviewer does — log in, open pages, approve or reject proposals, ask questions — against a throwaway Postgres with seeded data and local stand-ins for Claude and Voyage, and capture the pages and database state as proof. Use to prove a change to the app package (`app/`) works in the running app, not just in unit tests.
---

# Verify oshvn-demo

The app is the FastAPI package `app/` (entry point `app/main.py`), which renders HTML pages with forms and no JavaScript. A browser only follows links and submits forms with Basic auth, so the helper drives it the same way over HTTP: the `Authorization` header, the form token read from the page, and an `Origin` header naming the app. Every run gets its own database container, app process, and ports, so two runs can go side by side.

All commands run from the repository root. In Git Bash, set `MSYS_NO_PATHCONV=1` first, or Git Bash rewrites `/doc/1` into a Windows path. `V` below is shorthand for:

```bash
export MSYS_NO_PATHCONV=1
V="py -3.13 .claude/skills/verify/scripts/verify.py"     # any Python 3.12 or later
```

`--run ID` goes before the subcommand (`$V --run 20261111-172700 doctor`). Without it, the latest live run is used.

## Launch

1. Docker must be running (`docker info` succeeds).
2. `$V up` does all of this, in order:
	- creates `.venv` and installs `requirements.txt` on first use;
	- starts `pgvector/pgvector:pg17` labelled `oshvn.demo.verify=1` on a free port and waits until a query from outside the container succeeds twice;
	- loads `tests/fixtures/schema.sql` (the Neon schema with the loader's migrations), then `fixtures/seed.sql`;
	- starts the fake model server (`verify.py fake`) and `uvicorn app.main:app` on free ports, with `APP_PASSWORD` set to a random value and `ASK_API_BASE` and `VOYAGE_API_BASE` pointing at the fake server.
3. Ready means usable: `up` waits until the logged-in home page lists `1/2026/NĐ-CP`, then prints `ready: run <ID> · app http://127.0.0.1:<port> …`.

The seed gives predictable ids in every run: document 1 (`1/2026/NĐ-CP`, five clauses with vectors), obligations `VERIFY-ND1-01` (reviewed by `chi` and flagged) and `VERIFY-ND1-02`, proposal 1 (pending document proposal from agent00, one changed clause), proposal 2 (pending obligation proposal with `ND1-26-A01` and `ND1-26-A02`, A02 flagged by the verifier), and proposal 3 (applied).

## Doctor

`$V doctor` is read-only. It checks that the app and fake-server processes are alive, the container runs and carries the label, the app URL is local, `/healthz` answers `ok`, and the logged-in home page shows the seeded document. It ends with `doctor: OK` or lists each `PROBLEM:` and exits 1. Run it first, and again when anything looks wrong.

## Drive

- `$V get PATH [--slug NAME]` — logged-in GET.
- `$V review PID approved|rejected [--exclude ID ...] [--note TEXT]` — reads the token from `/proposals/PID` and submits the decision form, as the **Duyệt** and **Từ chối** buttons do.
- `$V ask "QUESTION" [--doc NUMBER]` — reads the token from `/ask` and submits the question form.
- `$V raw METHOD PATH [--password P] [--header K:V] [--form K=V] [--no-origin]` — any request, for the negative cases: a wrong password, a forged header, a POST without `Origin`.
- `$V sql "SELECT …"` — read-only query against the run's database.
- `$V calls` — the requests the app sent to the fake Claude and Voyage.

The fake Claude answers "Theo [1]: …" with the first line of clause 1. When the prompt contains `SAI SỐ`, it adds a number that no clause has, so the answer check warns. The fake Voyage returns the same 1024-dimension vector the seed stores, so `/ask` takes the fused keyword-and-vector path.

The feature map in `features/` has one recipe per feature. Read `features/README.md` first.

## Observe (traces and heap)

`.venv/Scripts/python .claude/skills/verify/scripts/observe.py` starts its own run, serves the app inside the script so its Python heap is visible, drives a fixed load, and stops the run. The load is two rounds of every page, 100 questions, and two phases of wrong passwords from distinct addresses (`--bad-logins N`, default 11000). Allow about five minutes. It writes `verify_out/<run>/observe/`:

- `trace.json`: one span per request, with its database connects, queries, template renders, and model calls nested under it. Open it at https://ui.perfetto.dev. The file stays in the browser.
- `heap-A…D.snapshot`: `tracemalloc` snapshots after warm-up, after normal use, and after each wrong-password phase. Compare two with `tracemalloc.Snapshot.load(...).compare_to(other, "lineno")`.
- `report.txt`: latency, connections, and queries per route; the share spent connecting, querying, rendering, and calling models; heap totals; and growth by source line.

Read it this way. Heap from A to B must stay flat, because normal use keeps no state per request. From C to D it must stay flat as well, because `FAILED_LOGINS` is capped at `LOGIN_TRACKED_MAX`. Times come from a local database, so connection cost on Neon is higher.

## Evidence

Each command saves to `verify_out/<run>/` (gitignored): `NNN-<slug>.html` (the page as served), `NNN-<slug>.txt` (status line, redirect target, and the page text), and `model-calls.jsonl`, `app.log`, `fake.log`. Proof standards:

- Use the user path: the page, then its form. Do not call functions from `app/` or the SQL review functions directly.
- Prove a change by its effect: after a review, query `load_proposals` with `$V sql` and open the page again.
- A model call is proven by `$V calls`, not by the answer text alone.
- The fake model server stands in at the app's own `ASK_API_BASE` and `VOYAGE_API_BASE` boundary. It proves the app's handling of answers and errors, not the quality of real model answers.

## Cleanup

`$V down` stops only the two processes this run started (by the PIDs in its state file), removes only the container named there after checking its label, and renames `state.json` to `state.down.json`. Everything in `verify_out/<run>/` stays. Run it after every attempt, including failed ones. `.venv` stays for the next run.

## Not covered

- Real rendering. No browser runs, so CSS and layout are not checked. The pages use no JavaScript.
- Real Claude and Voyage answers, Render, Cloudflare, and Neon. On Render the client key is `CF-Connecting-IP`; locally it is `127.0.0.1` unless a request sends that header.
