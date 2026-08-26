"""
Tarang Clinical — FastAPI Main Application
==========================================
Run with:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Or from the backend directory:
    python -m uvicorn main:app --host 0.0.0.0 --port 8000
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from scalar_fastapi import get_scalar_api_reference
from contextlib import asynccontextmanager
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.connection import get_db, init_db, SessionLocal
from database.models import DeviceDiagnostics, SystemSetting, Patient, Device, MonitoringSession

from routers import (
    telemetry,
    patients,
    diagnostics,
    devices,
    sessions,
    integrations,
    settings as settings_router,
    health as health_router,
    mode_a_events,
    clinical_actions,
)


# ── Seed default data on first run ───────────────────────────────────────────

def seed_defaults():
    """Populate neutral diagnostics, settings, and a default active demo session."""
    default_device_mac = os.getenv("TARANG_BLE_ADDRESS", "00:00:00:00:00:00")
    db = SessionLocal()
    try:
        # Neutral diagnostics keep the bootstrap response schema stable.
        if not db.query(DeviceDiagnostics).first():
            db.add(DeviceDiagnostics(
                ble_connected=False,
                device_name="EFR32MG26 (Tarang SoC)",
                device_mac=default_device_mac,
                firmware_version="v1.0.0-EFR32MG26",
                rssi_dbm=-100,
                packets_received=0,
                packets_dropped=0,
                latency_ms=0.0,
                battery_pct=0,
            ))

        # Non-clinical workstation defaults are safe to seed.
        if not db.query(SystemSetting).first():
            db.add(SystemSetting())

        # Ensure default demo patient exists and is named Himanshu Patel
        demo_patient = db.query(Patient).first()
        if not demo_patient:
            demo_patient = Patient(
                name="Himanshu Patel",
                age=45,
                gender="Male",
                mrn="TRG-84920",
                bed="ICU-04",
                admit_date=datetime.now().strftime("%Y-%m-%d"),
                attending_physician="Dr. Maya Lin, MD",
                blood_type="B+",
                allergies=["None known"],
                medical_history=["Post-CABG telemetry", "Hypertension"],
            )
            db.add(demo_patient)
            db.flush()
        else:
            demo_patient.name = "Himanshu Patel"
            demo_patient.gender = "Male"
            demo_patient.blood_type = "B+"
            demo_patient.medical_history = ["Post-CABG telemetry", "Hypertension"]
            db.flush()

        # Ensure default device exists
        demo_device = db.query(Device).filter(Device.device_id == "tarang-efr32-demo").first()
        if not demo_device:
            demo_device = Device(
                device_id="tarang-efr32-demo",
                name="EFR32MG26 Tarang Pod #1",
                mac_address=default_device_mac,
                firmware_version="v1.0.0-EFR32MG26",
                status="in_use",
                assigned_patient_id=demo_patient.id,
            )
            db.add(demo_device)
            db.flush()

        # ALWAYS archive previous active sessions and create a brand new active session on startup
        for old_session in db.query(MonitoringSession).filter(MonitoringSession.status == "active").all():
            old_session.status = "stopped"
            old_session.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)

        new_session_id = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        db.add(MonitoringSession(
            session_id=new_session_id,
            patient_id=demo_patient.id,
            device_id="tarang-efr32-demo",
            status="active",
            bed=demo_patient.bed or "ICU-04",
            notes="Live demonstration session - EFR32MG26 real-time ECG/PPG/IMU telemetry stream",
        ))

        db.commit()
    finally:
        db.close()


# ── App Lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB tables and seed defaults on startup."""
    init_db()
    seed_defaults()
    print("[TARANG] Backend started. Database initialized.")
    yield
    print("[TARANG] Backend shutting down.")


# ── OpenAPI Metadata & Tags ──────────────────────────────────────────────────

TAGS_METADATA = [
    {
        "name": "mode_a",
        "description": "Ingestion endpoints for real-time Mode A telemetry including ECG waveforms, rhythm classification, and beat annotations.",
    },
    {
        "name": "clinical_actions",
        "description": "Emergency alerting and physician dispatch logging for acute clinical events.",
    },
    {
        "name": "telemetry",
        "description": "Continuous vital signs polling and WebSocket telemetry stream broadcast.",
    },
    {
        "name": "integrations-v1",
        "description": "EHR and hospital CRM integration interfaces for patient admission and observation exports.",
    },
    {
        "name": "diagnostics",
        "description": "Hardware link metrics, BLE signal strength, packet delivery rates, and device battery telemetry.",
    },
    {
        "name": "patients",
        "description": "Patient directory management, ward assignments, and admission profiles.",
    },
    {
        "name": "health",
        "description": "Service health probes and database connectivity verification.",
    },
]


# ── FastAPI Application ───────────────────────────────────────────────────────

app = FastAPI(
    title="Tarang Clinical Workstation API",
    description="REST and WebSocket API specification for the Tarang clinical telemetry hub, handling sensor stream ingestion, real-time arrhythmia detection, and workstation synchronization.",
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=TAGS_METADATA,
    docs_url=None,  # Handled by Scalar at /docs
    redoc_url=None,
)

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("TARANG_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials="*" not in CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(mode_a_events.router)
app.include_router(clinical_actions.router)
app.include_router(telemetry.router)
app.include_router(patients.router)
app.include_router(diagnostics.router)
app.include_router(settings_router.router)
app.include_router(health_router.router)
app.include_router(devices.router)
app.include_router(sessions.router)
app.include_router(integrations.router)

# Mount WebSocket endpoint at /ws/telemetry (separate from REST prefix)
app.add_api_websocket_route("/ws/telemetry", telemetry.websocket_telemetry)


# ── Scalar API Reference (/docs) ─────────────────────────────────────────────

@app.get("/docs", include_in_schema=False)
async def scalar_html():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Reference",
    )


# ── Health Check ─────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
def health():
    return {
        "status": "ok",
        "service": "Tarang Clinical API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
    }


@app.get("/api/health", tags=["health"])
def api_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "service": "Tarang Clinical API"}
