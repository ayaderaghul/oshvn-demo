import os
from contextlib import contextmanager

import psycopg
from fastapi import HTTPException
from psycopg.rows import namedtuple_row


def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(500, "Chưa đặt DATABASE_URL trên Render")
    return url


@contextmanager
def db():
    """Read-only: every transaction starts with BEGIN READ ONLY, which also holds through Neon's connection pooler."""
    with psycopg.connect(database_url(), connect_timeout=15, row_factory=namedtuple_row) as conn:
        conn.read_only = True
        yield conn


@contextmanager
def writer():
    """The only writes this app makes: review_proposal() and review_proposal_items()."""
    with psycopg.connect(database_url(), autocommit=True, connect_timeout=15) as conn:
        yield conn
