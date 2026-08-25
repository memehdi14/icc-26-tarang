"""
Tarang Clinical — FastAPI Main Application
==========================================
Run with:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Or from the backend directory:
    python -m uvicorn main:app --host 0.0.0.0 --port 8000
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.connection import get_db, init_db, SessionLocal
from database.models import DeviceDiagnostics, SystemSetting

from routers import (
    telemetry,
    patients,
    diagnostics,
    devices,
    sessions,
    integrations,
    settings as settings_router,
    health as health_router,
    mode_a_events,
    clinical_actions,
)


# ── Seed default data on first run ───────────────────────────────────────────

def seed_defaults():
    """Populate neutral diagnostics and settings; clinical data is user-created."""
    default_device_mac = os.getenv("TARANG_BLE_ADDRESS", "00:00:00:00:00:00")
    db = SessionLocal()
    try:
        # Neutral diagnostics keep the bootstrap response schema stable.
        if not db.query(DeviceDiagnostics).first():
            db.add(DeviceDiagnostics(
                ble_connected=False,
                device_name="EFR32MG26 (Tarang SoC)",
                device_mac=default_device_mac,
                firmware_version="v1.0.0-EFR32MG26",
                rssi_dbm=-100,
                packets_received=0,
                packets_dropped=0,
                latency_ms=0.0,
                battery_pct=0,
            ))

        # Non-clinical workstation defaults are safe to seed.
        if not db.query(SystemSetting).first():
            db.add(SystemSetting())

        db.commit()
    finally:
        db.close()


# ── App Lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB tables and seed defaults on startup."""
    init_db()
    seed_defaults()
    print("[TARANG] Backend started. Database initialized.")
    yield
    print("[TARANG] Backend shutting down.")


# ── OpenAPI Metadata & Tags ──────────────────────────────────────────────────

TAGS_METADATA = [
    {
        "name": "mode_a",
        "description": "🫀 **Real-Time ECG Waveform & Anomaly Ingestion** — Live Mode A clinical event streaming, beat annotations, and 1Hz vitals.",
    },
    {
        "name": "clinical_actions",
        "description": "🚨 **Emergency Alerts & Physician Paging** — Trigger high-priority physician emergency pages and generate auditable clinical action logs.",
    },
    {
        "name": "telemetry",
        "description": "📈 **Real-Time Telemetry & WebSocket** — Live continuous ECG waveform stream (/ws/telemetry) and vitals subscription.",
    },
    {
        "name": "integrations-v1",
        "description": "🏥 **Hospital CRM & FHIR Integrations** — Admitted patient synchronization and observation exports.",
    },
    {
        "name": "diagnostics",
        "description": "🩺 **Hardware Health & BLE Diagnostics** — Monitor RSSI dBm, battery %, BLE latency, packet drop rates, and SQI.",
    },
    {
        "name": "patients",
        "description": "👤 **Patient Management** — Create, list, and switch clinical patients on the ICU ward.",
    },
    {
        "name": "health",
        "description": "⚡ **System Health & Connectivity** — Fast database and gateway connectivity probes.",
    },
]


# ── FastAPI Application ───────────────────────────────────────────────────────

