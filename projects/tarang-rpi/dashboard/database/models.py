"""
Tarang Clinical — SQLAlchemy ORM Models
=======================================
Tables: telemetry_events, patients, device_diagnostics, system_settings
"""

from sqlalchemy import (
    Column, Integer, BigInteger, SmallInteger, Float, String, Boolean,
    DateTime, JSON, Text, ForeignKey, func
)
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime


class Base(DeclarativeBase):
    pass


class TelemetryEvent(Base):
    """Stores every 16-byte clinical packet received from the EFR32 via BLE."""
    __tablename__ = "telemetry_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=True, index=True)
    timestamp_ms = Column(BigInteger, nullable=False, index=True)
    received_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    beat_class = Column(SmallInteger, nullable=False, default=0)       # 0=N, 1=PAC, 2=PVC, 3=Q
    confidence = Column(SmallInteger, nullable=False, default=0)       # 0–255
    rr_interval_ms = Column(Integer, nullable=False, default=0)
    rhythm_flags = Column(SmallInteger, nullable=False, default=0)     # bitmask
    pac_burden_pct = Column(Float, nullable=False, default=0.0)
    pvc_burden_pct = Column(Float, nullable=False, default=0.0)
    current_hr = Column(SmallInteger, nullable=False, default=0)
    sdnn_ms = Column(Integer, nullable=False, default=0)
    rmssd_ms = Column(Integer, nullable=False, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "timestamp_ms": self.timestamp_ms,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "beat_class": self.beat_class,
            "confidence": self.confidence,
            "rr_interval_ms": self.rr_interval_ms,
            "rhythm_flags": self.rhythm_flags,
            "pac_burden_pct": self.pac_burden_pct,
            "pvc_burden_pct": self.pvc_burden_pct,
            "current_hr": self.current_hr,
            "sdnn_ms": self.sdnn_ms,
            "rmssd_ms": self.rmssd_ms,
        }


class Patient(Base):
    """Patient demographics and clinical context."""
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    age = Column(SmallInteger, nullable=False)
    gender = Column(String(20), nullable=False)
    mrn = Column(String(50), unique=True, nullable=False, index=True)   # Medical Record Number
    bed = Column(String(50), nullable=False)
    admit_date = Column(String(20), nullable=False)
    attending_physician = Column(String(200), nullable=False)
    blood_type = Column(String(10), nullable=False, default="Unknown")
    allergies = Column(JSON, default=list)
    medical_history = Column(JSON, default=list)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "age": self.age,
            "gender": self.gender,
            "mrn": self.mrn,
            "bed": self.bed,
            "admit_date": self.admit_date,
            "attending_physician": self.attending_physician,
            "blood_type": self.blood_type,
            "allergies": self.allergies or [],
            "medical_history": self.medical_history or [],
        }


class Device(Base):
    """A wearable device that can be assigned to a patient."""
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False, default="Tarang Wearable")
    mac_address = Column(String(20), unique=True, nullable=True, index=True)
    firmware_version = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="available", index=True)
    assigned_patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "name": self.name,
            "mac_address": self.mac_address,
            "firmware_version": self.firmware_version,
            "status": self.status,
            "assigned_patient_id": self.assigned_patient_id,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MonitoringSession(Base):
    """A bounded monitoring period linking one patient and wearable."""
    __tablename__ = "monitoring_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    device_id = Column(String(64), ForeignKey("devices.device_id"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    bed = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    started_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    ended_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "patient_id": self.patient_id,
            "device_id": self.device_id,
            "status": self.status,
            "bed": self.bed,
            "notes": self.notes,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }


