"""
Tarang Clinical — Database Connection & Session Factory
========================================================
Uses SQLite by default (zero-config, single-file).
Change DATABASE_URL to postgresql://... for production.
"""

import os
from sqlalchemy import create_engine
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
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yield a database session, auto-close on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
