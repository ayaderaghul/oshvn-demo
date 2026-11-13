"""OSHVN demo web — view of what is in the Neon database, plus review of load proposals.

Pages: documents · one document (Điều › Khoản) · keyword search · obligations + rule engine · load log · proposals.
Environment: DATABASE_URL (role oshvn_web: reads tables; its only write is the review_proposal() function),
APP_PASSWORD (HTTP Basic; the user name is recorded as the reviewer).
"""
from fastapi import Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse

from app.routers import ask, documents, obligations, proposals, runs
from app.security import auth


# every route needs the password (except PUBLIC_PATHS): a new route cannot be public by forgetting a dependency
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, dependencies=[Depends(auth)])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


app.include_router(documents.router)
app.include_router(obligations.router)
app.include_router(runs.router)
app.include_router(proposals.router)
app.include_router(ask.router)
