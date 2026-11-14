"""Turn two tracemalloc snapshots into one HTML page: what grew between them, by source line, with the call paths.

usage: python heapview.py OLD.snapshot NEW.snapshot [-o OUT.html] [--top N]

Each row is a source line that allocated memory still alive in a snapshot. Click a column header to sort, type in
the box to filter by path, and open a row to see the call paths that reached the line. The source text shown is read
from the files as they are now, which can differ from the code that ran.
"""
import argparse, html, json, linecache, sys, sysconfig, tracemalloc
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STDLIB = sysconfig.get_paths()["stdlib"]


def short(path):
    p = str(path)
    if "site-packages" in p:
        return "site-packages" + p.split("site-packages", 1)[1]
    for base, label in ((str(ROOT), "."), (STDLIB, "stdlib")):
        if p.lower().startswith(base.lower()):
            return label + p[len(base):]
    if "\\Lib\\" in p and "Python" in p:
        return "stdlib\\" + p.split("\\Lib\\", 1)[1]
    return p


def kind(path):
    s = short(path)
    return "app" if s.startswith(".") and "site-packages" not in s and ".venv" not in s else "lib"


def collect(old, new, top):
    lines = defaultdict(lambda: {"size": 0, "dsize": 0, "count": 0, "dcount": 0, "paths": []})
    for st in new.compare_to(old, "traceback"):
        fr = st.traceback[-1]
        row = lines[(fr.filename, fr.lineno)]
        row["size"] += st.size; row["dsize"] += st.size_diff
        row["count"] += st.count; row["dcount"] += st.count_diff
        row["paths"].append((st.size_diff, st.count_diff, st.traceback))
    rows = sorted(lines.items(), key=lambda kv: -abs(kv[1]["dsize"]))[:top]
    out = []
    for (fn, ln), r in rows:
        paths = []
        for dsize, dcount, tb in sorted(r["paths"], key=lambda p: -abs(p[0]))[:3]:
            frames = [{"at": f"{short(f.filename)}:{f.lineno}", "src": linecache.getline(f.filename, f.lineno).strip(),
                       "kind": kind(f.filename)} for f in reversed(tb)]
            paths.append({"dsize": dsize, "dcount": dcount, "frames": frames})
        out.append({"at": f"{short(fn)}:{ln}", "kind": kind(fn), "src": linecache.getline(fn, ln).strip(),
                    "size": r["size"], "dsize": r["dsize"], "count": r["count"], "dcount": r["dcount"],
                    "npaths": len(r["paths"]), "paths": paths})
    return out


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Heap growth</title><style>
:root{--bg:#fafaf7;--fg:#1c1c1a;--mut:#6b6b66;--line:#e2e1da;--up:#b3261e;--down:#1a7f37;--app:#fff4d6;--code:#f0efe8}
@media(prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--mut:#9c9b94;--line:#33322e;--up:#ff8a80;--down:#7bd88f;--app:#3a3216;--code:#22211e}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:20px 16px 60px;max-width:1200px;margin-inline:auto}
h1{font-size:20px;margin:0 0 4px}.mut{color:var(--mut)}code,.mono{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0}.card{border:1px solid var(--line);border-radius:8px;padding:8px 14px}
.card b{display:block;font-size:18px}.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:10px 0}
input[type=search]{flex:1;min-width:200px;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{padding:5px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{cursor:pointer;user-select:none;position:sticky;top:0;background:var(--bg)}th.sorted::after{content:" ▾"}th.sorted.asc::after{content:" ▴"}
td.at,th.at{text-align:left;white-space:normal;word-break:break-all}tr.row{cursor:pointer}tr.row:hover{background:var(--code)}
tr.app td.at{background:var(--app)}.up{color:var(--up)}.down{color:var(--down)}.src{color:var(--mut);display:block}
tr.detail td{text-align:left;white-space:normal;background:var(--code);padding:10px 14px}
.path{margin:0 0 12px}.frame{padding:1px 0 1px 12px;border-left:2px solid var(--line)}.frame.app{border-left-color:#d49a00}
.frame:first-child{font-weight:600}
</style></head><body>
<h1>Heap growth</h1><div class="mut mono">__OLD__ → __NEW__</div>
<div class="cards" id="cards"></div>
<div class="bar"><input type="search" id="q" placeholder="Filter by path or source text">
<label><input type="checkbox" id="apponly"> app code only</label><span class="mut" id="n"></span></div>
<div class="wrap"><table><thead><tr><th class="at" data-k="at">Allocated at</th><th data-k="dsize">Growth</th><th data-k="dcount">Blocks added</th>
<th data-k="size">Alive now</th><th data-k="count">Blocks now</th><th data-k="avg">Avg block</th></tr></thead><tbody id="tb"></tbody></table></div>
<p class="mut">A row is a source line whose allocations were still alive when the snapshot was taken. Highlighted rows are this
repository's code. Open a row for the call paths, innermost frame first. Source text is read from the files as they are now.</p>
<script>
const D=__DATA__,T=__TOTALS__;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const sz=b=>{const a=Math.abs(b);return a>=1048576?(b/1048576).toFixed(2)+" MiB":a>=1024?(b/1024).toFixed(1)+" KiB":b+" B"};
const sg=(b,f)=>`<span class="${b>0?"up":b<0?"down":"mut"}">${b>0?"+":""}${f(b)}</span>`;
const num=n=>n.toLocaleString("en-US");
D.forEach((r,i)=>{r.avg=r.count?Math.round(r.size/r.count):0;r.i=i});
document.getElementById("cards").innerHTML=[["Before",sz(T.old)],["After",sz(T.new)],["Change",sg(T.new-T.old,sz)],
 ["Lines that grew",num(T.grew)],["Lines that shrank",num(T.shrank)]].map(([k,v])=>`<div class="card"><span class="mut">${k}</span><b>${v}</b></div>`).join("");
let key="dsize",asc=false,open=new Set();
function detail(r){
 const frame=f=>`<div class="frame mono ${f.kind}">${esc(f.at)} <span class="mut">${esc(f.src)}</span></div>`;
 const path=p=>`<div class="path"><div>${sg(p.dsize,sz)} in ${sg(p.dcount,num)} blocks through this path</div>${p.frames.map(frame).join("")}</div>`;
 const more=r.npaths>r.paths.length?`<div class="mut">${r.npaths-r.paths.length} more call paths not shown</div>`:"";
 return `<tr class="detail"><td colspan="6">${r.paths.map(path).join("")}${more}</td></tr>`;
}
function draw(){
 const q=document.getElementById("q").value.toLowerCase(),app=document.getElementById("apponly").checked;
 const rows=D.filter(r=>(!app||r.kind==="app")&&(!q||(r.at+" "+r.src).toLowerCase().includes(q)));
 rows.sort((a,b)=>{const x=a[key],y=b[key];const c=typeof x==="string"?x.localeCompare(y):(key==="dsize"||key==="dcount"?Math.abs(x)-Math.abs(y):x-y);return asc?c:-c});
 document.getElementById("n").textContent=rows.length+" of "+D.length+" lines";
 document.getElementById("tb").innerHTML=rows.map(r=>`<tr class="row ${r.kind}" data-i="${r.i}"><td class="at mono">${esc(r.at)}<span class="src">${esc(r.src)}</span></td>
 <td>${sg(r.dsize,sz)}</td><td>${sg(r.dcount,num)}</td><td>${sz(r.size)}</td><td>${num(r.count)}</td><td>${sz(r.avg)}</td></tr>`+
 (open.has(r.i)?detail(r):"")).join("");
 document.querySelectorAll("th").forEach(th=>{th.classList.toggle("sorted",th.dataset.k===key);th.classList.toggle("asc",th.dataset.k===key&&asc)});
}
document.querySelector("thead").onclick=e=>{const k=e.target.dataset.k;if(!k)return;asc=k===key?!asc:k==="at";key=k;draw()};
document.getElementById("tb").onclick=e=>{const tr=e.target.closest("tr.row");if(!tr)return;const i=+tr.dataset.i;open.has(i)?open.delete(i):open.add(i);draw()};
document.getElementById("q").oninput=draw;document.getElementById("apponly").onchange=draw;draw();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old"); ap.add_argument("new"); ap.add_argument("-o", "--out"); ap.add_argument("--top", type=int, default=300)
    a = ap.parse_args()
    old_p, new_p = Path(a.old).resolve(), Path(a.new).resolve()
    old, new = tracemalloc.Snapshot.load(str(old_p)), tracemalloc.Snapshot.load(str(new_p))
    by_line = new.compare_to(old, "lineno")
    totals = {"old": sum(t.size for t in old.traces), "new": sum(t.size for t in new.traces),
              "grew": sum(1 for s in by_line if s.size_diff > 0), "shrank": sum(1 for s in by_line if s.size_diff < 0)}
    safe = lambda x: json.dumps(x, ensure_ascii=False).replace("</", "<\\/")  # noqa: E731
    page = (PAGE.replace("__OLD__", html.escape(old_p.name)).replace("__NEW__", html.escape(new_p.name))
            .replace("__TOTALS__", safe(totals)).replace("__DATA__", safe(collect(old, new, a.top))))
    out = Path(a.out) if a.out else new_p.with_name(f"heapview-{old_p.stem}-vs-{new_p.stem}.html")
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
