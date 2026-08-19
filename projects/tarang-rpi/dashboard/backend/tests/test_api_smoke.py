"""End-to-end API smoke test using an isolated temporary SQLite database."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(DASHBOARD_DIR))


class ApiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(cls.temp_dir.name) / "tarang_test.db"
        os.environ["TARANG_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

        import main
        from database.connection import engine

        cls.engine = engine
        cls.client_context = TestClient(main.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.engine.dispose()
        cls.temp_dir.cleanup()

    def test_patient_device_session_and_integration_flow(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        schema = self.client.get("/openapi.json")
        self.assertEqual(schema.status_code, 200)
        self.assertIn("/api/v1/observations", schema.json()["paths"])
        self.assertEqual(self.client.get("/api/patients").json(), [])

        patient_response = self.client.post("/api/patients", json={
            "name": "Demo Patient",
            "mrn": "DEMO-001",
            "age": 42,
            "gender": "Other",
            "bed": "Demo-01",
        })
        self.assertEqual(patient_response.status_code, 201)

        upsert_response = self.client.put("/api/v1/patients/DEMO-001", json={
            "name": "Demo Patient Updated",
            "age": 42,
            "bed": "Demo-02",
        })
        self.assertEqual(upsert_response.status_code, 200)
        self.assertEqual(upsert_response.json()["bed"], "Demo-02")

        device_response = self.client.post("/api/devices", json={
            "device_id": "tarang-test-01",
            "mac_address": "AA:BB:CC:DD:EE:01",
            "firmware_version": "test-1.0.0",
        })
        self.assertEqual(device_response.status_code, 201)

        session_response = self.client.post("/api/sessions", json={
            "mrn": "DEMO-001",
            "device_id": "tarang-test-01",
        })
        self.assertEqual(session_response.status_code, 201)
        session_id = session_response.json()["session_id"]

        telemetry_response = self.client.post("/api/telemetry/ingest", json={
            "session_id": session_id,
            "timestamp_ms": 1000,
            "beat_class": 0,
            "confidence": 250,
            "rr_interval_ms": 800,
            "current_hr": 75,
        })
        self.assertEqual(telemetry_response.status_code, 200)

        health_response = self.client.post("/api/health/ingest", json={
            "session_id": session_id,
            "uptime_s": 30,
            "ecg_sqi": 245,
            "ppg_finger_present": True,
            "imu_ok": True,
        })
        self.assertEqual(health_response.status_code, 200)

        latest = self.client.get(f"/api/sessions/{session_id}/telemetry/latest")
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["current_hr"], 75)

        # ── Mode A Event-Driven API Tests ─────────────────────────────────────
        # 1. Periodic Vitals Ingest & Read
        vitals_ingest = self.client.post("/api/vitals", json={
            "device_id": "tarang-test-01",
            "session_id": session_id,
            "heart_rate_bpm": 78,
            "spo2_pct": 99,
        })
        self.assertEqual(vitals_ingest.status_code, 201)

        vitals_latest = self.client.get("/api/vitals/latest", params={"deviceId": "tarang-test-01"})
        self.assertEqual(vitals_latest.status_code, 200)
        self.assertEqual(vitals_latest.json()["heartRateBpm"], 78)
        self.assertEqual(vitals_latest.json()["spo2Pct"], 99)

        # 2. 5-Min Analytics Rollup Ingest & Read
        analytics_ingest = self.client.post("/api/analytics", json={
            "device_id": "tarang-test-01",
            "session_id": session_id,
            "pvc_burden_pct": 0.8,
            "pac_burden_pct": 1.5,
            "sdnn": 48.0,
            "rmssd": 36.0,
            "prr50": 9.2,
            "ai_duty_cycle_pct": 1.5,
            "em2_sleep_pct": 92.5,
        })
        self.assertEqual(analytics_ingest.status_code, 201)

        analytics_latest = self.client.get("/api/analytics/latest", params={"deviceId": "tarang-test-01"})
        self.assertEqual(analytics_latest.status_code, 200)
        self.assertEqual(analytics_latest.json()["em2SleepPct"], 92.5)
        self.assertEqual(analytics_latest.json()["aiDutyCyclePct"], 1.5)

        # 3. Clinical Event + 4s Snippet + Annotations Ingest & Read
        event_ingest = self.client.post("/api/events", json={
            "device_id": "tarang-test-01",
            "session_id": session_id,
            "rhythm_status": 2, # VT
            "pattern_type": "V-Run",
            "confidence": 0.96,
            "sample_rate_hz": 250,
            "waveform": [0.1, 0.2, 1.2, -0.4, 0.0] * 200, # 1000 samples = 4s @ 250Hz
            "annotations": [
                {"offset_ms": 800, "label": "N", "confidence": 0.99},
                {"offset_ms": 1600, "label": "V", "confidence": 0.95},
                {"offset_ms": 2400, "label": "V", "confidence": 0.96},
                {"offset_ms": 3200, "label": "V", "confidence": 0.94},
            ],
        })
        self.assertEqual(event_ingest.status_code, 201)
        event_id = event_ingest.json()["eventId"]

        events_latest = self.client.get("/api/events/latest", params={"deviceId": "tarang-test-01"})
        self.assertEqual(events_latest.status_code, 200)
        self.assertTrue(len(events_latest.json()) >= 1)
        self.assertEqual(events_latest.json()[0]["patternType"], "V-Run")

        snippet_res = self.client.get(f"/api/events/{event_id}/snippet")
        self.assertEqual(snippet_res.status_code, 200)
        self.assertEqual(len(snippet_res.json()["waveform"]), 1000)
        self.assertEqual(len(snippet_res.json()["annotations"]), 4)

        pdf_response = self.client.get(f"/api/events/{event_id}/pdf")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.headers["content-type"], "application/pdf")
        self.assertTrue(pdf_response.content.startswith(b"%PDF-1.4"))
        self.assertGreater(len(pdf_response.content), 1000)

        page_response = self.client.post("/api/clinical-actions/page-physician", json={
            "mrn": "DEMO-001",
            "session_id": session_id,
            "priority": "urgent",
            "reason": "Review ventricular run",
            "requested_by": "Dr. Test",
        })
        self.assertEqual(page_response.status_code, 201)
        self.assertEqual(page_response.json()["status"], "queued")
        self.assertEqual(page_response.json()["actionType"], "page_physician")

        actions_response = self.client.get("/api/clinical-actions", params={"mrn": "DEMO-001"})
        self.assertEqual(actions_response.status_code, 200)
        self.assertEqual(len(actions_response.json()), 1)

        settings_response = self.client.put("/api/settings", json={
            "hrLowThreshold": 55,
            "hrHighThreshold": 115,
            "rrLowThreshold": 9,
            "rrHighThreshold": 25,
            "attendingDoctor": "Dr. Test",
        })
        self.assertEqual(settings_response.status_code, 200)
        self.assertEqual(settings_response.json()["attendingDoctor"], "Dr. Test")
        invalid_settings = self.client.put("/api/settings", json={
            "hrLowThreshold": 130,
            "hrHighThreshold": 100,
        })
        self.assertEqual(invalid_settings.status_code, 422)

        # Stop Session
        stop_response = self.client.post(f"/api/sessions/{session_id}/stop")
        self.assertEqual(stop_response.status_code, 200)
        self.assertEqual(stop_response.json()["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
