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
        "description": "🫀 **ECG Anomaly & Waveform Ingestion** — Trigger 4.0s 1,000-sample ECG anomaly flows, query latest clinical events, and stream 1Hz vitals.",
    },
    {
        "name": "clinical_actions",
        "description": "🚨 **Emergency Alerts & Physician Paging** — Trigger high-priority physician emergency pages and generate auditable clinical action logs.",
    },
    {
        "name": "telemetry",
        "description": "📈 **Real-Time Telemetry & WebSocket** — Live ECG waveform stream (/ws/telemetry) and vitals subscription.",
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
### 🏥 Tarang Clinical Telemetry & External Trigger Gateway

Welcome to the **Tarang Clinical API**. This interface enables external testing harnesses, hospital EHR/CRM systems, and bedside simulation tools to interact with the Tarang workstation.

---

### 🚀 Key External Workflows:
1. **Trigger External ECG Anomaly Flow**:
   - `POST /api/events/simulate` — Ingests a mathematically authentic 4.0s (1,000 samples @ 250 Hz) Lead-I ECG anomaly (PVC, VT, AFib, PAC) and immediately pops it up on the workstation screen!
2. **Trigger Emergency Physician Page**:
   - `POST /api/clinical-actions/page-physician` — Dispatches an urgent clinical alert for a specific patient MRN.
3. **Query Live Waveforms & Vitals**:
   - `GET /api/vitals/latest` — 1 Hz Heart Rate & SpO₂.
   - `GET /api/events/latest` — Anomaly event stream with beat annotations.
   - `GET /api/events/{id}/snippet` — Complete 1,000-sample waveform array for any event.
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
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Tarang Clinical — API Documentation</title>
  <link rel="icon" type="image/svg+xml" href="/logo_mark.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>
    :root {{
      --paper: #FAFAF9;
      --paper-2: #F4EFEB;
      --ink: #181816;
      --ink-soft: #42423E;
      --muted: #73736C;
      --line: rgba(24, 24, 22, 0.10);
      --accent: #8E5DB0;
      --clinical-teal: #008378;
      --cardiac-rose: #E11D48;
      --deep-ocean: #0071E3;
    }}
    body {{
      margin: 0;
      padding: 0;
      background-color: var(--paper);
      color: var(--ink);
      font-family: "Outfit", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}
    /* Top Header Branding */
    .tarang-docs-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 60px;
      padding: 0 28px;
      background: #FFFFFF;
      border-bottom: 1px solid var(--line);
      box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    }}
    .tarang-docs-brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      text-decoration: none;
      color: var(--ink);
    }}
    .tarang-docs-brand img {{
      height: 32px;
      width: auto;
    }}
    .tarang-docs-title {{
      font-weight: 700;
      font-size: 15px;
      letter-spacing: -0.01em;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .tarang-docs-tag {{
      background: #00837818;
      color: var(--clinical-teal);
      font-family: "JetBrains Mono", monospace;
      font-size: 10px;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 4px;
      text-transform: uppercase;
    }}
    .tarang-docs-links {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .tarang-link-btn {{
      font-size: 12px;
      font-weight: 600;
      color: var(--ink);
      text-decoration: none;
      padding: 6px 14px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: var(--paper-2);
      transition: all 0.2s ease;
    }}
    .tarang-link-btn:hover {{
      background: #FFFFFF;
      border-color: var(--accent);
      color: var(--accent);
    }}
    .tarang-live-btn {{
      background: var(--clinical-teal);
      color: #FFFFFF;
      border: none;
    }}
    .tarang-live-btn:hover {{
      background: #006b62;
      color: #FFFFFF;
    }}

    /* Hero Guide Banner */
    .tarang-hero-guide {{
      max-width: 1400px;
      margin: 20px auto 0 auto;
      padding: 16px 28px;
      background: #FFFFFF;
      border: 1px solid var(--line);
      border-radius: 10px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.02);
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .tarang-hero-guide h3 {{
      margin: 0;
      font-size: 13px;
      font-weight: 700;
      color: var(--ink);
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .tarang-hero-guide p {{
      margin: 4px 0 0 0;
      font-size: 12px;
      color: var(--muted);
    }}
    .tarang-quick-chips {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .tarang-chip {{
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      padding: 4px 10px;
      border-radius: 4px;
      font-weight: 600;
      background: var(--paper-2);
      color: var(--ink);
      border: 1px solid var(--line);
    }}
    .tarang-chip--post {{
      background: #8e5db015;
      color: var(--accent);
      border-color: #8e5db030;
    }}
    .tarang-chip--alert {{
      background: #e11d4815;
      color: var(--cardiac-rose);
      border-color: #e11d4830;
    }}

    /* Swagger UI Custom Overrides */
    .swagger-ui {{
      font-family: "Outfit", sans-serif;
      color: var(--ink);
    }}
    .swagger-ui .topbar {{
      display: none; /* Replaced by our branded Tarang header */
    }}
    .swagger-ui .info {{
      margin: 24px 0 16px 0;
    }}
    .swagger-ui .info .title {{
      font-family: "Outfit", sans-serif;
      font-size: 26px;
      font-weight: 700;
      color: var(--ink);
    }}
    .swagger-ui .opblock {{
      border-radius: 8px !important;
      box-shadow: 0 1px 3px rgba(0,0,0,0.02) !important;
      margin-bottom: 12px !important;
      border: 1px solid rgba(0,0,0,0.06) !important;
    }}
    .swagger-ui .opblock .opblock-summary-method {{
      border-radius: 4px !important;
      font-family: "JetBrains Mono", monospace !important;
      font-weight: 700 !important;
      font-size: 12px !important;
    }}
    .swagger-ui .opblock-tag {{
      font-family: "Outfit", sans-serif !important;
      font-size: 16px !important;
      font-weight: 700 !important;
      color: var(--ink) !important;
      border-bottom: 1px solid var(--line) !important;
      padding: 12px 0 8px 0 !important;
    }}
    .swagger-ui .opblock-post {{
      background: #fdfbff !important;
      border-color: #8E5DB040 !important;
    }}
    .swagger-ui .opblock-post .opblock-summary-method {{
      background: var(--accent) !important;
    }}
    .swagger-ui .opblock-get {{
      background: #f0fdf9 !important;
      border-color: #00837840 !important;
    }}
    .swagger-ui .opblock-get .opblock-summary-method {{
      background: var(--clinical-teal) !important;
    }}
    .swagger-ui .btn.execute {{
      background-color: var(--clinical-teal) !important;
      border-color: var(--clinical-teal) !important;
      color: #FFFFFF !important;
      font-family: "Outfit", sans-serif !important;
      font-weight: 700 !important;
      border-radius: 6px !important;
    }}
    .swagger-ui .btn.execute:hover {{
      background-color: #006b62 !important;
    }}
    .swagger-ui pre, .swagger-ui code {{
      font-family: "JetBrains Mono", Consolas, monospace !important;
    }}
  </style>
</head>
<body>
  <!-- Tarang Branded Header -->
  <header class="tarang-docs-header">
    <a id="brand-link" href="http://localhost:3000" class="tarang-docs-brand">
      <svg width="28" height="28" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" style="border-radius: 6px; flex-shrink: 0;">
        <rect width="40" height="40" rx="8" fill="#008378"/>
        <path d="M8 20H14L17 12L23 28L26 20H32" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <span class="tarang-docs-title">
        Tarang Clinical
        <span class="tarang-docs-tag">API Documentation</span>
      </span>
    </a>
    <div class="tarang-docs-links">
      <a id="live-workstation-btn" href="http://localhost:3000" class="tarang-link-btn tarang-live-btn" target="_blank">
        ⚡ Open Live Workstation
      </a>
      <a href="/api/health" class="tarang-link-btn" target="_blank">
        System Health
      </a>
    </div>
  </header>

  <!-- External Flow & Simulation Trigger Guide -->
  <div class="tarang-hero-guide">
    <div>
      <h3>✦ External Trigger & Simulation Fast-Track</h3>
      <p>Test real-time ECG ingestion and emergency alerts directly from Swagger:</p>
    </div>
    <div class="tarang-quick-chips">
      <span class="tarang-chip tarang-chip--post">POST /api/events/simulate (Inject 4s ECG Waveform)</span>
      <span class="tarang-chip tarang-chip--alert">POST /api/clinical-actions/page-physician (Trigger Emergency)</span>
      <span class="tarang-chip">GET /api/vitals/latest (Live HR & SpO2)</span>
    </div>
  </div>

  <div id="swagger-ui"></div>

  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => {{
      // Dynamically bind live workstation button to current host on port 3000
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
