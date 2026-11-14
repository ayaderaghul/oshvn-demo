"""Error reports to Sentry: on only when SENTRY_DSN is set, errors only, and scrubbed before they leave the process."""
import os
import re

import sentry_sdk

SECRET_ENV = ("APP_PASSWORD", "ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "DATABASE_URL")
URL_PASSWORD = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")
KEPT_HEADERS = {"host", "user-agent", "content-type", "content-length", "accept"}
MAX_TEXT = 600


def _secrets():
    found = set()
    for name in SECRET_ENV:
        value = os.environ.get(name) or ""
        m = URL_PASSWORD.search(value)
        found.add(m.group(0)[len(m.group(1)):-1] if m else value)
    return sorted((s for s in found if len(s) >= 6), key=len, reverse=True)


def _clean(value, secrets):
    if isinstance(value, str):
        for s in secrets:
            value = value.replace(s, "[secret]")
        return URL_PASSWORD.sub(r"\1[secret]@", value)
    if isinstance(value, dict):
        return {k: _clean(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v, secrets) for v in value]
    return value


def scrub(event, hint=None):
    """What a report may carry: the stack, the route, and the error text with secrets masked. Not the login, the
    client address, the query string (a question on /ask), form data, or anything a reviewer typed."""
    req = event.get("request")
    if req:
        headers = {k: v for k, v in (req.get("headers") or {}).items() if k.lower() in KEPT_HEADERS}
        event["request"] = {"method": req.get("method"), "url": (req.get("url") or "").split("?")[0], "headers": headers}
    for key in ("user", "breadcrumbs", "extra", "_meta"):   # _meta names the fields the SDK itself removed
        event.pop(key, None)
    for exc in (event.get("exception") or {}).get("values") or []:
        if isinstance(exc.get("value"), str) and len(exc["value"]) > MAX_TEXT:
            exc["value"] = exc["value"][:MAX_TEXT] + "…"
    return _clean(event, _secrets())


def options(dsn):
    return {"dsn": dsn, "before_send": scrub, "include_local_variables": False,
            "max_breadcrumbs": 0, "max_request_body_size": "never", "traces_sample_rate": None,
            "release": os.environ.get("RENDER_GIT_COMMIT"), "environment": os.environ.get("SENTRY_ENVIRONMENT", "production")}


def init():
    dsn = os.environ.get("SENTRY_DSN")
    if dsn:
        sentry_sdk.init(**options(dsn))
