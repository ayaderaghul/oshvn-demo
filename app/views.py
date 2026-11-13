import difflib, html, json, re
from pathlib import Path

from fastapi.responses import HTMLResponse
from markupsafe import Markup

E = html.escape


CSS = (Path(__file__).parent / "static" / "style.css").read_text(encoding="utf-8")


NAV = [("/", "Văn bản"), ("/ask", "Hỏi đáp"), ("/search", "Tìm kiếm"), ("/obligations", "Nghĩa vụ & rule engine"), ("/proposals", "Chờ duyệt"), ("/runs", "Nhật ký nạp")]


def page(title, body, active="/"):
    nav = "".join(f'<a href="{h}" class="{"on" if h == active else ""}">{t}</a>' for h, t in NAV)
    return HTMLResponse(f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)} · OSHVN demo</title><style>{CSS}</style></head><body><div class="wrap">
<div class="eyebrow">OSHVN · bản demo dữ liệu từ Neon</div><nav>{nav}</nav>{body}
<p class="muted" style="font-size:.8rem;margin-top:24px">Dữ liệu luật do bộ tách tự động; nghĩa vụ là bản nháp chưa được chuyên gia OSHVN duyệt.</p>
</div></body></html>""")


# ---------------------------------------------------------------- review of load proposals
STATUS_VI = {"pending": ("Chờ duyệt", "no"), "approved": ("Đã duyệt — chờ nạp", "ok"), "rejected": ("Từ chối", ""),
             "applied": ("Đã nạp", "ok"), "superseded": ("Bị thay thế", ""), "failed": ("Lỗi khi nạp", "no")}


def status_pill(status):
    lab, cls = STATUS_VI.get(status, (str(status), ""))
    return f"<span class='pill {cls}'>{E(lab)}</span>"


def counts(c):
    c = c if isinstance(c, dict) else {}
    return E(f"{c.get('new', 0)} mới / {c.get('changed', 0)} đổi / {c.get('retired', 0)} ngừng")


def mark(snip):
    return Markup(E(snip).replace("&lt;mark&gt;", "<mark>").replace("&lt;/mark&gt;", "</mark>"))


def cite(text):
    return Markup(re.sub(r"\[([0-9]{1,6})\]", lambda m: f"<a href='#s{m.group(1)}'>[{m.group(1)}]</a>", E(text)))


def dumps(x):
    return json.dumps(x, ensure_ascii=False)


def word_diff(old, new):
    a, b = re.findall(r"\S+|\s+", old or ""), re.findall(r"\S+|\s+", new or "")
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal": out.append(E("".join(a[i1:i2])))
        if tag in ("delete", "replace"): out.append(f"<del>{E(''.join(a[i1:i2]))}</del>")
        if tag in ("insert", "replace"): out.append(f"<ins>{E(''.join(b[j1:j2]))}</ins>")
    return Markup("".join(out))


VERDICT_VI = {"ok": ("có thể duyệt", "ok"), "check": ("cần xem kỹ", "no"), "reject": ("không nên nạp", "no")}


def agent_cell(verdict, comment, route, full=False):
    if not verdict:
        return "<td class='muted' style='font-size:.82rem'>— (tạo bằng loader.py propose)</td>"
    lab, cls = VERDICT_VI.get(verdict, ("?", ""))
    how = {"ocr": "bản scan · OCR + Claude đọc ảnh", "parse": "file có chữ"}.get(route or "", route or "")
    text = comment or ""
    short = E(text) if full else E(text[:260]) + ("…" if len(text) > 260 else "")
    return (f"<td style='font-size:.85rem'><span class='pill {cls}'>{lab}</span> <span class='muted'>{E(how)}</span><br>{short}</td>")
