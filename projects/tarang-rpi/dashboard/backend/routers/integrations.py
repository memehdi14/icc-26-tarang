"""Versioned, read-oriented API for CRM and hospital-system integrations."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import (
    Device,
    DeviceHealthEvent,
    MonitoringSession,
    Patient,
    TelemetryEvent,
)

router = APIRouter(prefix="/api/v1", tags=["integrations-v1"])


class ExternalPatientUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    age: int = Field(default=0, ge=0, le=130)
    gender: str = Field(default="Other", max_length=20)
    bed: str = Field(default="Unassigned", max_length=50)
    admitDate: str = Field(default="Not recorded", max_length=20)
    attendingPhysician: str = Field(default="Unassigned", max_length=200)
    bloodType: str = Field(default="Unknown", max_length=10)
    allergies: list[str] = Field(default_factory=list)
    medicalHistory: list[str] = Field(default_factory=list)


def _patient_resource(patient: Patient) -> dict:
    return {
        "resourceType": "Patient",
        "id": str(patient.id),
        "identifier": {"system": "urn:tarang:mrn", "value": patient.mrn},
        "name": patient.name,
        "gender": patient.gender,
        "age": patient.age,
        "bed": patient.bed,
        "attendingPhysician": patient.attending_physician,
    }


def _observation_resource(event: TelemetryEvent, patient_id: Optional[int]) -> dict:
    return {
        "resourceType": "Observation",
        "id": str(event.id),
        "status": "final",
        "code": "tarang-cardiac-telemetry",
        "patientId": str(patient_id) if patient_id is not None else None,
        "sessionId": event.session_id,
        "effectiveDateTime": event.received_at.isoformat() if event.received_at else None,
        "value": {
            "heartRateBpm": event.current_hr,
            "rrIntervalMs": event.rr_interval_ms,
            "beatClass": event.beat_class,
            "confidence": event.confidence,
            "rhythmFlags": event.rhythm_flags,
            "pacBurdenPct": event.pac_burden_pct,
            "pvcBurdenPct": event.pvc_burden_pct,
            "sdnnMs": event.sdnn_ms,
            "rmssdMs": event.rmssd_ms,
        },
    }


@router.get("/patients")
def list_integration_patients(
    mrn: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(Patient)
    if mrn:
        query = query.filter(Patient.mrn == mrn)
    records = query.order_by(Patient.id).limit(limit).all()
    return {"data": [_patient_resource(patient) for patient in records], "count": len(records)}


@router.put("/patients/{mrn}")
def upsert_integration_patient(
    mrn: str,
    data: ExternalPatientUpsert,
    db: Session = Depends(get_db),
):
    """Idempotently create or update a patient using the hospital MRN."""
    patient = db.query(Patient).filter(Patient.mrn == mrn).first()
    values = {
        "name": data.name,
        "age": data.age,
        "gender": data.gender,
        "bed": data.bed,
        "admit_date": data.admitDate,
        "attending_physician": data.attendingPhysician,
        "blood_type": data.bloodType,
        "allergies": data.allergies,
        "medical_history": data.medicalHistory,
    }
    if patient:
        for field, value in values.items():
            setattr(patient, field, value)
    else:
        patient = Patient(mrn=mrn, **values)
        db.add(patient)
    db.commit()
    db.refresh(patient)
    return _patient_resource(patient)


@router.get("/devices")
def list_integration_devices(
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(Device)
    if status:
        query = query.filter(Device.status == status)
    records = query.order_by(Device.id).limit(limit).all()
    return {"data": [device.to_dict() for device in records], "count": len(records)}


@router.get("/observations")
def list_observations(
    patient_id: Optional[int] = Query(default=None, alias="patientId"),
    mrn: Optional[str] = None,
    session_id: Optional[str] = Query(default=None, alias="sessionId"),
    date_from: Optional[datetime] = Query(default=None, alias="from"),
    date_to: Optional[datetime] = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    if mrn:
        patient = db.query(Patient).filter(Patient.mrn == mrn).first()
        if not patient:
            raise HTTPException(status_code=404, detail=f"Patient MRN {mrn} not found")
        patient_id = patient.id

    session_patient = {}
    if patient_id is not None:
        sessions = db.query(MonitoringSession).filter(MonitoringSession.patient_id == patient_id).all()
        session_ids = [session.session_id for session in sessions]
        if not session_ids:
            return {"data": [], "count": 0}
        session_patient = {session.session_id: session.patient_id for session in sessions}
    elif session_id:
        session = db.query(MonitoringSession).filter(MonitoringSession.session_id == session_id).first()
        if session:
            session_patient[session.session_id] = session.patient_id

    query = db.query(TelemetryEvent)
    if session_id:
        query = query.filter(TelemetryEvent.session_id == session_id)
    elif patient_id is not None:
        query = query.filter(TelemetryEvent.session_id.in_(list(session_patient)))
    if date_from:
        query = query.filter(TelemetryEvent.received_at >= date_from.replace(tzinfo=None))
    if date_to:
        query = query.filter(TelemetryEvent.received_at <= date_to.replace(tzinfo=None))

    records = query.order_by(desc(TelemetryEvent.id)).limit(limit).all()
    data = [_observation_resource(event, session_patient.get(event.session_id)) for event in records]
    return {"data": data, "count": len(data)}


@router.get("/sessions/{session_id}/summary")
def get_session_summary(session_id: str, db: Session = Depends(get_db)):
    session = db.query(MonitoringSession).filter(MonitoringSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    patient = db.query(Patient).filter(Patient.id == session.patient_id).first()
    device = db.query(Device).filter(Device.device_id == session.device_id).first() if session.device_id else None
    latest_telemetry = db.query(TelemetryEvent).filter(
        TelemetryEvent.session_id == session_id
    ).order_by(desc(TelemetryEvent.id)).first()
    latest_health = db.query(DeviceHealthEvent).filter(
        DeviceHealthEvent.session_id == session_id
    ).order_by(desc(DeviceHealthEvent.id)).first()
    return {
        "resourceType": "MonitoringSessionSummary",
        "session": session.to_dict(),
        "patient": _patient_resource(patient) if patient else None,
        "device": device.to_dict() if device else None,
        "latestObservation": _observation_resource(latest_telemetry, session.patient_id) if latest_telemetry else None,
        "latestDeviceHealth": latest_health.to_dict() if latest_health else None,
    }
