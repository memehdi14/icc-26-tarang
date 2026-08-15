"""
Tarang Clinical — Device Diagnostics Router
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import DeviceDiagnostics

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


class DiagnosticsUpdate(BaseModel):
    ble_connected: Optional[bool] = None
    device_name: Optional[str] = None
    device_mac: Optional[str] = None
    firmware_version: Optional[str] = None
    rssi_dbm: Optional[int] = None
    packets_received: Optional[int] = None
    packets_dropped: Optional[int] = None
    latency_ms: Optional[float] = None
    battery_pct: Optional[int] = None
    ecg_health: Optional[bool] = None
    ppg_health: Optional[bool] = None
    imu_health: Optional[bool] = None


@router.get("/latest")
def get_latest_diagnostics(db: Session = Depends(get_db)):
    """Return the latest device diagnostics snapshot."""
    diag = db.query(DeviceDiagnostics).order_by(DeviceDiagnostics.id.desc()).first()
    if not diag:
        return {"message": "No diagnostics yet"}
    return diag.to_dict()


@router.post("/update")
async def update_diagnostics(data: DiagnosticsUpdate, db: Session = Depends(get_db)):
    """
    BLE Gateway posts device state here after each connection or packet burst.
    Upserts a single running diagnostics row and broadcasts to dashboard WS clients.
    """
    diag = db.query(DeviceDiagnostics).first()
    if not diag:
        diag = DeviceDiagnostics()
        db.add(diag)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(diag, field, value)

    db.commit()
    db.refresh(diag)

    dict_data = diag.to_dict()
    # Import WebSocket manager lazily to avoid circular imports
    from routers.telemetry import manager
    await manager.broadcast({"type": "diagnostics", "data": dict_data})

    return dict_data
