#!/usr/bin/env python3
"""
TARANG VCOM Logger with Airtable & Local Volunteer Integration
===============================================================
Reads VCOM serial output, displays real-time telemetry live on screen,
and logs every record into a structured, timestamped CSV file linked to a volunteer.

Flow:
  1. Prompts for Volunteer ID (e.g. TRG-2026-0005, KD) or uses --id
  2. Fetches volunteer record from Airtable (fallback: local participants.json / pseudonymous)
  3. Creates per-volunteer subdirectory under captures/<volunteer_id>/
  4. Streams & logs all VCOM data live at 115200 baud with embedded metadata
  5. On Ctrl+C (or --duration), automatically syncs status to DATA_CAPTURED in Airtable/local JSON
  6. Automatically runs DSP validation plots (via plot_tarang.py)

Usage:
  python log_vcom.py
  python log_vcom.py --id TRG-2026-0005
  python log_vcom.py --id KD --baud 115200 --port COM11
  python log_vcom.py --verbose
"""

import argparse
import csv
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime

import serial
import serial.tools.list_ports

# Configuration & Known Paths
DEFAULT_BAUD = 115200
DEFAULT_PORT = "COM11"

PRIMARY_PORTFOLIO_ENV = Path(r"C:\MMDPublic\Freelance\portfolio\tarang\.env")
PRIMARY_PARTICIPANTS_JSON = Path(r"C:\MMDPublic\Freelance\portfolio\tarang\data\participants.json")

CAPTURES_BASE = Path(os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "tarang-dsp", "integration_validation", "captures",
)))
INTEGRATION_VALIDATION_DIR = CAPTURES_BASE.parent
PLOTS_BASE = INTEGRATION_VALIDATION_DIR / "plots"
PLOT_SCRIPT = INTEGRATION_VALIDATION_DIR / "plot_tarang.py"

def load_env_file(env_path: Path) -> dict:
    env_vars = {}
    if not env_path.exists():
        return env_vars
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    val = value.strip()
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    env_vars[key.strip()] = val
    except Exception:
        pass
    return env_vars

def get_airtable_credentials() -> tuple[str, str, str]:
    api_key = os.environ.get("AIRTABLE_API_KEY", "") or os.environ.get("AIRTABLE_PAT", "")
    base_id = os.environ.get("AIRTABLE_BASE_ID", "")
    table_name = os.environ.get("AIRTABLE_TABLE_NAME", "Volunteers")

    candidate_files = [
        PRIMARY_PORTFOLIO_ENV,
        Path.cwd() / ".env",
        Path.cwd() / ".env.local",
        Path(__file__).resolve().parent / ".env",
        Path.home() / ".tarang" / ".env",
    ]
    curr = Path(__file__).resolve().parent
    for _ in range(5):
        candidate_files.append(curr / ".env")
        candidate_files.append(curr / ".env.local")
        if curr.parent == curr:
            break
        curr = curr.parent

    for env_candidate in candidate_files:
        if (not api_key or not base_id) and env_candidate.exists():
            env_vars = load_env_file(env_candidate)
            api_key = api_key or env_vars.get("AIRTABLE_API_KEY", "") or env_vars.get("AIRTABLE_PAT", "") or env_vars.get("NEXT_PUBLIC_AIRTABLE_API_KEY", "")
            base_id = base_id or env_vars.get("AIRTABLE_BASE_ID", "") or env_vars.get("NEXT_PUBLIC_AIRTABLE_BASE_ID", "")
            table_name = env_vars.get("AIRTABLE_TABLE_NAME", "") or env_vars.get("NEXT_PUBLIC_AIRTABLE_TABLE_NAME", "") or table_name

    return api_key, base_id, table_name

def fetch_volunteer_from_airtable(volunteer_id: str) -> dict | None:
    api_key, base_id, table_name = get_airtable_credentials()
    if not api_key or not base_id:
        return None
    try:
        import urllib.parse
        import urllib.request
        filter_formula = urllib.parse.quote(f"OR(LOWER({{Volunteer ID}})='{volunteer_id.lower()}', {{Volunteer ID}}='{volunteer_id}')")
        url = f"https://api.airtable.com/v0/{base_id}/{urllib.parse.quote(table_name)}?filterByFormula={filter_formula}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        records = data.get("records", [])
        if not records:
            return None
        record = records[0]
        fields = record.get("fields", {})
        volunteer = {
            "volunteerId": fields.get("Volunteer ID", volunteer_id),
            "name": fields.get("Name", "Unknown"),
            "email": fields.get("Email", ""),
            "phone": fields.get("Phone", ""),
            "age": str(fields.get("Age", "")),
            "gender": fields.get("Gender", ""),
            "hasCardiacCondition": fields.get("Has Condition", "unknown"),
            "conditionDetails": fields.get("Condition Details", ""),
            "status": fields.get("Status", "REGISTERED"),
            "_airtable_record_id": record.get("id", ""),
        }
        print(f"[AIRTABLE] [OK] Found volunteer: {volunteer['name']} ({volunteer['volunteerId']})")
        return volunteer
    except Exception as e:
        print(f"[AIRTABLE] Lookup notice: {e}")
        return None

