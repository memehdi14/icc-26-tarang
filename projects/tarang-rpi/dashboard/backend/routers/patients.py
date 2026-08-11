"""
Tarang Clinical — Patients Router
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import Patient

router = APIRouter(prefix="/api/patients", tags=["patients"])


class PatientUpdate(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    bed: Optional[str] = None
    attending_physician: Optional[str] = None
    blood_type: Optional[str] = None
    allergies: Optional[List[str]] = None
    medical_history: Optional[List[str]] = None


@router.get("/{mrn}")
def get_patient(mrn: str, db: Session = Depends(get_db)):
    """Fetch patient by Medical Record Number."""
    patient = db.query(Patient).filter(Patient.mrn == mrn).first()
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient MRN {mrn} not found")
    return patient.to_dict()


@router.put("/{mrn}")
def update_patient(mrn: str, data: PatientUpdate, db: Session = Depends(get_db)):
    """Update patient demographics."""
    patient = db.query(Patient).filter(Patient.mrn == mrn).first()
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient MRN {mrn} not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)

    db.commit()
    db.refresh(patient)
    return patient.to_dict()
