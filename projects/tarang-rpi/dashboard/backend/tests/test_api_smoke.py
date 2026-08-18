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
        self.assertEqual(self.client.get("/api/patients/884219").status_code, 200)

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

        observations = self.client.get(
            "/api/v1/observations", params={"sessionId": session_id}
        )
        self.assertEqual(observations.status_code, 200)
        self.assertEqual(observations.json()["count"], 1)

        summary = self.client.get(f"/api/v1/sessions/{session_id}/summary")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["latestObservation"]["value"]["heartRateBpm"], 75)

        stop_response = self.client.post(f"/api/sessions/{session_id}/stop")
        self.assertEqual(stop_response.status_code, 200)
        self.assertEqual(stop_response.json()["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
