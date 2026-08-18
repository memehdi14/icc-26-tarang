"""
Tarang Clinical — Patients Router
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mrn: str = Field(min_length=1, max_length=50)
    age: int = Field(default=0, ge=0, le=130)
    gender: str = Field(default="Other", max_length=20)
    bed: str = Field(default="Unassigned", max_length=50)
    admit_date: str = Field(default="Not recorded", max_length=20)
    attending_physician: str = Field(default="Unassigned", max_length=200)
    blood_type: str = Field(default="Unknown", max_length=10)
    allergies: List[str] = Field(default_factory=list)
    medical_history: List[str] = Field(default_factory=list)


@router.get("")
def list_patients(db: Session = Depends(get_db)):
    """Return the patient worklist."""
    return [patient.to_dict() for patient in db.query(Patient).order_by(Patient.name).all()]


@router.post("", status_code=201)
def create_patient(data: PatientCreate, db: Session = Depends(get_db)):
    """Add a patient to the worklist."""
    if db.query(Patient).filter(Patient.mrn == data.mrn).first():
        raise HTTPException(status_code=409, detail=f"Patient MRN {data.mrn} already exists")
    patient = Patient(**data.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient.to_dict()


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


@router.patch("/{mrn}")
def patch_patient(mrn: str, data: PatientUpdate, db: Session = Depends(get_db)):
    """Partially update patient demographics."""
    return update_patient(mrn, data, db)
