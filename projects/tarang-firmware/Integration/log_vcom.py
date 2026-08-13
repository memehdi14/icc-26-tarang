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

# Path to the portfolio tarang .env for auto-loading credentials
PORTFOLIO_ENV_PATH = Path(r"C:\MMDPublic\Freelance\portfolio\tarang\.env")

# Path to local participants.json fallback
LOCAL_PARTICIPANTS_PATH = Path(r"C:\MMDPublic\Freelance\portfolio\tarang\data\participants.json")

# ─── Serial Defaults ─────────────────────────────────────────────────────────

DEFAULT_BAUD = 115200
DEFAULT_PORT = "COM11"

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
    Resolve Airtable credentials from environment variables or the portfolio .env file.
    Returns (api_key, base_id, table_name).
    """
    api_key = AIRTABLE_API_KEY
    base_id = AIRTABLE_BASE_ID
    table_name = AIRTABLE_TABLE_NAME

    # If not set in env, try loading from portfolio .env
    if not api_key or not base_id:
        env_vars = load_env_file(PORTFOLIO_ENV_PATH)
        api_key = api_key or env_vars.get("AIRTABLE_API_KEY", "")
        base_id = base_id or env_vars.get("AIRTABLE_BASE_ID", "")
        table_name = table_name or env_vars.get("AIRTABLE_TABLE_NAME", "Volunteers")

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
            f"/{urllib.parse.quote(table_name)}"
        )

        ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        csv_basename = os.path.basename(csv_path)

        payload = json.dumps({
            "typecast": True,
            "records": [{
                "id": record_id,
                "fields": {
                    "Status": "DATA_CAPTURED",
                    "Last Capture": f"{csv_basename} | {record_count} records | {duration_sec:.1f}s | {ts_now}",
                },
            }],
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
        sys.exit(1)

    # ── Step 6: Capture loop ──
    t0 = time.time()
    last_flush = t0
    record_count = 0

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

                if args.verbose or not line.startswith("@"):
                    print(line)

                writer.writerow([f"{now:.3f}", f"{elapsed:.3f}", line])
                if now - last_flush >= 1.0:
                    f.flush()
                    if not args.verbose:
                        print(f"[CAPTURE] {volunteer['volunteerId']} | {record_count} records, {elapsed:.1f}s")
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
