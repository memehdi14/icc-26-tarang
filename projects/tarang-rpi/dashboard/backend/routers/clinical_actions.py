"""Auditable clinical workstation actions."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import ClinicalAction, MonitoringSession, Patient


router = APIRouter(prefix="/api/clinical-actions", tags=["clinical_actions"])


class PagePhysicianRequest(BaseModel):
    mrn: str = Field(min_length=1, max_length=50)
    session_id: Optional[str] = Field(default=None, max_length=64)
    priority: str = Field(default="urgent", pattern="^(routine|urgent|critical)$")
    reason: Optional[str] = Field(default=None, max_length=500)
    requested_by: str = Field(default="Tarang clinical workstation", min_length=1, max_length=200)


@router.post("/page-physician", status_code=status.HTTP_201_CREATED)
def page_physician(data: PagePhysicianRequest, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.mrn == data.mrn).first()
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient MRN {data.mrn} not found")

    if data.session_id:
        session = db.query(MonitoringSession).filter(
            MonitoringSession.session_id == data.session_id,
            MonitoringSession.patient_id == patient.id,
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Monitoring session not found for this patient")

    action = ClinicalAction(
        patient_id=patient.id,
        session_id=data.session_id,
        action_type="page_physician",
        priority=data.priority,
        status="queued",
        reason=data.reason or "Clinical review requested from the Tarang workstation",
        requested_by=data.requested_by,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action.to_dict()


@router.get("")
def list_clinical_actions(
    mrn: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(ClinicalAction)
    if mrn:
        patient = db.query(Patient).filter(Patient.mrn == mrn).first()
        if not patient:
            return []
        query = query.filter(ClinicalAction.patient_id == patient.id)
    if session_id:
        query = query.filter(ClinicalAction.session_id == session_id)
    return [action.to_dict() for action in query.order_by(desc(ClinicalAction.id)).limit(limit).all()]
