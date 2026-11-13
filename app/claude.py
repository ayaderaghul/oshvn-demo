import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque

ASK_LOG, ASK_LOCK = deque(), threading.Lock()   # times of model calls in this process, for the hourly limit


def ask_limit():
    try:
        return max(0, int(os.environ.get("ASK_LIMIT_PER_HOUR", "60")))
    except ValueError:
        return 60


def reserve_ask():
    """Take one slot of the hourly limit, atomically. Returns the slot, or None when the limit is reached."""
    now = time.time()
    with ASK_LOCK:
        while ASK_LOG and now - ASK_LOG[0] > 3600: ASK_LOG.popleft()
        if len(ASK_LOG) >= ask_limit(): return None
        ASK_LOG.append(now)
        return now


def release_ask(slot):
    """A call that failed does not count against the limit."""
    with ASK_LOCK:
        try: ASK_LOG.remove(slot)
        except ValueError: pass


def _ref(loc, num):
    return f"{num} " + (loc.get("ref") or (loc.get("label") or f"Điều {loc.get('dieu')}") + (f", khoản {loc['khoan']}" if loc.get("khoan") else ""))


def _numbers(t):
    return re.findall(r"\d+(?:[/.,]\d+)*", t)


def _same_number(n):
    """1.000.000, 1,000,000 and 1000000 are one number; 1,5 and 1.5 are one number."""
    if re.fullmatch(r"\d{1,3}(?:([.,])\d{3})(?:\1\d{3})*", n):
        return re.sub(r"[.,]", "", n)
    return n.replace(",", ".")


def _small_int(x):
    if isinstance(x, bool): return None
    if isinstance(x, int): return x if abs(x) < 10**6 else None
    if isinstance(x, str) and x.strip().isascii() and x.strip().isdigit() and len(x.strip()) <= 6: return int(x.strip())
    return None


def parse_answer(out):
    """The model's JSON, coerced to {answer: str, used: [int], not_found: str} whatever it returned."""
    out = out if isinstance(out, dict) else {}
    text = lambda x: "" if x is None else x if isinstance(x, str) else str(x)
    used = out.get("used") if isinstance(out.get("used"), list) else []
    return {"answer": text(out.get("answer")), "used": [n for n in map(_small_int, used) if n is not None],
            "not_found": text(out.get("not_found")), "_usage": out.get("_usage", ("", 0, 0))}


def check_answer(answer, used, hits):
    """Citations outside the hits, numbers not in a cited clause, and an answer that cites nothing at all."""
    cited = {int(x) for x in re.findall(r"\[([0-9]{1,6})\]", answer)} | set(used)
    bad_cite = sorted(c for c in cited if c < 1 or c > len(hits))
    src = {_same_number(n) for c in cited if 1 <= c <= len(hits)
           for n in _numbers(hits[c - 1][1][3] + " " + _ref(hits[c - 1][1][2], hits[c - 1][1][1]))}   # text + its own reference
    plain = re.sub(r"\[[0-9]+\]", " ", answer)          # citation marks are not numbers to check
    bad_num = sorted({n for n in _numbers(plain) if _same_number(n) not in src
                      and not all(_same_number(p) in src for p in re.split(r"[,;]", n))})   # "5,7" may be a list
    return {"bad_cite": bad_cite, "bad_num": bad_num, "no_cite": not cited}


def ask_claude(question, hits):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None, "Chưa đặt ANTHROPIC_API_KEY trên Render — chỉ hiện các khoản tìm được, chưa có câu trả lời."
    slot = reserve_ask()
    if slot is None:
        return None, f"Đã đủ {ask_limit()} câu hỏi trong một giờ (giới hạn ASK_LIMIT_PER_HOUR). Thử lại sau."
    sources = "\n\n".join(f"[{i + 1}] {_ref(h[1][2], h[1][1])}\n{h[1][3][:2500]}" for i, h in enumerate(hits))
    user = (f"Câu hỏi của chuyên gia an toàn, vệ sinh lao động:\n{question}\n\nCác khoản luật tìm được (đánh số):\n{sources}\n\n"
            "Trả lời bằng tiếng Việt, ngắn gọn, CHỈ dựa vào các khoản trên. Sau mỗi ý ghi số khoản làm căn cứ, ví dụ [2] hoặc [1][4]. "
            "Mọi con số (thời hạn, số người, mức phạt) phải chép đúng từ khoản được dẫn. Nếu các khoản trên không đủ để trả lời, nói rõ "
            "phần nào không tìm thấy căn cứ, không đoán. Lưu ý: mức phạt trong NĐ 283/2026 là mức cho cá nhân; tổ chức bị phạt gấp 2 lần, "
            "trừ khi điều đó ghi rõ là tổ chức.\n"
            'Trả JSON: {"answer": "...", "used": [số các khoản đã dẫn], "not_found": "phần không có căn cứ, hoặc rỗng"}')
    model = os.environ.get("ASK_MODEL", "claude-sonnet-5-5")
    body = {"model": model, "max_tokens": 2500, "system": "Bạn là trợ lý tra cứu pháp luật ATVSLĐ của OSHVN. Chỉ trả lời bằng một đối tượng JSON.",
            "messages": [{"role": "user", "content": user}]}
    base = os.environ.get("ASK_API_BASE", "https://api.anthropic.com")
    req = urllib.request.Request(base + "/v1/messages", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        release_ask(slot)
        return None, f"Claude API báo lỗi {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
    except Exception as e:
        release_ask(slot)
        return None, f"Không gọi được Claude API: {e}"
    text = "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict) and b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        out = json.loads(m.group(0) if m else text)
    except json.JSONDecodeError:
        return None, "Câu trả lời của model không đúng định dạng — thử lại."
    if not isinstance(out, dict):
        return None, "Câu trả lời của model không đúng định dạng — thử lại."
    u = data.get("usage", {}); out["_usage"] = (model, u.get("input_tokens", 0), u.get("output_tokens", 0))
    return out, None