app = FastAPI(
    title="Tarang Clinical Workstation API",
    description="""
### 🏥 Tarang Clinical Telemetry Gateway (Real-Time Ingestion)

Welcome to the **Tarang Clinical API**. This interface provides real-time access to the live Bluetooth Low Energy stream from the Tarang sensor patch, hospital EHR integration hooks, and bedside workstation telemetry.

---

### 🚀 Key Real-Time Workflows:
1. **Live ECG Waveforms & Vitals**:
   - `GET /api/vitals/latest` — 1 Hz Heart Rate & SpO₂.
   - `GET /api/events/latest` — Real-time anomaly event stream with beat annotations.
   - `GET /api/events/{id}/snippet` — Complete 1,000-sample waveform array for any clinical event.
2. **Emergency Physician Alerting**:
   - `POST /api/clinical-actions/page-physician` — Dispatches an urgent clinical alert for a specific patient MRN.
3. **Live Hardware Diagnostics**:
   - `GET /api/diagnostics/latest` — Live BLE link RSSI, packet delivery counters, and battery status.
4. **Real-Time WebSocket Stream**:
   - `ws://<host>:8000/ws/telemetry` — Continuous 250 Hz sample broadcast directly to dashboard clients.
""",
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=TAGS_METADATA,
    docs_url=None,  # Custom branded Swagger UI served at /docs below
    redoc_url=None, # Custom branded ReDoc served at /redoc below
)

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("TARANG_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials="*" not in CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(mode_a_events.router)
app.include_router(clinical_actions.router)
app.include_router(telemetry.router)
app.include_router(patients.router)
app.include_router(diagnostics.router)
app.include_router(settings_router.router)
app.include_router(health_router.router)
app.include_router(devices.router)
app.include_router(sessions.router)
app.include_router(integrations.router)

# Mount WebSocket endpoint at /ws/telemetry (separate from REST prefix)
app.add_api_websocket_route("/ws/telemetry", telemetry.websocket_telemetry)


# ── Custom Branded Swagger UI (/docs) in Tarang Theme ─────────────────────────

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    """Render Swagger UI in the Tarang Clinical Workstation Theme."""
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tarang Clinical Hub — API Documentation</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100' fill='none'%3E%3Ccircle cx='50' cy='50' r='44' fill='%23006A61' stroke='%23008378' stroke-width='3'/%3E%3Cpath d='M16 50 H32 L36 42 L40 58 L46 22 L54 78 L60 44 L64 54 L68 50 H84' stroke='%23A1F1E5' stroke-width='5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Jost:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>
    :root {{
      --paper: #F8FAFC;
      --paper-card: #FFFFFF;
      --ink: #0F172A;
      --ink-soft: #334155;
      --muted: #64748B;
      --line: #E2E8F0;
      --line-soft: #F1F5F9;
      --accent: #0F172A;
      --clinical-teal: #059669;
      --clinical-teal-soft: rgba(5, 150, 105, 0.08);
      --cardiac-rose: #DC2626;
      --cardiac-rose-soft: rgba(220, 38, 38, 0.08);
      --deep-ocean: #0284C7;
      --deep-ocean-soft: rgba(2, 132, 199, 0.08);
      --font-sans: 'Jost', system-ui, -apple-system, sans-serif;
      --font-mono: 'JetBrains Mono', Consolas, monospace;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      padding: 0;
      background-color: var(--paper);
      color: var(--ink);
      font-family: var(--font-sans);
      -webkit-font-smoothing: antialiased;
    }}
    /* Top Header Branding */
    .tarang-docs-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 62px;
      padding: 0 32px;
      background: #FFFFFF;
      border-bottom: 1px solid var(--line);
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03);
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    .tarang-docs-brand {{
      display: flex;
      align-items: center;
      gap: 14px;
      text-decoration: none;
      color: var(--ink);
    }}
    .tarang-logo-emblem {{
      width: 36px;
      height: 36px;
      filter: drop-shadow(0 2px 4px rgba(5, 150, 105, 0.2));
    }}
    .tarang-docs-title-wrap {{
      display: flex;
      flex-direction: column;
    }}
    .tarang-docs-title {{
      font-weight: 700;
      font-size: 16px;
      letter-spacing: -0.02em;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .tarang-docs-subtitle {{
      font-size: 11px;
      color: var(--muted);
      font-weight: 500;
    }}
    .tarang-status-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--clinical-teal-soft);
      color: var(--clinical-teal);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: 9999px;
      border: 1px solid rgba(5, 150, 105, 0.2);
    }}
    .tarang-status-dot {{
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--clinical-teal);
      animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: .3; }}
    }}
    .tarang-docs-actions {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .tarang-btn {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      font-size: 12px;
      font-weight: 600;
      color: var(--ink);
      text-decoration: none;
      padding: 7px 16px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #FFFFFF;
      transition: all 0.15s ease;
      cursor: pointer;
    }}
    .tarang-btn:hover {{
      border-color: var(--ink);
      background: var(--paper);
    }}
    .tarang-btn--primary {{
      background: var(--ink);
      color: #FFFFFF;
      border-color: var(--ink);
    }}
    .tarang-btn--primary:hover {{
      background: #334155;
      color: #FFFFFF;
    }}
    .tarang-btn svg {{
      width: 14px;
      height: 14px;
    }}

    /* Hero Guide Banner */
    .tarang-hero-container {{
      max-width: 1420px;
      margin: 24px auto 0 auto;
      padding: 0 24px;
    }}
    .tarang-hero-banner {{
      background: #FFFFFF;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 20px 24px;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.02);
    }}
    .tarang-hero-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 16px;
    }}
    .tarang-hero-header h2 {{
      margin: 0;
      font-size: 14px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--ink);
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .tarang-hero-header p {{
      margin: 2px 0 0 0;
      font-size: 12px;
      color: var(--muted);
    }}
    .tarang-cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }}
    .tarang-action-card {{
      display: flex;
      align-items: flex-start;
      gap: 12px;
      padding: 12px 14px;
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      text-decoration: none;
      color: var(--ink);
      transition: all 0.15s ease;
    }}
    .tarang-action-card:hover {{
      border-color: var(--deep-ocean);
      background: #FFFFFF;
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
    }}
    .tarang-card-icon {{
      width: 32px;
      height: 32px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      shrink-0: 0;
    }}
    .tarang-card-icon--teal {{ background: var(--clinical-teal-soft); color: var(--clinical-teal); }}
    .tarang-card-icon--rose {{ background: var(--cardiac-rose-soft); color: var(--cardiac-rose); }}
    .tarang-card-icon--blue {{ background: var(--deep-ocean-soft); color: var(--deep-ocean); }}
    .tarang-card-icon--dark {{ background: rgba(15, 23, 42, 0.06); color: var(--ink); }}
    .tarang-card-body h4 {{
      margin: 0;
      font-size: 12px;
      font-weight: 700;
    }}
    .tarang-card-body code {{
      font-family: var(--font-mono);
      font-size: 10.5px;
      color: var(--muted);
      display: block;
      margin-top: 2px;
    }}

    /* Swagger UI Container Overrides */
    .swagger-ui {{
      font-family: var(--font-sans);
      color: var(--ink);
    }}
    .swagger-ui .wrapper {{
      max-width: 1420px;
      padding: 0 24px;
    }}
    .swagger-ui .topbar {{
      display: none !important;
    }}
    .swagger-ui .info {{
      margin: 24px 0 16px 0;
    }}
    .swagger-ui .info .title {{
      font-family: var(--font-sans);
      font-size: 28px;
      font-weight: 700;
      color: var(--ink);
      letter-spacing: -0.02em;
    }}
    .swagger-ui .info p, .swagger-ui .info li {{
      font-family: var(--font-sans);
      color: var(--ink-soft);
      font-size: 14px;
      line-height: 1.6;
    }}
    .swagger-ui .scheme-container {{
      background: #FFFFFF;
      box-shadow: none;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 16px 20px;
      margin: 16px 0 24px 0;
    }}
    .swagger-ui .opblock {{
      border-radius: 10px !important;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.02) !important;
      margin-bottom: 12px !important;
      border: 1px solid var(--line) !important;
      background: #FFFFFF !important;
    }}
    .swagger-ui .opblock .opblock-summary {{
      padding: 10px 16px !important;
    }}
    .swagger-ui .opblock .opblock-summary-method {{
      border-radius: 6px !important;
      font-family: var(--font-mono) !important;
      font-weight: 700 !important;
      font-size: 12px !important;
      padding: 6px 14px !important;
    }}
    .swagger-ui .opblock-tag {{
      font-family: var(--font-sans) !important;
      font-size: 16px !important;
      font-weight: 700 !important;
      color: var(--ink) !important;
      border-bottom: 1px solid var(--line) !important;
      padding: 18px 0 8px 0 !important;
    }}
    .swagger-ui .opblock-tag small {{
      font-family: var(--font-sans) !important;
      color: var(--muted) !important;
      font-size: 12px !important;
    }}
    .swagger-ui .opblock-post .opblock-summary-method {{
      background: var(--ink) !important;
    }}
    .swagger-ui .opblock-get .opblock-summary-method {{
      background: var(--clinical-teal) !important;
    }}
    .swagger-ui .opblock-delete .opblock-summary-method {{
      background: var(--cardiac-rose) !important;
    }}
    .swagger-ui .btn.execute {{
      background-color: var(--clinical-teal) !important;
      border-color: var(--clinical-teal) !important;
      color: #FFFFFF !important;
      font-family: var(--font-sans) !important;
      font-weight: 700 !important;
      font-size: 13px !important;
      border-radius: 8px !important;
      padding: 8px 24px !important;
      transition: background-color 0.15s ease;
    }}
    .swagger-ui .btn.execute:hover {{
      background-color: #047857 !important;
    }}
    .swagger-ui .btn.try-out__btn {{
      font-family: var(--font-sans) !important;
      font-weight: 600 !important;
      border-radius: 6px !important;
    }}
    .swagger-ui select, .swagger-ui input[type="text"] {{
      border-radius: 6px !important;
      border: 1px solid var(--line) !important;
      font-family: var(--font-mono) !important;
    }}
    .swagger-ui table.parameters {{
      font-family: var(--font-sans);
    }}
    .swagger-ui table.parameters .parameter__name {{
      font-family: var(--font-mono);
      font-weight: 600;
    }}
    .swagger-ui pre, .swagger-ui code {{
      font-family: var(--font-mono) !important;
      font-size: 12px !important;
    }}
  </style>
