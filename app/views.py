import difflib, html, json, re

from markupsafe import Markup

STATUS_VI = {"pending": ("Chờ duyệt", "no"), "approved": ("Đã duyệt — chờ nạp", "ok"), "rejected": ("Từ chối", ""),
             "applied": ("Đã nạp", "ok"), "superseded": ("Bị thay thế", ""), "failed": ("Lỗi khi nạp", "no")}
VERDICT_VI = {"ok": ("có thể duyệt", "ok"), "check": ("cần xem kỹ", "no"), "reject": ("không nên nạp", "no")}


def mark(snip):
    return Markup(html.escape(snip).replace("&lt;mark&gt;", "<mark>").replace("&lt;/mark&gt;", "</mark>"))


def cite(text):
    return Markup(re.sub(r"\[([0-9]{1,6})\]", lambda m: f"<a href='#s{m.group(1)}'>[{m.group(1)}]</a>", html.escape(text)))


def dumps(x):
    return json.dumps(x, ensure_ascii=False)


def word_diff(old, new):
    a, b = re.findall(r"\S+|\s+", old or ""), re.findall(r"\S+|\s+", new or "")
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal": out.append(html.escape("".join(a[i1:i2])))
        if tag in ("delete", "replace"): out.append(f"<del>{html.escape(''.join(a[i1:i2]))}</del>")
        if tag in ("insert", "replace"): out.append(f"<ins>{html.escape(''.join(b[j1:j2]))}</ins>")
    return Markup("".join(out))
