"""
Tarang Clinical — Telemetry Router
====================================
REST endpoints + WebSocket for real-time clinical telemetry.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database.connection import get_db
from database.models import TelemetryEvent

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

# ── WebSocket Connection Manager ──────────────────────────────────────────────

class ConnectionManager:
    """Manages active WebSocket connections for live telemetry broadcast."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Send JSON message to all connected dashboard clients."""
        data = json.dumps(message)
        stale = []
        for conn in self.active_connections:
            try:
                await conn.send_text(data)
            except Exception:
                stale.append(conn)
        for conn in stale:
            self.disconnect(conn)


manager = ConnectionManager()


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class TelemetryIngest(BaseModel):
    session_id: Optional[str] = None
    timestamp_ms: int = Field(ge=0)
    beat_class: int = Field(default=0, ge=0, le=3)
    confidence: int = Field(default=0, ge=0, le=255)
    rr_interval_ms: int = Field(default=0, ge=0, le=65535)
    rhythm_flags: int = Field(default=0, ge=0, le=255)
    pac_burden_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    pvc_burden_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    current_hr: int = Field(default=0, ge=0, le=255)
    sdnn_ms: int = Field(default=0, ge=0, le=65535)
    rmssd_ms: int = Field(default=0, ge=0, le=65535)


# ── REST Endpoints ────────────────────────────────────────────────────────────

@router.get("/latest")
def get_latest_telemetry(db: Session = Depends(get_db)):
    """Return the most recent telemetry event."""
    event = db.query(TelemetryEvent).order_by(desc(TelemetryEvent.id)).first()
    if not event:
        return {"message": "No telemetry events yet"}
    return event.to_dict()


@router.get("/history")
def get_telemetry_history(
    minutes: int = Query(default=5, ge=1, le=60),
    session_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return telemetry events from the last N minutes."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    query = db.query(TelemetryEvent).filter(TelemetryEvent.received_at >= cutoff)
    if session_id:
        query = query.filter(TelemetryEvent.session_id == session_id)
    events = query.order_by(desc(TelemetryEvent.id)).limit(500).all()
    return [e.to_dict() for e in events]


@router.post("/ingest")
async def ingest_telemetry(packet: TelemetryIngest, db: Session = Depends(get_db)):
    """
    BLE Gateway posts decoded 16-byte packets here.
    Stores to DB and broadcasts to all WebSocket dashboard clients.
    """
    event = TelemetryEvent(
        session_id=packet.session_id,
        timestamp_ms=packet.timestamp_ms,
        beat_class=packet.beat_class,
        confidence=packet.confidence,
        rr_interval_ms=packet.rr_interval_ms,
        rhythm_flags=packet.rhythm_flags,
        pac_burden_pct=packet.pac_burden_pct,
        pvc_burden_pct=packet.pvc_burden_pct,
        current_hr=packet.current_hr,
        sdnn_ms=packet.sdnn_ms,
        rmssd_ms=packet.rmssd_ms,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    # Broadcast to all connected WebSocket dashboard clients
    await manager.broadcast(event.to_dict())

    return {"status": "ok", "id": event.id}


# ── WebSocket Endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_telemetry(websocket: WebSocket):
    """
    Live telemetry WebSocket. Dashboard connects here to receive
    real-time clinical event packets as JSON.
    """
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client doesn't need to send anything
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