</head>
<body>
  <!-- Tarang Branded Header -->
  <header class="tarang-docs-header">
    <a id="brand-link" href="http://localhost:3000" class="tarang-docs-brand">
      <svg class="tarang-logo-emblem" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="50" cy="50" r="44" fill="#006A61" stroke="#008378" stroke-width="3" />
        <path d="M50 10 V90 M10 50 H90 M25 10 V90 M75 10 V90 M10 25 H90 M10 75 H90" stroke="rgba(255,255,255,0.08)" stroke-width="1" />
        <path d="M 16 50 H 32 L 36 42 L 40 58 L 46 22 L 54 78 L 60 44 L 64 54 L 68 50 H 84" stroke="#A1F1E5" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" />
        <circle cx="46" cy="22" r="3.5" fill="#FFFFFF" />
      </svg>
      <div class="tarang-docs-title-wrap">
        <span class="tarang-docs-title">
          Tarang Clinical Hub
        </span>
        <span class="tarang-docs-subtitle">Bedside Telemetry & External Trigger Gateway</span>
      </div>
    </a>
    <div class="tarang-docs-actions">
      <span class="tarang-status-badge">
        <span class="tarang-status-dot"></span>
        API Online
      </span>
      <a id="live-workstation-btn" href="http://localhost:3000" class="tarang-btn tarang-btn--primary" target="_blank">
        <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        Open Bedside Workstation
      </a>
      <a href="/api/health" class="tarang-btn" target="_blank">
        <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        Health Probe
      </a>
    </div>
  </header>

  <!-- Real-Time Telemetry Fast-Track Banner -->
  <div class="tarang-hero-container">
    <div class="tarang-hero-banner">
      <div class="tarang-hero-header">
        <div>
          <h2>✦ Real-Time Live Telemetry Fast-Track</h2>
          <p>Explore live Bluetooth ECG ingestion, real-time arrhythmia alerts, and physician paging:</p>
        </div>
      </div>
      <div class="tarang-cards-grid">
        <div class="tarang-action-card">
          <div class="tarang-card-icon tarang-card-icon--teal">
            <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div class="tarang-card-body">
            <h4>Live ECG Anomaly Ingestion</h4>
            <code>POST /api/events</code>
          </div>
        </div>

        <div class="tarang-action-card">
          <div class="tarang-card-icon tarang-card-icon--rose">
            <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <div class="tarang-card-body">
            <h4>Dispatch Physician Emergency Page</h4>
            <code>POST /api/clinical-actions/page-physician</code>
          </div>
        </div>

        <div class="tarang-action-card">
          <div class="tarang-card-icon tarang-card-icon--blue">
            <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
            </svg>
          </div>
          <div class="tarang-card-body">
            <h4>Stream 1 Hz Live Vitals</h4>
            <code>GET /api/vitals/latest</code>
          </div>
        </div>

        <div class="tarang-action-card">
          <div class="tarang-card-icon tarang-card-icon--dark">
            <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
            </svg>
          </div>
          <div class="tarang-card-body">
            <h4>Hardware Health & BLE RSSI</h4>
            <code>GET /api/diagnostics/latest</code>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div id="swagger-ui"></div>

  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => {{
      // Dynamically bind live workstation buttons to current host on port 3000
      try {{
        const host = window.location.hostname || 'localhost';
        const port = window.location.protocol === 'https:' ? '' : ':3000';
        const target = window.location.protocol + '//' + host + port;
        const brandLink = document.getElementById('brand-link');
        const liveBtn = document.getElementById('live-workstation-btn');
        if (brandLink) brandLink.href = target;
        if (liveBtn) liveBtn.href = target;
      }} catch (e) {{}}

      window.ui = SwaggerUIBundle({{
        url: '/openapi.json',
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout",
        defaultModelsExpandDepth: 1,
        defaultModelExpandDepth: 1,
        docExpansion: "list",
        filter: true,
        showExtensions: true,
        showCommonExtensions: true,
      }});
    }};
  </script>
</body>
</html>
""")


# ── Health Check ─────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
def health():
    return {
        "status": "ok",
        "service": "Tarang Clinical API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
    }


@app.get("/api/health", tags=["health"])
def api_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "service": "Tarang Clinical API"}
