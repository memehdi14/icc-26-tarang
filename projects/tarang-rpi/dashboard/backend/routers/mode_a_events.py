"""
Tarang Clinical — Mode A (Event-Driven) Router
===============================================
Endpoints for:
  - Periodic Vitals (POST /vitals, GET /vitals/latest, GET /vitals/range)
  - 5-Min Analytics Rollups (POST /analytics, GET /analytics/latest, GET /analytics/history)
  - Anomaly Clinical Events + 4s Snippets + Annotations (POST /events, GET /events/latest, GET /events/:id/snippet)
"""

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import VitalsSample, Analytics5Min, ClinicalEvent, EcgSnippet, BeatAnnotation
from routers.telemetry import manager

router = APIRouter(tags=["mode_a"])


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class VitalsIngestItem(BaseModel):
    device_id: str = Field(default="tarang-efr32-demo")
    session_id: Optional[str] = None
    heart_rate_bpm: Optional[int] = Field(default=None, ge=0, le=300)
    spo2_pct: Optional[int] = Field(default=None, ge=0, le=100)
    ts: Optional[datetime] = None


class AnalyticsIngest(BaseModel):
    device_id: str = Field(default="tarang-efr32-demo")
    session_id: Optional[str] = None
    pvc_burden_pct: Optional[float] = Field(default=0.0, ge=0.0, le=100.0)
    pac_burden_pct: Optional[float] = Field(default=0.0, ge=0.0, le=100.0)
    sdnn: Optional[float] = Field(default=0.0, ge=0.0)
    rmssd: Optional[float] = Field(default=0.0, ge=0.0)
    prr50: Optional[float] = Field(default=0.0, ge=0.0, le=100.0)
    ai_duty_cycle_pct: Optional[float] = Field(default=0.0, ge=0.0, le=100.0)
    em2_sleep_pct: Optional[float] = Field(default=0.0, ge=0.0, le=100.0)
    ts: Optional[datetime] = None


class BeatAnnotationInput(BaseModel):
    offset_ms: int = Field(ge=0, le=10000)
    label: str = Field(pattern="^[NVSQ]$")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ClinicalEventIngest(BaseModel):
    device_id: str = Field(default="tarang-efr32-demo")
    session_id: Optional[str] = None
    rhythm_status: int = Field(default=0, ge=0, le=255) # 0=NSR, 1=AFib, 2=VT, ...
    pattern_type: Optional[str] = None # Couplet, Triplet, Bigeminy, Run, null
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    ts: Optional[datetime] = None

    # Optional 4s ECG snippet & annotations in single transaction
    waveform: Optional[List[float]] = None # Array of ECG samples (e.g. 1000 samples @ 250Hz)
    sample_rate_hz: Optional[int] = Field(default=250)
    annotations: Optional[List[BeatAnnotationInput]] = None


# ── Vitals Endpoints ──────────────────────────────────────────────────────────

@router.post("/api/vitals", status_code=status.HTTP_201_CREATED)
@router.post("/vitals", status_code=status.HTTP_201_CREATED)
async def ingest_vitals(
    payload: Union[VitalsIngestItem, List[VitalsIngestItem]],
    db: Session = Depends(get_db)
):
    """
    Batched or single periodic vitals writes (2-5s interval).
    Broadcasts the latest vitals update to active WebSocket clients.
    """
    items = payload if isinstance(payload, list) else [payload]
    created_samples = []

    for item in items:
        sample = VitalsSample(
            device_id=item.device_id,
            session_id=item.session_id,
            heart_rate_bpm=item.heart_rate_bpm,
            spo2_pct=item.spo2_pct,
            ts=item.ts or datetime.now(timezone.utc),
        )
        db.add(sample)
        created_samples.append(sample)

    db.commit()
    for s in created_samples:
        db.refresh(s)

    # Broadcast newest sample to WebSocket dashboard
    if created_samples:
        latest = created_samples[-1].to_dict()
        await manager.broadcast({"type": "vitals_sample", "data": latest})

    return {"status": "ok", "inserted": len(created_samples), "latestId": created_samples[-1].id if created_samples else None}


