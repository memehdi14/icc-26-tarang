"""
Tarang Clinical — System Settings Router
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import SystemSetting

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    hrLowThreshold: Optional[int] = Field(default=None, ge=20, le=220)
    hrHighThreshold: Optional[int] = Field(default=None, ge=30, le=250)
    spo2LowThreshold: Optional[int] = Field(default=None, ge=50, le=100)
    rrLowThreshold: Optional[int] = Field(default=None, ge=4, le=40)
    rrHighThreshold: Optional[int] = Field(default=None, ge=5, le=60)
    bleSyncIntervalMs: Optional[int] = Field(default=None, ge=250, le=10000)
    gridDensity: Optional[str] = Field(default=None, pattern="^(dense|standard|relaxed)$")
    audioAlertsEnabled: Optional[bool] = None
    attendingDoctor: Optional[str] = Field(default=None, min_length=1, max_length=200)


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

    next_hr_low = data.hrLowThreshold if data.hrLowThreshold is not None else settings.hr_low_threshold
    next_hr_high = data.hrHighThreshold if data.hrHighThreshold is not None else settings.hr_high_threshold
    next_rr_low = data.rrLowThreshold if data.rrLowThreshold is not None else settings.rr_low_threshold
    next_rr_high = data.rrHighThreshold if data.rrHighThreshold is not None else settings.rr_high_threshold
    if next_hr_low >= next_hr_high:
        raise HTTPException(status_code=422, detail="Heart-rate low threshold must be below the high threshold")
    if next_rr_low >= next_rr_high:
        raise HTTPException(status_code=422, detail="Respiratory-rate low threshold must be below the high threshold")

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
