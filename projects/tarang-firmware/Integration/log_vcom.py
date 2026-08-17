#!/usr/bin/env python3
"""
TARANG VCOM Logger with Airtable Volunteer Integration
=======================================================
Reads VCOM serial output, prints everything to terminal screen live,
AND saves everything into a timestamped CSV file linked to a volunteer.

Flow:
  1. Prompts for Volunteer ID (e.g. TRG-2026-0001)
  2. Fetches volunteer record from Airtable (falls back to local JSON)
  3. Creates per-volunteer subdirectory under captures/
  4. Logs VCOM data with volunteer metadata embedded in CSV header

Usage:
  python log_vcom.py
  python log_vcom.py --port COM11
  python log_vcom.py --id TRG-2026-0001           # skip interactive prompt
  python log_vcom.py --id TRG-2026-0001 --port COM11
"""

import argparse
import json
import os
import sys
import time
import csv
from datetime import datetime
from pathlib import Path

import serial
import serial.tools.list_ports

# ─── Airtable Configuration ──────────────────────────────────────────────────
# Reads credentials from the portfolio tarang .env file or environment variables.
# These match the keys used in the portfolio site's /api/register route.

AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY", "")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
AIRTABLE_TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME", "Volunteers")

# Path to optional portfolio tarang .env for auto-loading credentials
PORTFOLIO_ENV_PATH = Path(os.environ.get("TARANG_PORTFOLIO_ENV_PATH", str(Path.home() / ".tarang" / ".env")))

# Path to optional local participants.json fallback
LOCAL_PARTICIPANTS_PATH = Path(os.environ.get("TARANG_PARTICIPANTS_PATH", str(Path.home() / ".tarang" / "participants.json")))

# ─── Serial Defaults ─────────────────────────────────────────────────────────

DEFAULT_BAUD = 115200
DEFAULT_PORT = os.environ.get("TARANG_VCOM_PORT", "COM11")

# ─── Output directory: integration_validation/captures/<volunteer_id>/ ────────

CAPTURES_BASE = Path(os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "tarang-dsp", "integration_validation", "captures",
)))


def load_env_file(env_path: Path) -> dict:
    """Parse a .env file and return key-value pairs."""
    env_vars = {}
    if not env_path.exists():
        return env_vars
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip()
    return env_vars


def get_airtable_credentials() -> tuple:
    """
    Resolve Airtable credentials from environment variables or .env files.
    Searches current working directory, script directory, and repository root.
    Returns (api_key, base_id, table_name).
    """
    api_key = AIRTABLE_API_KEY
    base_id = AIRTABLE_BASE_ID
    table_name = AIRTABLE_TABLE_NAME

    # If not set in env, search relative directories for .env and .env.local
    if not api_key or not base_id:
        search_dirs = [Path.cwd()]
        # Add script directory and all parent directories up to 5 levels (reaching repo root)
        curr = Path(__file__).resolve().parent
        for _ in range(5):
            search_dirs.append(curr)
            if curr.parent == curr:
                break
            curr = curr.parent

        candidate_files = []
        for d in search_dirs:
            candidate_files.append(d / ".env")
            candidate_files.append(d / ".env.local")
        candidate_files.append(PORTFOLIO_ENV_PATH)

        for env_candidate in candidate_files:
            if env_candidate.exists():
                env_vars = load_env_file(env_candidate)
                api_key = api_key or env_vars.get("AIRTABLE_API_KEY", "") or env_vars.get("AIRTABLE_PAT", "") or env_vars.get("NEXT_PUBLIC_AIRTABLE_API_KEY", "")
                base_id = base_id or env_vars.get("AIRTABLE_BASE_ID", "") or env_vars.get("NEXT_PUBLIC_AIRTABLE_BASE_ID", "")
                table_name = table_name or env_vars.get("AIRTABLE_TABLE_NAME", "") or env_vars.get("NEXT_PUBLIC_AIRTABLE_TABLE_NAME", "Volunteers")
                if api_key and base_id:
                    break

    return api_key, base_id, table_name


