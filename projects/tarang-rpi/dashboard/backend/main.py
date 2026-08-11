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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from database.connection import init_db, SessionLocal
from database.models import Patient, DeviceDiagnostics, SystemSetting

from routers import telemetry, patients, diagnostics, settings as settings_router


# ── Seed default data on first run ───────────────────────────────────────────

def seed_defaults():
    """Populate default patient, device diagnostics, and settings if tables are empty."""
    db = SessionLocal()
    try:
        # Default patient (John Doe, ICU-04)
        if not db.query(Patient).first():
            db.add(Patient(
                name="John Doe",
                age=58,
                gender="Male",
                mrn="884219",
                bed="ICU-04",
                admit_date="2026-08-09",
                attending_physician="Dr. Aris",
                blood_type="O+",
                allergies=["Penicillin", "Latex Adhesives"],
                medical_history=[
                    "Hypertension (Diagnosed 2018)",
                    "Coronary Artery Stent - LAD (2021)",
                    "Type 2 Diabetes Mellitus",
                ],
            ))

        # Default device diagnostics snapshot
        if not db.query(DeviceDiagnostics).first():
            db.add(DeviceDiagnostics(
                ble_connected=False,
                device_name="EFR32MG26 (Tarang SoC)",
                device_mac="70:B3:D5:70:9A:C4",
                firmware_version="v1.0.0-EFR32MG26",
                rssi_dbm=-100,
                packets_received=0,
                packets_dropped=0,
                latency_ms=0.0,
                battery_pct=0,
            ))

        # Default system settings
        if not db.query(SystemSetting).first():
            db.add(SystemSetting())

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


# ── FastAPI Application ───────────────────────────────────────────────────────

app = FastAPI(
    title="Tarang Clinical API",
    description="Real-time cardiac telemetry API for the Tarang EFR32MG26 BLE wearable.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Next.js dev server and same-origin RPi access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # Next.js dev server
        "http://127.0.0.1:3000",
        "http://0.0.0.0:3000",
        "*",                       # Allow all during hackathon; restrict in production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(telemetry.router)
app.include_router(patients.router)
app.include_router(diagnostics.router)
app.include_router(settings_router.router)

# Mount WebSocket endpoint at /ws/telemetry (separate from REST prefix)
app.add_api_websocket_route("/ws/telemetry", telemetry.websocket_telemetry)


# ── Health Check ─────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
def health():
    return {
        "status": "ok",
        "service": "Tarang Clinical API",
        "version": "1.0.0",
    }


@app.get("/api/health", tags=["health"])
def api_health():
    return {"status": "ok"}
