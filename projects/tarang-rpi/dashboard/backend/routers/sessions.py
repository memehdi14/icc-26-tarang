"""Monitoring session lifecycle and session-scoped clinical data."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import desc
from sqlalchemy.orm import Session

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import Device, DeviceHealthEvent, MonitoringSession, Patient, TelemetryEvent

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=64)
    patient_id: Optional[int] = None
    mrn: Optional[str] = Field(default=None, max_length=50)
    device_id: Optional[str] = Field(default=None, max_length=64)
    bed: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_patient(self):
        if self.patient_id is None and not self.mrn:
            raise ValueError("patient_id or mrn is required")
        return self


def _get_session(session_id: str, db: Session) -> MonitoringSession:
    session = db.query(MonitoringSession).filter(MonitoringSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session


@router.get("")
def list_sessions(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(MonitoringSession)
    if status:
        query = query.filter(MonitoringSession.status == status)
    sessions = query.order_by(desc(MonitoringSession.started_at)).all()
    return [session.to_dict() for session in sessions]


@router.post("", status_code=201)
def create_session(data: SessionCreate, db: Session = Depends(get_db)):
    patient_query = db.query(Patient)
    patient = (
        patient_query.filter(Patient.id == data.patient_id).first()
        if data.patient_id is not None
        else patient_query.filter(Patient.mrn == data.mrn).first()
    )
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    device = None
    if data.device_id:
        device = db.query(Device).filter(Device.device_id == data.device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device {data.device_id} not found")
        active = db.query(MonitoringSession).filter(
            MonitoringSession.device_id == data.device_id,
            MonitoringSession.status == "active",
        ).first()
        if active:
            raise HTTPException(status_code=409, detail=f"Device is active in session {active.session_id}")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    session_id = data.session_id or f"sess_{now_utc.strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
    if db.query(MonitoringSession).filter(MonitoringSession.session_id == session_id).first():
        raise HTTPException(status_code=409, detail=f"Session {session_id} already exists")

    session = MonitoringSession(
        session_id=session_id,
        patient_id=patient.id,
        device_id=data.device_id,
        bed=data.bed or patient.bed,
        notes=data.notes,
    )
    db.add(session)
    if device:
        device.assigned_patient_id = patient.id
        device.status = "in_use"
    db.commit()
    db.refresh(session)
    return session.to_dict()


@router.get("/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    return _get_session(session_id, db).to_dict()


@router.post("/{session_id}/stop")
def stop_session(session_id: str, db: Session = Depends(get_db)):
    session = _get_session(session_id, db)
    if session.status != "stopped":
        session.status = "stopped"
        session.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if session.device_id:
            device = db.query(Device).filter(Device.device_id == session.device_id).first()
            if device:
                device.status = "available"
                device.assigned_patient_id = None
        db.commit()
        db.refresh(session)
    return session.to_dict()


@router.get("/{session_id}/telemetry/latest")
def get_session_latest_telemetry(session_id: str, db: Session = Depends(get_db)):
    _get_session(session_id, db)
    event = db.query(TelemetryEvent).filter(
        TelemetryEvent.session_id == session_id
    ).order_by(desc(TelemetryEvent.id)).first()
    return event.to_dict() if event else {"message": "No telemetry events yet"}


@router.get("/{session_id}/telemetry/history")
def get_session_telemetry_history(
    session_id: str,
    minutes: int = Query(default=5, ge=1, le=1440),
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    _get_session(session_id, db)
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)
    events = db.query(TelemetryEvent).filter(
        TelemetryEvent.session_id == session_id,
        TelemetryEvent.received_at >= cutoff,
    ).order_by(desc(TelemetryEvent.id)).limit(limit).all()
    return [event.to_dict() for event in events]


@router.get("/{session_id}/events")
def get_session_events(
    session_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    _get_session(session_id, db)
    telemetry = db.query(TelemetryEvent).filter(
        TelemetryEvent.session_id == session_id
    ).order_by(desc(TelemetryEvent.id)).limit(limit).all()
    health = db.query(DeviceHealthEvent).filter(
        DeviceHealthEvent.session_id == session_id
    ).order_by(desc(DeviceHealthEvent.id)).limit(limit).all()
    events = (
        [{"type": "telemetry", "recorded_at": e.received_at.isoformat(), "data": e.to_dict()} for e in telemetry]
        + [{"type": "device_health", "recorded_at": e.received_at.isoformat(), "data": e.to_dict()} for e in health]
    )
    return sorted(events, key=lambda item: item["recorded_at"], reverse=True)[:limit]