def fetch_volunteer_from_airtable(volunteer_id: str) -> dict | None:
    """
    Fetch a volunteer record from Airtable by Volunteer ID.
    Returns a dict with volunteer info or None if not found / error.
    """
    api_key, base_id, table_name = get_airtable_credentials()

    if not api_key or not base_id:
        print("[AIRTABLE] No API key or Base ID configured. Skipping Airtable lookup.")
        return None

    try:
        import urllib.request
        import urllib.parse
        import urllib.error

        filter_formula = urllib.parse.quote(f"{{Volunteer ID}}='{volunteer_id}'")
        url = (
            f"https://api.airtable.com/v0/{base_id}"
            f"/{urllib.parse.quote(table_name)}"
            f"?filterByFormula={filter_formula}"
        )

        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        records = data.get("records", [])
        if not records:
            print(f"[AIRTABLE] Volunteer '{volunteer_id}' not found in Airtable.")
            return None

        record = records[0]
        record_id = record.get("id", "")  # Airtable record ID for PATCH updates
        fields = record.get("fields", {})
        # Map Airtable field names to a normalized dict
        volunteer = {
            "volunteerId": fields.get("Volunteer ID", volunteer_id),
            "name": fields.get("Name", "Unknown"),
            "email": fields.get("Email", ""),
            "phone": fields.get("Phone", ""),
            "age": fields.get("Age", ""),
            "gender": fields.get("Gender", ""),
            "hasCardiacCondition": fields.get("Has Condition", "unknown"),
            "conditionDetails": fields.get("Condition Details", ""),
            "status": fields.get("Status", "UNKNOWN"),
            "_airtable_record_id": record_id,
        }
        print(f"[AIRTABLE] [OK] Found volunteer: {volunteer['name']} ({volunteer['volunteerId']})")
        return volunteer

    except urllib.error.HTTPError as e:
        print(f"[AIRTABLE] HTTP error {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"[AIRTABLE] Connection error: {e}")
        return None


def fetch_volunteer_from_local(volunteer_id: str) -> dict | None:
    """
    Fallback: search local participants.json for a matching volunteer.
    """
    if not LOCAL_PARTICIPANTS_PATH.exists():
        print(f"[LOCAL] participants.json not found at {LOCAL_PARTICIPANTS_PATH}")
        return None

    try:
        with open(LOCAL_PARTICIPANTS_PATH, "r", encoding="utf-8") as f:
            participants = json.load(f)

        for p in participants:
            if p.get("volunteerId", "").lower() == volunteer_id.lower():
                volunteer = {
                    "volunteerId": p.get("volunteerId", volunteer_id),
                    "name": p.get("participantInfo", {}).get("name", "Unknown"),
                    "email": p.get("participantInfo", {}).get("email", ""),
                    "phone": p.get("participantInfo", {}).get("phone", ""),
                    "age": p.get("participantInfo", {}).get("age", ""),
                    "gender": p.get("participantInfo", {}).get("gender", ""),
                    "hasCardiacCondition": p.get("healthInfo", {}).get("hasCardiacCondition", "unknown"),
                    "conditionDetails": p.get("healthInfo", {}).get("conditionDetails", ""),
                    "status": p.get("status", "UNKNOWN"),
                }
                print(f"[LOCAL] [OK] Found volunteer: {volunteer['name']} ({volunteer['volunteerId']})")
                return volunteer

        print(f"[LOCAL] Volunteer '{volunteer_id}' not found in local participants.json")
        return None

    except Exception as e:
        print(f"[LOCAL] Error reading participants.json: {e}")
        return None


def update_airtable_status(volunteer: dict, csv_path: str, record_count: int, duration_sec: float):
    """
    Update the volunteer's Airtable record status to DATA_CAPTURED
    after a VCOM capture session ends (Ctrl+C).
    """
    record_id = volunteer.get("_airtable_record_id", "")
    if not record_id:
        print("[AIRTABLE] No record ID stored -- skipping status update.")
        return False

    api_key, base_id, table_name = get_airtable_credentials()
    if not api_key or not base_id:
        print("[AIRTABLE] No credentials -- skipping status update.")
        return False

    try:
        import urllib.request
        import urllib.parse

        url = (
            f"https://api.airtable.com/v0/{base_id}"
            f"/{urllib.parse.quote(table_name)}/{record_id}"
        )

        payload = json.dumps({
            "typecast": True,
            "fields": {
                "Status": "DATA_CAPTURED",
            },
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="PATCH")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                print(f"[AIRTABLE] [OK] Status updated to DATA_CAPTURED for {volunteer['volunteerId']}")
                return True
            else:
                print(f"[AIRTABLE] Unexpected response status: {resp.status}")
                return False

    except Exception as e:
        print(f"[AIRTABLE] Failed to update status: {e}")
        return False


def update_local_status(volunteer: dict, csv_path: str, record_count: int, duration_sec: float):
    """
    Update the volunteer's status in local participants.json after capture.
    """
    if not LOCAL_PARTICIPANTS_PATH.exists():
        return

    try:
        with open(LOCAL_PARTICIPANTS_PATH, "r", encoding="utf-8") as f:
            participants = json.load(f)

        for p in participants:
            if p.get("volunteerId", "").lower() == volunteer["volunteerId"].lower():
                p["status"] = "DATA_CAPTURED"
                p["lastCapture"] = {
                    "file": os.path.basename(csv_path),
                    "records": record_count,
                    "durationSec": round(duration_sec, 1),
                    "timestamp": datetime.now().isoformat(),
                }
                break

        with open(LOCAL_PARTICIPANTS_PATH, "w", encoding="utf-8") as f:
            json.dump(participants, f, indent=2)

        print(f"[LOCAL] Status updated to DATA_CAPTURED in participants.json")
    except Exception as e:
        print(f"[LOCAL] Failed to update local status: {e}")


def fetch_volunteer(volunteer_id: str) -> dict | None:
    """
    Try Airtable first, then fall back to local participants.json.
    """
    # Try Airtable
    volunteer = fetch_volunteer_from_airtable(volunteer_id)
    if volunteer:
        return volunteer

    # Fallback to local JSON
    print("[INFO] Falling back to local participants.json ...")
    return fetch_volunteer_from_local(volunteer_id)


def find_serial_port():
    """Auto-detect Silicon Labs VCOM port, fall back to DEFAULT_PORT."""
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        mfg  = (p.manufacturer or "").lower()
        if any(kw in desc for kw in ["silicon labs", "jlink", "efr32", "vcom"]):
            print(f"[AUTO] Found TARANG board on {p.device}: {p.description}")
            return p.device
        if "silicon" in mfg:
            print(f"[AUTO] Found TARANG board on {p.device}: {p.description}")
            return p.device
    print(f"[AUTO] No board auto-detected, using {DEFAULT_PORT}")
    return DEFAULT_PORT


def prompt_volunteer_id() -> str:
    """Interactive prompt for Volunteer ID with input validation."""
    print("\n" + "=" * 60)
    print("  TARANG — VOLUNTEER IDENTIFICATION")
    print("=" * 60)
    print("  Enter the Volunteer ID assigned during registration.")
    print("  Format: TRG-2026-XXXX  (e.g. TRG-2026-0001)")
    print("-" * 60)

    while True:
        vid = input("  Volunteer ID > ").strip()
        if not vid:
            print("  [!] Volunteer ID cannot be empty. Try again.")
            continue
        # Accept any non-empty string — flexible for edge cases
        return vid.upper()


def print_volunteer_card(v: dict):
    """Pretty-print the volunteer record."""
    print("\n" + "-" * 60)
    print("  VOLUNTEER RECORD")
    print("-" * 60)
    print(f"  ID         : {v.get('volunteerId', 'N/A')}")
    print(f"  Name       : {v.get('name', 'N/A')}")
    print(f"  Email      : {v.get('email', 'N/A')}")
    print(f"  Phone      : {v.get('phone', 'N/A')}")
    print(f"  Age/Gender : {v.get('age', 'N/A')} / {v.get('gender', 'N/A')}")
    print(f"  Cardiac    : {v.get('hasCardiacCondition', 'N/A')} ({v.get('conditionDetails', '') or 'None'})")
    print(f"  Status     : {v.get('status', 'N/A')}")
    print("-" * 60)


def write_csv_header(f, writer, volunteer: dict, port: str, baud: int):
    """Write volunteer metadata as comment lines + CSV column header."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Metadata block as CSV comments
    f.write(f"# TARANG VCOM Capture\n")
    f.write(f"# Date: {ts}\n")
    f.write(f"# Port: {port} @ {baud} baud\n")
    f.write(f"# Volunteer ID: {volunteer.get('volunteerId', 'UNKNOWN')}\n")
    f.write(f"# Name: {volunteer.get('name', 'N/A')}\n")
    f.write(f"# Email: {volunteer.get('email', 'N/A')}\n")
    f.write(f"# Phone: {volunteer.get('phone', 'N/A')}\n")
    f.write(f"# Age: {volunteer.get('age', 'N/A')}\n")
    f.write(f"# Gender: {volunteer.get('gender', 'N/A')}\n")
    f.write(f"# Cardiac Condition: {volunteer.get('hasCardiacCondition', 'N/A')}\n")
    f.write(f"# Condition Details: {volunteer.get('conditionDetails', '') or 'None'}\n")
    f.write(f"# Status: {volunteer.get('status', 'N/A')}\n")
    f.write(f"#\n")

    # Column header row
    writer.writerow(["unix_timestamp", "elapsed_sec", "raw_line"])
    f.flush()


def build_csv_path(volunteer_id: str) -> Path:
    """
    Build output CSV path:
      captures/<VOLUNTEER_ID>/<VOLUNTEER_ID>_<YYYYMMDD_HHMMSS>.csv
    """
    vol_dir = CAPTURES_BASE / volunteer_id
    vol_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_name = f"{volunteer_id}_{ts}.csv"
    return vol_dir / csv_name


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port", help="Serial port, for example COM11")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--id", dest="volunteer_id",
                        help="Volunteer ID (e.g. TRG-2026-0001). If omitted, prompts interactively.")
    parser.add_argument("--output", type=os.path.abspath,
                        help="Override output CSV path (default: auto-generated per volunteer)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every high-rate telemetry record (lines starting with @)")
    parser.add_argument("--skip-lookup", action="store_true",
                        help="Skip Airtable/local lookup (use volunteer ID as-is)")
    args = parser.parse_args()

    # ── Step 1: Get Volunteer ID ──
    volunteer_id = args.volunteer_id or prompt_volunteer_id()

    # ── Step 2: Fetch volunteer info ──
    volunteer = None
    if not args.skip_lookup:
        volunteer = fetch_volunteer(volunteer_id)

    if volunteer is None:
        print(f"\n[WARN] Could not find volunteer record for '{volunteer_id}'.")
        proceed = input("  Continue with ID only? (y/N) > ").strip().lower()
        if proceed not in ("y", "yes"):
            print("[EXIT] Aborted.")
            sys.exit(0)
        # Create a minimal volunteer dict
        volunteer = {
            "volunteerId": volunteer_id,
            "name": "Unknown",
            "email": "",
            "phone": "",
            "age": "",
            "gender": "",
            "hasCardiacCondition": "unknown",
            "conditionDetails": "",
            "status": "UNVERIFIED",
        }
    else:
        # Ensure the ID in the record matches what we have
        volunteer["volunteerId"] = volunteer.get("volunteerId", volunteer_id)

    print_volunteer_card(volunteer)

    # ── Step 3: Setup serial port ──
    port = args.port or find_serial_port()
    baud = args.baud

    # ── Step 4: Setup CSV output ──
    csv_path = Path(args.output) if args.output else build_csv_path(volunteer["volunteerId"])
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    # Also write a volunteer_info.json sidecar in the volunteer's directory
    info_path = csv_path.parent / "volunteer_info.json"
    if not info_path.exists() or True:  # Always update with latest fetch
        with open(info_path, "w", encoding="utf-8") as jf:
            json.dump({
                **volunteer,
                "lastCapture": datetime.now().isoformat(),
                "capturePort": port,
                "captureBaud": baud,
            }, jf, indent=2)

    print("\n" + "=" * 60)
    print("  TARANG VCOM LOGGER — VOLUNTEER SESSION")
    print(f"  Volunteer : {volunteer['volunteerId']} ({volunteer['name']})")
    print(f"  Port      : {port} @ {baud} baud")
    print(f"  CSV       : {csv_path}")
    print("=" * 60)
    print("  Press Ctrl+C to stop logging.\n")

    # ── Step 5: Open serial port ──
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as e:
        print(f"[ERROR] Could not open {port}: {e}")
        print("[TIP] Close Simplicity Studio Serial Console or other terminal programs accessing the port.")
    # ── Step 6: Capture loop ──
    t0 = time.time()
    last_flush = t0
    last_ui_update = t0
    record_count = 0

    # Live dashboard tracking state
    ecg_samples = 0
    ecg_overruns = 0
    ecg_fs = 250.0
    last_ecg_sample_time = t0
    last_ecg_sample_val = 0
    
    ppg_status = "STARTING"
    ppg_samples = 0
    ppg_red = 0
    ppg_ir = 0
    
    imu_status = "STARTING"
    imu_samples = 0
    imu_ax, imu_ay, imu_az = 0, 0, 0
    
    ai_tier0 = 0
    ai_tier1 = 0
    ai_tier2 = 0
    class_n = 0
    class_s = 0
    class_v = 0
    last_ai_event = "None (listening for beats...)"

    import re

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        write_csv_header(f, writer, volunteer, port, baud)

        try:
            while True:
                line_bytes = ser.readline()
                if not line_bytes:
                    continue
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue

                now = time.time()
                elapsed = now - t0
                record_count += 1

                # Parse ECG status
                m_ecg = re.search(r'\[ECG\]\s+halves=\d+\s+total_samples=(\d+)\s+overruns=(\d+)', line)
                if m_ecg:
                    cur_s = int(m_ecg.group(1))
                    dt_s = now - last_ecg_sample_time
                    if dt_s > 0.5 and last_ecg_sample_val > 0:
                        ecg_fs = (cur_s - last_ecg_sample_val) / dt_s
                    last_ecg_sample_time = now
                    last_ecg_sample_val = cur_s
                    ecg_samples = cur_s
                    ecg_overruns = int(m_ecg.group(2))

                # Parse PPG status
                m_ppg = re.search(r'\[PPG\]\s+samples=(\d+)\s+RED=(\d+)\s+IR=(\d+)\s+sensor=(\w+)', line)
                if m_ppg:
                    ppg_samples = int(m_ppg.group(1))
                    ppg_red = int(m_ppg.group(2))
                    ppg_ir = int(m_ppg.group(3))
                    ppg_status = m_ppg.group(4)

                # Parse IMU status
                m_imu = re.search(r'\[IMU\]\s+samples=(\d+)\s+interrupts=\d+\s+sensor=(\w+)', line)
                if m_imu:
                    imu_samples = int(m_imu.group(1))
                    imu_status = m_imu.group(2)

                m_accel = re.search(r'\[IMU\]\s+accel:\s+ax=([-\d]+)\s+ay=([-\d]+)\s+az=([-\d]+)', line)
                if m_accel:
                    imu_ax = int(m_accel.group(1))
                    imu_ay = int(m_accel.group(2))
                    imu_az = int(m_accel.group(3))

                # Parse AI Tier events
                if "[AI] TIER1" in line:
                    ai_tier1 += 1
                    last_ai_event = line.strip()
                elif "[AI] TIER2" in line:
                    ai_tier2 += 1
                    last_ai_event = line.strip()

                m_ai_diag1 = re.search(r'\[AI\]\s+tier0_evals=(\d+)\s+tier1_fires=(\d+)\s+tier2_fires=(\d+)', line)
                if m_ai_diag1:
                    ai_tier0 = int(m_ai_diag1.group(1))
                    ai_tier1 = int(m_ai_diag1.group(2))
                    ai_tier2 = int(m_ai_diag1.group(3))

                m_ai_diag2 = re.search(r'\[AI\]\s+class_n=(\d+)\s+class_s=(\d+)\s+class_v=(\d+)', line)
                if m_ai_diag2:
                    class_n = int(m_ai_diag2.group(1))
                    class_s = int(m_ai_diag2.group(2))
                    class_v = int(m_ai_diag2.group(3))

                # Write every raw line to CSV
                writer.writerow([f"{now:.3f}", f"{elapsed:.3f}", line])

                if args.verbose:
                    print(line)
                else:
                    # In-place consolidated ANSI dashboard update once every 0.5s
                    if now - last_ui_update >= 0.5:
                        last_ui_update = now
                        sys.stdout.write("\033[2J\033[H") # Clear screen & move to top
                        sys.stdout.write("========================================================================\n")
                        sys.stdout.write(f"  TARANG LIVE CLINICAL CONSOLE — Volunteer: {volunteer['volunteerId']} ({volunteer.get('name', 'N/A')})\n")
                        sys.stdout.write(f"  Session: {elapsed:.1f}s | Records: {record_count} | Port: {port} @ {baud}\n")
                        sys.stdout.write("------------------------------------------------------------------------\n")
                        sys.stdout.write(f"  ECG  : Rate: {ecg_fs:.1f} Hz | Overruns: {ecg_overruns} | Samples: {ecg_samples}\n")
                        sys.stdout.write(f"  PPG  : Status: {ppg_status:<4} | Samples: {ppg_samples:<6} | RED: {ppg_red:<6} | IR: {ppg_ir}\n")
                        sys.stdout.write(f"  IMU  : Status: {imu_status:<4} | Samples: {imu_samples:<6} | Accel(g): [{imu_ax/16384.0:+.2f}, {imu_ay/16384.0:+.2f}, {imu_az/16384.0:+.2f}]\n")
                        sys.stdout.write("------------------------------------------------------------------------\n")
                        sys.stdout.write(f"  AI   : Tier-0: {ai_tier0:<5} evals | Tier-1 Gate: {ai_tier1:<3} fires | Tier-2 SV: {ai_tier2} fires\n")
                        sys.stdout.write(f"  Class: Normal (N): {class_n:<4} | S-Ectopic (S): {class_s:<3} | V-Ectopic (V): {class_v}\n")
                        sys.stdout.write("------------------------------------------------------------------------\n")
                        sys.stdout.write(f"  Event: {last_ai_event}\n")
                        sys.stdout.write("========================================================================\n")
                        sys.stdout.write("  [Press Ctrl+C to stop logging and save session]\n")
                        sys.stdout.flush()

                if now - last_flush >= 1.0:
                    f.flush()
                    last_flush = now

        except KeyboardInterrupt:
            print("\n[LOG] Stopped logging.")
        finally:
            ser.close()
            duration = time.time() - t0
            print(f"[LOG] Volunteer  : {volunteer['volunteerId']}")
            print(f"[LOG] Records    : {record_count}")
            print(f"[LOG] Duration   : {duration:.1f}s")
            print(f"[LOG] File saved : {csv_path}")

            # ── Step 7: Update Airtable & local status ──
            if record_count > 0:
                print("\n[SYNC] Updating volunteer status to DATA_CAPTURED ...")
                update_airtable_status(volunteer, str(csv_path), record_count, duration)
                update_local_status(volunteer, str(csv_path), record_count, duration)
            else:
                print("\n[SYNC] No records captured, skipping status update.")


if __name__ == "__main__":
    main()
