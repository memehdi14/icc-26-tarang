"""
Tarang Clinical — SQLAlchemy ORM Models
=======================================
Mode A (Event-Driven) Schema + Legacy Compatibility
Tables:
  - Mode A Time Series & Snapshot:
      vitals_samples, analytics_5min, clinical_events, ecg_snippets, beat_annotations
  - Management & Workstation:
      patients, devices, monitoring_sessions, clinical_actions, device_diagnostics,
      device_health_events, system_settings
  - Legacy Compatibility:
      telemetry_events
"""

from sqlalchemy import (
    Column, Integer, BigInteger, SmallInteger, Float, String, Boolean,
    DateTime, JSON, Text, LargeBinary, ForeignKey, Index, func
)
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime


class Base(DeclarativeBase):
    pass


# ── Mode A: Periodic Vitals (2-5s) ───────────────────────────────────────────

class VitalsSample(Base):
    """
    Periodic vitals (append-only time series, downsample-friendly).
    Captures Heart Rate (BPM) and SpO2 (%) at 2-5s intervals.
    """
    __tablename__ = "vitals_samples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, index=True)
    session_id = Column(String(64), nullable=True, index=True)
    ts = Column(DateTime, default=func.now(), nullable=False, index=True)
    heart_rate_bpm = Column(SmallInteger, nullable=True)
    spo2_pct = Column(SmallInteger, nullable=True)

    __table_args__ = (
        Index("ix_vitals_device_ts", "device_id", "ts"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "deviceId": self.device_id,
            "sessionId": self.session_id,
            "ts": self.ts.isoformat() if self.ts else None,
            "heartRateBpm": self.heart_rate_bpm,
            "spo2Pct": self.spo2_pct,
        }


# ── Mode A: 5-Min Analytics Rollups ──────────────────────────────────────────

class Analytics5Min(Base):
    """
    5-min analytics rollups.
    Stores PVC/PAC burden, HRV metrics (SDNN, RMSSD, pRR50), and Edge AI Health (Duty cycle %, EM2 Sleep %).
    """
    __tablename__ = "analytics_5min"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, index=True)
    session_id = Column(String(64), nullable=True, index=True)
    ts = Column(DateTime, default=func.now(), nullable=False, index=True)
    pvc_burden_pct = Column(Float, nullable=True, default=0.0)
    pac_burden_pct = Column(Float, nullable=True, default=0.0)
    sdnn = Column(Float, nullable=True, default=0.0)
    rmssd = Column(Float, nullable=True, default=0.0)
    prr50 = Column(Float, nullable=True, default=0.0)
    ai_duty_cycle_pct = Column(Float, nullable=True, default=0.0)
    em2_sleep_pct = Column(Float, nullable=True, default=0.0)

    __table_args__ = (
        Index("ix_analytics_device_ts", "device_id", "ts"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "deviceId": self.device_id,
            "sessionId": self.session_id,
            "ts": self.ts.isoformat() if self.ts else None,
            "pvcBurdenPct": self.pvc_burden_pct,
            "pacBurdenPct": self.pac_burden_pct,
            "sdnn": self.sdnn,
            "rmssd": self.rmssd,
            "prr50": self.prr50,
            "aiDutyCyclePct": self.ai_duty_cycle_pct,
            "em2SleepPct": self.em2_sleep_pct,
        }


# ── Mode A: Clinical Anomaly Events ──────────────────────────────────────────

class ClinicalEvent(Base):
    """
    Anomaly events — source of truth for the Triage Banner and Glitch Ticker.
    Notified on state change (NSR -> AFib -> VT) or glitch patterns (Couplet, Triplet, Bigeminy, Run).
    """
    __tablename__ = "clinical_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, index=True)
    session_id = Column(String(64), nullable=True, index=True)
    ts = Column(DateTime, default=func.now(), nullable=False, index=True)
    rhythm_status = Column(SmallInteger, nullable=False, default=0) # 0=NSR, 1=AFib, 2=VT, etc.
    pattern_type = Column(String(50), nullable=True) # Couplet, Triplet, Bigeminy, Trigeminy, Run, VT, etc.
    confidence = Column(Float, nullable=True, default=1.0)

    snippets = relationship("EcgSnippet", back_populates="event", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_events_device_ts", "device_id", "ts"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "deviceId": self.device_id,
            "sessionId": self.session_id,
            "ts": self.ts.isoformat() if self.ts else None,
            "rhythmStatus": self.rhythm_status,
            "patternType": self.pattern_type,
            "confidence": self.confidence,
        }


# ── Mode A: 4s ECG Snippets Blob ─────────────────────────────────────────────

class EcgSnippet(Base):
    """
    The 4s ECG snippet blob tied to an anomaly event.
    Replaces continuous streaming with high-fidelity event snapshots.
    """
    __tablename__ = "ecg_snippets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("clinical_events.id"), nullable=False, index=True)
    device_id = Column(String(64), nullable=False, index=True)
    ts_start = Column(DateTime, default=func.now(), nullable=False)
    sample_rate_hz = Column(SmallInteger, nullable=False, default=250)
    waveform = Column(LargeBinary, nullable=True) # Binary sample buffer or compressed bytes
    waveform_json = Column(JSON, nullable=True)   # Convenient array representation [1000 samples]

    event = relationship("ClinicalEvent", back_populates="snippets")
    annotations = relationship("BeatAnnotation", back_populates="snippet", cascade="all, delete-orphan")

    def to_dict(self, include_waveform: bool = True):
        data = {
            "id": self.id,
            "eventId": self.event_id,
            "deviceId": self.device_id,
            "tsStart": self.ts_start.isoformat() if self.ts_start else None,
            "sampleRateHz": self.sample_rate_hz,
            "annotations": [a.to_dict() for a in self.annotations] if self.annotations else [],
        }
        if include_waveform:
            data["waveform"] = self.waveform_json or []
        return data


# ── Mode A: Beat Annotations ─────────────────────────────────────────────────

class BeatAnnotation(Base):
    """
    AI Beat Annotations (N/V/S + confidence) positioned at offset_ms relative to the snippet start.
    """
    __tablename__ = "beat_annotations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snippet_id = Column(Integer, ForeignKey("ecg_snippets.id"), nullable=False, index=True)
    offset_ms = Column(Integer, nullable=False)
    label = Column(String(1), nullable=False) # 'N', 'V', 'S', 'Q'
    confidence = Column(Float, nullable=False, default=1.0)

    snippet = relationship("EcgSnippet", back_populates="annotations")

    def to_dict(self):
        return {
            "id": self.id,
            "snippetId": self.snippet_id,
            "offsetMs": self.offset_ms,
            "label": self.label,
            "confidence": self.confidence,
        }


# ── Management, Patient & Workstation Models ─────────────────────────────────

class Patient(Base):
    """Patient demographics and clinical context."""
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    age = Column(SmallInteger, nullable=False)
    gender = Column(String(20), nullable=False)
    mrn = Column(String(50), unique=True, nullable=False, index=True)
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


class ClinicalAction(Base):
    """Auditable workstation action such as paging the duty physician."""
    __tablename__ = "clinical_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    session_id = Column(String(64), ForeignKey("monitoring_sessions.session_id"), nullable=True, index=True)
    action_type = Column(String(40), nullable=False, index=True)
    priority = Column(String(20), nullable=False, default="routine")
    status = Column(String(20), nullable=False, default="queued", index=True)
    reason = Column(String(500), nullable=True)
    requested_by = Column(String(200), nullable=False, default="Clinical workstation")
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    acknowledged_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "patientId": self.patient_id,
            "sessionId": self.session_id,
            "actionType": self.action_type,
            "priority": self.priority,
            "status": self.status,
            "reason": self.reason,
            "requestedBy": self.requested_by,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "acknowledgedAt": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
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


# ── Legacy Compatibility Table ───────────────────────────────────────────────

class TelemetryEvent(Base):
    """Legacy table kept for backward-compatibility during Mode A transition."""
    __tablename__ = "telemetry_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=True, index=True)
    timestamp_ms = Column(BigInteger, nullable=False, index=True)
    received_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    beat_class = Column(SmallInteger, nullable=False, default=0)
    confidence = Column(SmallInteger, nullable=False, default=0)
    rr_interval_ms = Column(Integer, nullable=False, default=0)
    rhythm_flags = Column(SmallInteger, nullable=False, default=0)
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