@router.get("/api/vitals/latest")
@router.get("/vitals/latest")
def get_latest_vitals(
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Return the most recent periodic vitals sample."""
    query = db.query(VitalsSample)
    if device_id:
        query = query.filter(VitalsSample.device_id == device_id)
    if session_id:
        query = query.filter(VitalsSample.session_id == session_id)
    sample = query.order_by(desc(VitalsSample.id)).first()
    if not sample:
        return {"heartRateBpm": 75, "spo2Pct": 98, "deviceId": device_id or "tarang-efr32-demo", "ts": None}
    return sample.to_dict()


@router.get("/api/vitals/range")
@router.get("/vitals/range")
def get_vitals_range(
    minutes: int = Query(default=15, ge=1, le=1440),
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Return vitals samples over the given time range."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    query = db.query(VitalsSample).filter(VitalsSample.ts >= cutoff)
    if device_id:
        query = query.filter(VitalsSample.device_id == device_id)
    if session_id:
        query = query.filter(VitalsSample.session_id == session_id)
    samples = query.order_by(VitalsSample.id.asc()).limit(1000).all()
    return [s.to_dict() for s in samples]


# ── Analytics Endpoints (5-Min Rollups) ────────────────────────────────────────

@router.post("/api/analytics", status_code=status.HTTP_201_CREATED)
@router.post("/analytics", status_code=status.HTTP_201_CREATED)
async def ingest_analytics(payload: AnalyticsIngest, db: Session = Depends(get_db)):
    """5-min analytics rollup write (Burden, HRV, Edge AI Health)."""
    analytics = Analytics5Min(
        device_id=payload.device_id,
        session_id=payload.session_id,
        pvc_burden_pct=payload.pvc_burden_pct,
        pac_burden_pct=payload.pac_burden_pct,
        sdnn=payload.sdnn,
        rmssd=payload.rmssd,
        prr50=payload.prr50,
        ai_duty_cycle_pct=payload.ai_duty_cycle_pct,
        em2_sleep_pct=payload.em2_sleep_pct,
        ts=payload.ts or datetime.now(timezone.utc),
    )
    db.add(analytics)
    db.commit()
    db.refresh(analytics)

    data = analytics.to_dict()
    await manager.broadcast({"type": "analytics_5min", "data": data})
    return {"status": "ok", "id": analytics.id}


@router.get("/api/analytics/latest")
@router.get("/analytics/latest")
def get_latest_analytics(
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Return the most recent 5-min analytics rollup."""
    query = db.query(Analytics5Min)
    if device_id:
        query = query.filter(Analytics5Min.device_id == device_id)
    if session_id:
        query = query.filter(Analytics5Min.session_id == session_id)
    rollup = query.order_by(desc(Analytics5Min.id)).first()
    if not rollup:
        return {
            "pvcBurdenPct": 0.4,
            "pacBurdenPct": 1.2,
            "sdnn": 44.0,
            "rmssd": 38.0,
            "prr50": 8.5,
            "aiDutyCyclePct": 1.5,
            "em2SleepPct": 92.0,
            "deviceId": device_id or "tarang-efr32-demo",
            "ts": None,
        }
    return rollup.to_dict()


@router.get("/api/analytics/history")
@router.get("/analytics/history")
def get_analytics_history(
    hours: int = Query(default=24, ge=1, le=168),
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Return 5-min analytics rollups over the specified hour window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = db.query(Analytics5Min).filter(Analytics5Min.ts >= cutoff)
    if device_id:
        query = query.filter(Analytics5Min.device_id == device_id)
    if session_id:
        query = query.filter(Analytics5Min.session_id == session_id)
    records = query.order_by(Analytics5Min.id.asc()).limit(500).all()
    return [r.to_dict() for r in records]


# ── Clinical Events & 4s Snippet Endpoints ────────────────────────────────────

@router.post("/api/events", status_code=status.HTTP_201_CREATED)
@router.post("/events", status_code=status.HTTP_201_CREATED)
async def ingest_clinical_event(payload: ClinicalEventIngest, db: Session = Depends(get_db)):
    """
    New clinical event + linked 4s ECG snippet + beat annotations in a single atomic transaction.
    Source of truth for triage banner flip and glitch ticker.
    """
    event = ClinicalEvent(
        device_id=payload.device_id,
        session_id=payload.session_id,
        rhythm_status=payload.rhythm_status,
        pattern_type=payload.pattern_type,
        confidence=payload.confidence,
        ts=payload.ts or datetime.now(timezone.utc),
    )
    db.add(event)
    db.flush() # Populate event.id

    snippet = None
    if payload.waveform is not None:
        snippet = EcgSnippet(
            event_id=event.id,
            device_id=payload.device_id,
            ts_start=event.ts,
            sample_rate_hz=payload.sample_rate_hz or 250,
            waveform_json=payload.waveform,
        )
        db.add(snippet)
        db.flush()

        if payload.annotations:
            for annot in payload.annotations:
                db.add(BeatAnnotation(
                    snippet_id=snippet.id,
                    offset_ms=annot.offset_ms,
                    label=annot.label,
                    confidence=annot.confidence,
                ))

    db.commit()
    db.refresh(event)

    broadcast_data = {
        "type": "clinical_event",
        "event": event.to_dict(),
        "snippet": snippet.to_dict(include_waveform=True) if snippet else None,
    }
    await manager.broadcast(broadcast_data)

    return {
        "status": "ok",
        "eventId": event.id,
        "snippetId": snippet.id if snippet else None,
    }


@router.get("/api/events/latest")
@router.get("/events/latest")
def get_latest_clinical_events(
    limit: int = Query(default=10, ge=1, le=100),
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Return the newest clinical events (for Triage banner & Glitch Ticker)."""
    query = db.query(ClinicalEvent)
    if device_id:
        query = query.filter(ClinicalEvent.device_id == device_id)
    if session_id:
        query = query.filter(ClinicalEvent.session_id == session_id)
    events = query.order_by(desc(ClinicalEvent.id)).limit(limit).all()
    return [e.to_dict() for e in events]


@router.get("/api/events/{event_id}/snippet")
@router.get("/events/{event_id}/snippet")
def get_event_snippet(event_id: int, db: Session = Depends(get_db)):
    """Return the 4s ECG snippet and AI beat annotations for a specific clinical event."""
    snippet = db.query(EcgSnippet).filter(EcgSnippet.event_id == event_id).first()
    if not snippet:
        raise HTTPException(status_code=404, detail="Snippet not found for this event ID")
    return snippet.to_dict(include_waveform=True)
