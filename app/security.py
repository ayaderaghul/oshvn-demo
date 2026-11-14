import hashlib
import hmac
import os
import secrets
import threading
import time
import unicodedata
from collections import deque
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic(auto_error=False)
PUBLIC_PATHS = {"/healthz"}
LOGIN_FAILURES_ALLOWED = 10          # per client address, within LOGIN_WINDOW seconds
LOGIN_WINDOW = 900
LOGIN_TRACKED_MAX = 10_000           # about 9 MB of counters at most
FAILED_LOGINS, _login_lock = {}, threading.Lock()
_last_sweep = [0.0]


def _remember_failure(key, now):
    """Under _login_lock. Counters are otherwise trimmed only when their own client returns, so without the sweep
    and the size limit, addresses that never come back would stay in memory until a restart."""
    if now - _last_sweep[0] > 60:
        _last_sweep[0] = now
        for k in [k for k, f in FAILED_LOGINS.items() if now - f[-1] > LOGIN_WINDOW]:
            del FAILED_LOGINS[k]
    if key not in FAILED_LOGINS:
        while len(FAILED_LOGINS) >= LOGIN_TRACKED_MAX:
            del FAILED_LOGINS[next(iter(FAILED_LOGINS))]
        FAILED_LOGINS[key] = deque()
    FAILED_LOGINS[key].append(now)


def reviewer_name(raw):
    """The Basic-auth user name, recorded as the reviewer. Invisible and blank-looking characters (U+200B, Hangul
    fillers, braille blank…) are dropped; a name with no letter or digit left is no name."""
    def visible(ch):
        name = unicodedata.name(ch, "")
        return (ch.isprintable() and unicodedata.category(ch) not in ("Cf", "Cc", "Zs")
                and "FILLER" not in name and name != "BRAILLE PATTERN BLANK")
    s = unicodedata.normalize("NFKC", raw or "")
    s = " ".join("".join(ch if ch == " " or visible(ch) else "" for ch in s).split())
    return s if any(ch.isalnum() for ch in s) else ""


def client_key(request):
    """Who is guessing passwords. Render serves the app behind Cloudflare, which sets CF-Connecting-IP to the real
    client address and overwrites any value a client sends. X-Forwarded-For is no use: its first entries are whatever
    the client sent, and its last entry is a proxy hop that changes between connections (seen on 2026-11-11)."""
    return (request.headers.get("cf-connecting-ip", "").strip()
            or (request.client.host if request.client else "?"))


def auth(request: Request, c: HTTPBasicCredentials | None = Depends(security)):
    if request.url.path in PUBLIC_PATHS:
        return ""
    key, now = client_key(request), time.time()
    with _login_lock:
        fails = FAILED_LOGINS.get(key)
        while fails and now - fails[0] > LOGIN_WINDOW: fails.popleft()
        if fails is not None and not fails: del FAILED_LOGINS[key]
        if fails and len(fails) >= LOGIN_FAILURES_ALLOWED:
            raise HTTPException(429, "Sai mật khẩu quá nhiều lần — thử lại sau 15 phút")
    pw = os.environ.get("APP_PASSWORD")
    if not pw or c is None or not secrets.compare_digest(c.password.encode(), pw.encode()):
        if c is not None:
            with _login_lock: _remember_failure(key, now)
        raise HTTPException(401, "Sai mật khẩu", headers={"WWW-Authenticate": "Basic"})
    with _login_lock: FAILED_LOGINS.pop(key, None)
    return reviewer_name(c.username)


def csrf_token(pid):
    key = (os.environ.get("APP_PASSWORD") or "").encode()
    return hmac.new(key, f"proposal:{pid}".encode(), hashlib.sha256).hexdigest()[:32]


def same_origin(request):
    """A form post from this site: browsers send Origin (or at least Referer) on POST, and it must name this host."""
    src = request.headers.get("origin") or request.headers.get("referer")
    return bool(src) and urlsplit(src).netloc == request.headers.get("host")
