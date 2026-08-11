"""
Tarang Clinical — System Settings Router
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import SystemSetting

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    hrLowThreshold: Optional[int] = None
    hrHighThreshold: Optional[int] = None
    spo2LowThreshold: Optional[int] = None
    rrLowThreshold: Optional[int] = None
    rrHighThreshold: Optional[int] = None
    bleSyncIntervalMs: Optional[int] = None
    gridDensity: Optional[str] = None
    audioAlertsEnabled: Optional[bool] = None
    attendingDoctor: Optional[str] = None


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    """Fetch current system settings."""
    settings = db.query(SystemSetting).first()
    if not settings:
        return {"message": "No settings configured"}
    return settings.to_dict()


@router.put("")
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    """Update and persist alarm thresholds and preferences."""
    settings = db.query(SystemSetting).first()
    if not settings:
        settings = SystemSetting()
        db.add(settings)

    # Map camelCase fields to snake_case DB columns
    field_map = {
        "hrLowThreshold": "hr_low_threshold",
        "hrHighThreshold": "hr_high_threshold",
        "spo2LowThreshold": "spo2_low_threshold",
        "rrLowThreshold": "rr_low_threshold",
        "rrHighThreshold": "rr_high_threshold",
        "bleSyncIntervalMs": "ble_sync_interval_ms",
        "gridDensity": "grid_density",
        "audioAlertsEnabled": "audio_alerts_enabled",
        "attendingDoctor": "attending_doctor",
    }

    for camel, snake in field_map.items():
        value = getattr(data, camel, None)
        if value is not None:
            setattr(settings, snake, value)

    db.commit()
    db.refresh(settings)
    return settings.to_dict()
