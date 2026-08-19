"""
Tarang Clinical — Device Health Router
======================================
REST endpoints for 1Hz hardware/sensor health telemetry snapshots.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import DeviceHealthEvent

router = APIRouter(prefix="/api/health", tags=["health"])


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class HealthIngest(BaseModel):
    session_id: Optional[str] = None
    uptime_s: int = Field(default=0, ge=0)
    ecg_lead_off: bool = Field(default=False)
    ecg_sqi: int = Field(default=255, ge=0, le=255)
    ppg_finger_present: bool = Field(default=False)
    imu_ok: bool = Field(default=False)
    i2c_failure_count: int = Field(default=0, ge=0, le=255)
    dsp_overflow_count: int = Field(default=0, ge=0, le=255)
    ecg_overrun_count: int = Field(default=0, ge=0, le=255)
    ble_rssi: Optional[int] = Field(default=-60, ge=-128, le=127)
    battery_pct: Optional[int] = Field(default=None, ge=0, le=255)
    fw_version: Optional[str] = Field(default="1.0.0")


# ── REST Endpoints ────────────────────────────────────────────────────────────

@router.get("/device")
def get_latest_device_health(db: Session = Depends(get_db)):
    """Return the latest single health telemetry snapshot."""
    event = db.query(DeviceHealthEvent).order_by(desc(DeviceHealthEvent.id)).first()
    if not event:
        return {
            "uptimeS": 0,
            "ecgLeadOff": False,
            "ecgSqi": 0,
            "ppgFingerPresent": False,
            "imuOk": False,
            "i2cFailureCount": 0,
            "dspOverflowCount": 0,
            "ecgOverrunCount": 0,
            "bleRssi": None,
            "batteryPct": None,
            "fwVersion": None,
        }
    return event.to_dict()


@router.get("/history")
def get_health_history(
    minutes: int = Query(default=10, ge=1, le=120),
    session_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return device health snapshots over the specified time window."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    query = db.query(DeviceHealthEvent).filter(DeviceHealthEvent.received_at >= cutoff)
    if session_id:
        query = query.filter(DeviceHealthEvent.session_id == session_id)
    events = query.order_by(desc(DeviceHealthEvent.id)).limit(500).all()
    return [e.to_dict() for e in events]


@router.post("/ingest")
async def ingest_health(packet: HealthIngest, db: Session = Depends(get_db)):
    """
    BLE Gateway posts decoded 16-byte health packets here at 1Hz.
    Stores to DB and broadcasts to WebSocket clients.
    """
    event = DeviceHealthEvent(
        session_id=packet.session_id,
        uptime_s=packet.uptime_s,
        ecg_lead_off=packet.ecg_lead_off,
        ecg_sqi=packet.ecg_sqi,
        ppg_finger_present=packet.ppg_finger_present,
        imu_ok=packet.imu_ok,
        i2c_failure_count=packet.i2c_failure_count,
        dsp_overflow_count=packet.dsp_overflow_count,
        ecg_overrun_count=packet.ecg_overrun_count,
        ble_rssi=packet.ble_rssi if packet.ble_rssi != 127 else None,
        battery_pct=packet.battery_pct if packet.battery_pct != 255 else None,
        fw_version=packet.fw_version,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    dict_data = event.to_dict()
    # Broadcast to dashboard WebSocket clients
    from routers.telemetry import manager
    await manager.broadcast({"type": "device_health", "data": dict_data})

    return {"status": "ok", "id": event.id}