def fetch_volunteer_from_local(volunteer_id: str) -> dict | None:
    candidate_paths = [
        PRIMARY_PARTICIPANTS_JSON,
        Path.home() / ".tarang" / "participants.json",
        INTEGRATION_VALIDATION_DIR / "participants.json",
    ]
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                participants = json.load(f)
            for p in participants:
                vid = p.get("volunteerId", "")
                pinfo = p.get("participantInfo", {})
                hinfo = p.get("healthInfo", {})
                if vid.lower() == volunteer_id.lower() or pinfo.get("name", "").lower() == volunteer_id.lower():
                    volunteer = {
                        "volunteerId": vid or volunteer_id,
                        "name": pinfo.get("name", "Unknown"),
                        "email": pinfo.get("email", ""),
                        "phone": pinfo.get("phone", ""),
                        "age": str(pinfo.get("age", "")),
                        "gender": pinfo.get("gender", ""),
                        "hasCardiacCondition": hinfo.get("hasCardiacCondition", "unknown"),
                        "conditionDetails": hinfo.get("conditionDetails", ""),
                        "status": p.get("status", "REGISTERED"),
                    }
                    print(f"[LOCAL] [OK] Found volunteer: {volunteer['name']} ({volunteer['volunteerId']}) in {path.name}")
                    return volunteer
        except Exception:
            pass
    return None

def fetch_volunteer(volunteer_id: str) -> dict:
    volunteer = fetch_volunteer_from_airtable(volunteer_id)
    if volunteer:
        return volunteer
    volunteer = fetch_volunteer_from_local(volunteer_id)
    if volunteer:
        return volunteer
    print(f"[INFO] Volunteer '{volunteer_id}' not found in database. Using as pseudonymous ID.")
    return {
        "volunteerId": volunteer_id,
        "name": volunteer_id,
        "email": "",
        "phone": "",
        "age": "",
        "gender": "",
        "hasCardiacCondition": "unknown",
        "conditionDetails": "None",
        "status": "UNVERIFIED",
    }

