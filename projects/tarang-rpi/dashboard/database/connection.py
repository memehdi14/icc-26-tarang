"""
Tarang Clinical — Database Connection & Session Factory
========================================================
Mode A (Event-Driven) + Legacy Compatibility
"""

import os
from sqlalchemy import create_engine, event, text
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

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _auto_migrate_columns(conn):
    """Detect and auto-add any missing columns for existing SQLite tables."""
    for table_name, table in Base.metadata.tables.items():
        try:
            res = conn.execute(text(f"PRAGMA table_info({table_name});"))
            existing_cols = {row[1] for row in res.fetchall()}
            if not existing_cols:
                continue
            for col in table.columns:
                if col.name not in existing_cols:
                    col_type = col.type.compile(engine.dialect)
                    default_clause = ""
                    if col.default is not None and hasattr(col.default, "arg") and col.default.arg is not None:
                        val = col.default.arg
                        if isinstance(val, (int, float)):
                            default_clause = f" DEFAULT {val}"
                        elif isinstance(val, str):
                            default_clause = f" DEFAULT '{val}'"
                    alter_query = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause};"
                    print(f"[DB Auto-Migrate] {table_name}: {alter_query}")
                    conn.execute(text(alter_query))
            conn.commit()
        except Exception as err:
            print(f"[DB Auto-Migrate Warning] {table_name}: {err}")


def init_db():
    """Create all tables if they don't exist and ensure schema migrations."""
    Base.metadata.create_all(bind=engine)
    try:
        with engine.connect() as conn:
            _auto_migrate_columns(conn)

            # Mode A Indexes
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_vitals_device_ts ON vitals_samples (device_id, ts);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analytics_device_ts ON analytics_5min (device_id, ts);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_events_device_ts ON clinical_events (device_id, ts);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_snippets_event_id ON ecg_snippets (event_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_annotations_snippet_id ON beat_annotations (snippet_id);"))

            # Legacy index compatibility
            try:
                conn.execute(text("ALTER TABLE telemetry_events ADD COLUMN session_id VARCHAR(64);"))
                conn.commit()
            except Exception:
                pass
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
