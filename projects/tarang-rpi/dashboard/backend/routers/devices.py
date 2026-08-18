"""Device registration, inventory, and patient assignment endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import Device, Patient

router = APIRouter(prefix="/api/devices", tags=["devices"])


class DeviceCreate(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="Tarang Wearable", max_length=100)
    mac_address: Optional[str] = Field(default=None, max_length=20)
    firmware_version: Optional[str] = Field(default=None, max_length=50)
    status: str = Field(default="available", max_length=20)


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    mac_address: Optional[str] = Field(default=None, max_length=20)
    firmware_version: Optional[str] = Field(default=None, max_length=50)
    status: Optional[str] = Field(default=None, max_length=20)
    last_seen_at: Optional[datetime] = None


class DeviceAssignment(BaseModel):
    patient_id: Optional[int] = None
    mrn: Optional[str] = None
    release: bool = False

    @model_validator(mode="after")
    def validate_target(self):
        if not self.release and self.patient_id is None and not self.mrn:
            raise ValueError("patient_id or mrn is required unless release is true")
        return self


def _get_device(device_id: str, db: Session) -> Device:
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
    return device


@router.get("")
def list_devices(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Device)
    if status:
        query = query.filter(Device.status == status)
    return [device.to_dict() for device in query.order_by(Device.device_id).all()]


@router.post("", status_code=201)
@router.post("/register", status_code=201)
def register_device(data: DeviceCreate, db: Session = Depends(get_db)):
    if db.query(Device).filter(Device.device_id == data.device_id).first():
        raise HTTPException(status_code=409, detail=f"Device {data.device_id} already exists")
    if data.mac_address and db.query(Device).filter(Device.mac_address == data.mac_address).first():
        raise HTTPException(status_code=409, detail=f"MAC address {data.mac_address} already exists")
    device = Device(**data.model_dump())
    db.add(device)
    db.commit()
    db.refresh(device)
    return device.to_dict()


@router.get("/{device_id}")
def get_device(device_id: str, db: Session = Depends(get_db)):
    return _get_device(device_id, db).to_dict()


@router.patch("/{device_id}")
def update_device(device_id: str, data: DeviceUpdate, db: Session = Depends(get_db)):
    device = _get_device(device_id, db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    db.commit()
    db.refresh(device)
    return device.to_dict()


@router.post("/{device_id}/assign")
def assign_device(device_id: str, data: DeviceAssignment, db: Session = Depends(get_db)):
    device = _get_device(device_id, db)
    if data.release:
        device.assigned_patient_id = None
        device.status = "available"
    else:
        patient_query = db.query(Patient)
        patient = (
            patient_query.filter(Patient.id == data.patient_id).first()
            if data.patient_id is not None
            else patient_query.filter(Patient.mrn == data.mrn).first()
        )
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        device.assigned_patient_id = patient.id
        device.status = "assigned"
    db.commit()
    db.refresh(device)
    return device.to_dict()
