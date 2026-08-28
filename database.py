"""SQLAlchemy engine + session factory.

Works against Supabase Postgres (production) or local SQLite (offline demo)
transparently, based on DATABASE_URL.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    # Needed so the same SQLite connection can be used across Streamlit threads.
    connect_args = {"check_same_thread": False}
else:
    # Postgres: return uuid columns as plain strings (parity with SQLite, and
    # our models declare String ids). Avoids "UUID is not JSON serializable".
    import psycopg2.extensions as _ext
    _UUID_STR = _ext.new_type((2950,), "UUID_STR", lambda v, c: v)
    _ext.register_type(_UUID_STR)
    _UUID_ARR = _ext.new_array_type((2951,), "UUID_STR_ARRAY", _UUID_STR)
    _ext.register_type(_UUID_ARR)

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)

if not settings.database_url.startswith("sqlite"):
    # Our models declare String ids; make psycopg2 return uuid columns as str.
    # Registered per-connection AFTER the dialect's native-uuid registration.
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _uuid_as_str(dbapi_conn, _rec):
        import psycopg2.extensions as _ext
        t = _ext.new_type((2950,), "UUID_STR", lambda v, c: v)
        _ext.register_type(t, dbapi_conn)
        _ext.register_type(_ext.new_array_type((2951,), "UUID_STR_ARR", t), dbapi_conn)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables from the ORM metadata (idempotent).

    The canonical schema (with RLS) lives in schema.sql for Postgres/Supabase;
    this is the convenience path for local SQLite demos.
    """
    import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
