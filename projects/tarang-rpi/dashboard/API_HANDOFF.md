# Tarang API and UI Handoff

## End-user flow

1. Open the patient worklist (`GET /api/patients`).
2. Add a patient or select an existing patient.
3. Select an available device (`GET /api/devices?status=available`).
4. Start monitoring (`POST /api/sessions`) with the patient MRN and device ID.
5. Open the existing workstation using the returned `session_id`.
6. Stream live data over `/ws/telemetry` and load history from the session endpoints.
7. Stop monitoring (`POST /api/sessions/{session_id}/stop`) to release the device.

A clean database starts with an empty patient worklist. The UI must preserve
`null`/unavailable clinical values during acquisition and algorithm warmup; it
must not replace them with demonstration HR or SpO2 values.

## UI direction

- First screen: compact patient worklist with search, status, bed, active device, and an Add Patient action.
- Patient form: demographics and clinical context only; keep device assignment in the next step.
- Start-monitoring step: patient summary, available-device selector, connection status, then one Start action.
- Dashboard: retain the current workstation; add the selected patient and active session to its route/state.
- Session review: start/end time, latest vitals, rhythm events, connection diagnostics, and export/integration action.
- Always show empty, loading, disconnected, reconnecting, and device-already-in-use states.

## Internal API

- `GET|POST /api/patients`
- `GET|PUT|PATCH /api/patients/{mrn}`
- `GET|POST /api/devices`
- `POST /api/devices/register`
- `GET|PATCH /api/devices/{device_id}`
- `POST /api/devices/{device_id}/assign`
- `GET|POST /api/sessions`
- `GET /api/sessions/{session_id}`
- `POST /api/sessions/{session_id}/stop`
- `GET /api/sessions/{session_id}/telemetry/latest`
- `GET /api/sessions/{session_id}/telemetry/history`
- `GET /api/sessions/{session_id}/events`
- `POST /api/telemetry/ingest`
- `POST /api/health/ingest`
- `GET /api/events/{event_id}/snippet`
- `GET /api/events/{event_id}/pdf`
- `POST /api/clinical-actions/page-physician`
- `GET /api/clinical-actions?mrn=&session_id=`
- `GET|PUT /api/settings`
- `WS /ws/telemetry`

## External integration API

- `GET /api/v1/patients?mrn=`
- `PUT /api/v1/patients/{mrn}` (idempotent CRM/HIS upsert)
- `GET /api/v1/devices?status=`
- `GET /api/v1/observations?patientId=&mrn=&sessionId=&from=&to=&limit=`
- `GET /api/v1/sessions/{session_id}/summary`
- Interactive schema: `/docs`; machine-readable schema: `/openapi.json`

The versioned resources are FHIR-inspired, not certified FHIR resources. Put a vendor-specific adapter in front of this API when a hospital requires exact FHIR R4, HL7 v2, or proprietary CRM fields.

## Raspberry Pi configuration

- Backend database: `TARANG_DATABASE_URL` (defaults to `dashboard/database/tarang_clinical.db`).
- Allowed frontend origins: `TARANG_CORS_ORIGINS` (defaults to `*` for hackathon LAN use).
- Frontend API URL: `NEXT_PUBLIC_API_URL`.
- Frontend WebSocket URL: `NEXT_PUBLIC_WS_URL`.
- Gateway backend URL: `TARANG_BACKEND_URL`.
- Gateway device selector: `TARANG_BLE_ADDRESS` (optional; otherwise it scans).
- Gateway name selector: `TARANG_BLE_NAME_PREFIX` (defaults to `TARANG`).
- Gateway pairing: `TARANG_BLE_PAIR=true` pairs before protected GATT discovery.
- Gateway API device identifier: `TARANG_DEVICE_ID` (defaults to the BLE address).
- Gateway active session: `TARANG_SESSION_ID` (set this to the ID returned by `POST /api/sessions`).

When `TARANG_SESSION_ID` is unset, the gateway polls the backend for the active
session assigned to `TARANG_DEVICE_ID`. An explicit value pins ingestion to one
session and disables automatic session switching.

The current firmware requires 14 subscriptions: HR, SpO2, seven analytics
scalars, event metadata, ECG chunks, beat annotations, rhythm, and pattern
ticker. The event-control characteristic is a command input in the current
runtime and is intentionally not subscribed. There is no dedicated
device-health characteristic in the current generated GATT database;
readiness is connection plus first real telemetry.

Run the backend smoke test before deployment:

```powershell
cd dashboard/backend
./venv/Scripts/python.exe -m unittest discover -s tests -v
```
