import os

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row


def connect():
    """Use read committed statements; the service opens explicit write transactions."""
    options = dict(autocommit=True, row_factory=dict_row, connect_timeout=5)
    url = os.environ.get("DATABASE_URL")
    if url:
        conn = psycopg.connect(url, **options)
    else:
        conn = psycopg.connect(
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ.get("DB_NAME", "minithsr"),
            user=os.environ.get("DB_USER", "minithsr"),
            password=os.environ.get("DB_PASSWORD", "minithsr-local"),
            **options,
        )
    conn.isolation_level = IsolationLevel.READ_COMMITTED
    return conn