class DeviceDiagnostics(Base):
    """Latest EFR32 device state snapshot."""
    __tablename__ = "device_diagnostics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ble_connected = Column(Boolean, default=False)
    device_name = Column(String(100), default="EFR32MG26 (Tarang SoC)")
    device_mac = Column(String(20), default="00:00:00:00:00:00")
    firmware_version = Column(String(50), default="v1.0.0-EFR32MG26")
    rssi_dbm = Column(Integer, default=-100)
    packets_received = Column(Integer, default=0)
    packets_dropped = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    battery_pct = Column(SmallInteger, default=0)
    ecg_health = Column(Boolean, default=True)
    ppg_health = Column(Boolean, default=True)
    imu_health = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "bleConnected": self.ble_connected,
            "deviceName": self.device_name,
            "deviceMac": self.device_mac,
            "firmwareVersion": self.firmware_version,
            "rssiDbm": self.rssi_dbm,
            "packetsReceived": self.packets_received,
            "packetsDropped": self.packets_dropped,
            "latencyMs": self.latency_ms,
            "batteryPct": self.battery_pct,
            "ecgDmaHealth": self.ecg_health,
            "ppgI2cHealth": self.ppg_health,
            "imuFifoHealth": self.imu_health,
            "lastSyncTimestamp": self.updated_at.isoformat() if self.updated_at else None,
        }


class DeviceHealthEvent(Base):
    """Stores periodic 1Hz device health telemetry snapshots."""
    __tablename__ = "device_health_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=True, index=True)
    received_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    uptime_s = Column(BigInteger, nullable=False, default=0)
    ecg_lead_off = Column(Boolean, nullable=False, default=False)
    ecg_sqi = Column(SmallInteger, nullable=False, default=255)
    ppg_finger_present = Column(Boolean, nullable=False, default=False)
    imu_ok = Column(Boolean, nullable=False, default=False)
    i2c_failure_count = Column(SmallInteger, nullable=False, default=0)
    dsp_overflow_count = Column(SmallInteger, nullable=False, default=0)
    ecg_overrun_count = Column(SmallInteger, nullable=False, default=0)
    ble_rssi = Column(SmallInteger, nullable=True, default=-60)
    battery_pct = Column(SmallInteger, nullable=True, default=None)
    fw_version = Column(String(30), default="1.0.0")

    def to_dict(self):
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "receivedAt": self.received_at.isoformat() if self.received_at else None,
            "uptimeS": self.uptime_s,
            "ecgLeadOff": self.ecg_lead_off,
            "ecgSqi": self.ecg_sqi,
            "ppgFingerPresent": self.ppg_finger_present,
            "imuOk": self.imu_ok,
            "i2cFailureCount": self.i2c_failure_count,
            "dspOverflowCount": self.dsp_overflow_count,
            "ecgOverrunCount": self.ecg_overrun_count,
            "bleRssi": self.ble_rssi,
            "batteryPct": self.battery_pct,
            "fwVersion": self.fw_version,
        }


class SystemSetting(Base):
    """Persisted alarm thresholds and workstation preferences."""
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hr_low_threshold = Column(SmallInteger, default=60)
    hr_high_threshold = Column(SmallInteger, default=100)
    spo2_low_threshold = Column(SmallInteger, default=92)
    rr_low_threshold = Column(SmallInteger, default=10)
    rr_high_threshold = Column(SmallInteger, default=24)
    ble_sync_interval_ms = Column(Integer, default=1000)
    grid_density = Column(String(20), default="standard")
    audio_alerts_enabled = Column(Boolean, default=True)
    attending_doctor = Column(String(200), default="Dr. Aris")

    def to_dict(self):
        return {
            "hrLowThreshold": self.hr_low_threshold,
            "hrHighThreshold": self.hr_high_threshold,
            "spo2LowThreshold": self.spo2_low_threshold,
            "rrLowThreshold": self.rr_low_threshold,
            "rrHighThreshold": self.rr_high_threshold,
            "bleSyncIntervalMs": self.ble_sync_interval_ms,
            "gridDensity": self.grid_density,
            "audioAlertsEnabled": self.audio_alerts_enabled,
            "attendingDoctor": self.attending_doctor,
        }
