"""
Tarang Clinical — Database Connection & Session Factory
========================================================
Uses SQLite by default (zero-config, single-file).
Change DATABASE_URL to postgresql://... for production.
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .models import Base

_DB_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB_PATH = os.path.join(_DB_DIR, "tarang_clinical.db")

DATABASE_URL = os.getenv(
    "TARANG_DATABASE_URL",
    f"sqlite:///{_DEFAULT_DB_PATH}"
)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables if they don't exist and ensure schema migrations."""
    Base.metadata.create_all(bind=engine)
    try:
        with engine.connect() as conn:
            # Migration 1: Add session_id column if not present
            try:
                conn.execute(text("ALTER TABLE telemetry_events ADD COLUMN session_id VARCHAR(64);"))
                conn.commit()
            except Exception:
                pass # Column already exists
            # Migration 2: Ensure indexes
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telemetry_events_received_at ON telemetry_events (received_at);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telemetry_events_session_id ON telemetry_events (session_id);"))
            conn.commit()
    except Exception as e:
        print(f"[DB] Migration check: {e}")


def get_db():
    """FastAPI dependency: yield a database session, auto-close on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