def update_airtable_status(volunteer: dict, csv_path: str, record_count: int, duration_sec: float) -> bool:
    record_id = volunteer.get("_airtable_record_id", "")
    api_key, base_id, table_name = get_airtable_credentials()
    if not record_id or not api_key or not base_id:
        return False
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.airtable.com/v0/{base_id}/{urllib.parse.quote(table_name)}/{record_id}"
        ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        csv_basename = os.path.basename(csv_path)
        payload = json.dumps({
            "typecast": True,
            "fields": {
                "Status": "DATA_CAPTURED",
                "Last Capture": f"{csv_basename} | {record_count} records | {duration_sec:.1f}s | {ts_now}",
            },
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="PATCH", headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201):
                print(f"[AIRTABLE] [OK] Status synced to DATA_CAPTURED for {volunteer['volunteerId']}")
                return True
    except Exception as e:
        print(f"[AIRTABLE] Sync note: {e}")
    return False

def update_local_status(volunteer: dict, csv_path: str, record_count: int, duration_sec: float):
    target_files = [PRIMARY_PARTICIPANTS_JSON, Path.home() / ".tarang" / "participants.json"]
    for path in target_files:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                participants = json.load(f)
            found = False
            for p in participants:
                if p.get("volunteerId", "").lower() == volunteer["volunteerId"].lower():
                    p["status"] = "DATA_CAPTURED"
                    p["lastCapture"] = {
                        "file": os.path.basename(csv_path),
                        "records": record_count,
                        "durationSec": round(duration_sec, 1),
                        "timestamp": datetime.now().isoformat(),
                    }
                    found = True
                    break
            if found:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(participants, f, indent=2)
                print(f"[LOCAL] [OK] Status synced to DATA_CAPTURED in {path.name}")
        except Exception as e:
            print(f"[LOCAL] Local update note: {e}")

def find_serial_port() -> str:
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        mfg = (p.manufacturer or "").lower()
        if p.vid == 0x1366 or "segger" in desc or "j-link" in desc or "jlink" in desc:
            print(f"[AUTO] Found SEGGER/J-Link VCOM on {p.device}: {p.description}")
            return p.device
        if any(kw in desc for kw in ["silicon labs", "efr32", "vcom", "usb serial"]):
            print(f"[AUTO] Found TARANG serial port on {p.device}: {p.description}")
            return p.device
        if "silicon" in mfg:
            print(f"[AUTO] Found Silicon Labs device on {p.device}: {p.description}")
            return p.device
    if ports:
        print(f"[AUTO] Using default available port: {ports[0].device} ({ports[0].description})")
        return ports[0].device
    return DEFAULT_PORT

def prompt_volunteer_id() -> str:
    print("\n" + "=" * 60)
    print("  TARANG - VOLUNTEER IDENTIFICATION")
    print("=" * 60)
    print("  Enter Volunteer ID (e.g. TRG-2026-0005, KD, etc.)")
    print("-" * 60)
    while True:
        try:
            vid = input("  Volunteer ID > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession setup cancelled.")
            sys.exit(0)
        if not vid:
            print("  [!] Volunteer ID cannot be empty. Try again.")
            continue
        return vid

def print_volunteer_card(v: dict):
    print("\n" + "-" * 60)
    print("  VOLUNTEER RECORD")
    print("-" * 60)
    print(f"  ID         : {v.get('volunteerId', 'N/A')}")
    print(f"  Name       : {v.get('name', 'N/A')}")
    print(f"  Age/Gender : {v.get('age', 'N/A')} / {v.get('gender', 'N/A')}")
    print(f"  Cardiac    : {v.get('hasCardiacCondition', 'N/A')} ({v.get('conditionDetails', '') or 'None'})")
    print(f"  Status     : {v.get('status', 'N/A')}")
    print("-" * 60)

def write_csv_header(f, writer, volunteer: dict, port: str, baud: int):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f.write("# TARANG VCOM Capture\n")
    f.write(f"# Date: {ts}\n")
    f.write(f"# Port: {port} @ {baud} baud\n")
    f.write(f"# Volunteer ID: {volunteer.get('volunteerId', 'UNKNOWN')}\n")
    f.write(f"# Name: {volunteer.get('name', 'N/A')}\n")
    f.write(f"# Age: {volunteer.get('age', 'N/A')}\n")
    f.write(f"# Gender: {volunteer.get('gender', 'N/A')}\n")
    f.write(f"# Cardiac Condition: {volunteer.get('hasCardiacCondition', 'N/A')}\n")
    f.write(f"# Condition Details: {volunteer.get('conditionDetails', '') or 'None'}\n")
    f.write(f"# Status: {volunteer.get('status', 'N/A')}\n")
    f.write("#\n")
    writer.writerow(["unix_timestamp", "elapsed_sec", "raw_line"])
    f.flush()

def build_csv_path(volunteer_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", volunteer_id.strip()) or "VOLUNTEER"
    vol_dir = CAPTURES_BASE / safe_id
    vol_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return vol_dir / f"{safe_id}_{ts}.csv"

def generate_plots(csv_path: Path, volunteer_id: str):
    if not PLOT_SCRIPT.exists():
        return
    try:
        output_dir = PLOTS_BASE / volunteer_id / csv_path.stem
        command = [
            sys.executable,
            str(PLOT_SCRIPT),
            str(csv_path),
            "--output-dir",
            str(output_dir),
            "--no-open",
        ]
        print(f"\n[PLOT] Generating validation plots in {output_dir} ...")
        import subprocess
        subprocess.run(command, check=False, timeout=25)
    except Exception as e:
        print(f"[PLOT] Note: {e}")

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port", help="Serial port, for example COM11")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD,
                        help=f"Baud rate (default: {DEFAULT_BAUD})")
    parser.add_argument("--id", "--volunteer-id", dest="volunteer_id",
                        help="Volunteer ID (e.g. TRG-2026-0005, KD). If omitted, prompts interactively.")
    parser.add_argument("--output", type=os.path.abspath,
                        help="Override output CSV path (default: auto-generated per volunteer)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every single raw telemetry record to the console")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Capture duration in seconds; default 0 runs until Ctrl+C")
    parser.add_argument("--no-plot", action="store_true",
                        help="Skip automatic DSP plot generation after capture")
    args = parser.parse_args()

    # Step 1: Volunteer Identification & Lookup
    volunteer_id = args.volunteer_id or prompt_volunteer_id()
    volunteer = fetch_volunteer(volunteer_id)
    print_volunteer_card(volunteer)

    # Step 2: Setup serial port & paths
    port = args.port or find_serial_port()
    baud = args.baud
    csv_path = Path(args.output) if args.output else build_csv_path(volunteer["volunteerId"])
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    # Save volunteer_info.json sidecar
    info_path = csv_path.parent / "volunteer_info.json"
    try:
        with open(info_path, "w", encoding="utf-8") as jf:
            json.dump({
                **volunteer,
                "lastCapture": datetime.now().isoformat(),
                "capturePort": port,
                "captureBaud": baud,
            }, jf, indent=2)
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("  TARANG VCOM LOGGER - VOLUNTEER SESSION")
    print(f"  Volunteer : {volunteer['volunteerId']} ({volunteer['name']})")
    print(f"  Port      : {port} @ {baud} baud")
    print(f"  CSV       : {csv_path}")
    print("=" * 60)
    print("  Ready to stream. Press board RESET button if starting a new session.")
    print("  Press Ctrl+C at any time to finish and save session.\n")

    # Step 3: Open serial port
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
        ser.dtr = True
        ser.rts = True
        ser.reset_input_buffer()
    except serial.SerialException as e:
        print(f"[ERROR] Could not open {port}: {e}")
        print("[TIP] Close Simplicity Studio Serial Console or other serial tools accessing the port.")
        sys.exit(1)

    t0 = time.time()
    last_flush = t0
    last_ticker = t0
    record_count = 0
    machine_records = 0
    ecg_samples = 0
    ppg_samples = 0
    imu_samples = 0
    beats_detected = 0
    last_ai_event = ""

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        write_csv_header(f, writer, volunteer, port, baud)
        try:
            while True:
                if args.duration > 0 and time.time() - t0 >= args.duration:
                    print(f"\n[LOG] Reached requested duration of {args.duration:.1f}s.")
                    break
                line_bytes = ser.readline()
                if not line_bytes:
                    continue
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                now = time.time()
                elapsed = now - t0
                record_count += 1

                if line.startswith("@"):
                    machine_records += 1
                    if line.startswith("@E"):
                        ecg_samples += 1
                    elif line.startswith("@P"):
                        ppg_samples += 1
                    elif line.startswith("@I"):
                        imu_samples += 1
                    elif line.startswith("@A"):
                        beats_detected += 1
                        parts = line.split(",")
                        if len(parts) > 11:
                            cls_code = parts[9] if len(parts) > 9 else "0"
                            cls_name = {"0": "Normal(N)", "1": "S-Ectopic(S)", "2": "V-Ectopic(V)"}.get(cls_code, "Q")
                            hr = parts[12] if len(parts) > 12 else parts[4]
                            last_ai_event = f"AI Beat [{cls_name}] HR={hr}bpm"

                writer.writerow([f"{now:.3f}", f"{elapsed:.3f}", line])

                if args.verbose:
                    print(line)
                else:
                    if not line.startswith(("@E", "@P", "@I")):
                        print(f"[{elapsed:6.1f}s] {line}")
                    else:
                        if now - last_ticker >= 1.0:
                            last_ticker = now
                            rate_est = record_count / max(0.1, elapsed)
                            summary = (
                                f"\r[CAPTURE {elapsed:5.1f}s] {volunteer['volunteerId']} | "
                                f"Total: {record_count} lines ({rate_est:.0f} L/s) | "
                                f"ECG: {ecg_samples} | PPG: {ppg_samples} | IMU: {imu_samples} | Beats: {beats_detected}"
                            )
                            if last_ai_event:
                                summary += f" | {last_ai_event}"
                            sys.stdout.write(summary)
                            sys.stdout.flush()

                if now - last_flush >= 1.0:
                    f.flush()
                    last_flush = now
        except KeyboardInterrupt:
            print("\n\n[LOG] Capture stopped by operator (Ctrl+C).")
        finally:
            ser.close()
            duration = time.time() - t0
            print("-" * 60)
            print(f"[SUMMARY] Volunteer  : {volunteer['volunteerId']} ({volunteer['name']})")
            print(f"[SUMMARY] Duration   : {duration:.1f} seconds")
            print(f"[SUMMARY] Records    : {record_count} lines ({machine_records} machine records)")
            print(f"[SUMMARY] CSV Saved  : {csv_path}")
            print("-" * 60)
            if record_count > 0:
                print("[SYNC] Updating volunteer status to DATA_CAPTURED ...")
                update_airtable_status(volunteer, str(csv_path), record_count, duration)
                update_local_status(volunteer, str(csv_path), record_count, duration)
            else:
                print("[SYNC] No records captured; status update skipped.")

    if record_count > 0 and not args.no_plot:
        generate_plots(csv_path, volunteer["volunteerId"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
