import json
import os
import re

# Comprehensive mapping of German VR log actions to standardized English codes
ACTION_MAP = {
    "Atmung prüfen": "CHECK_BREATHING",
    "Atemwegsverlegung prüfen": "CHECK_AIRWAY",
    "Puls messen": "CHECK_PULSE",
    "Palpation": "PALPATION",
    "ReCap": "RECAP_TIME",
    "Blutdruckmanschette": "BP_CUFF_APPLY",
    "Pulsoxymetrie": "PULSE_OX_APPLY",
    "EKG 3-Kanal": "ECG_3LEAD_APPLY",
    "EKG 12-Kanal": "ECG_12LEAD_APPLY",
    "PVK": "IV_ACCESS",
    "Patient entkleiden": "UNDRESS_PATIENT",
    "NPC beauftragen": "DELEGATE_NPC",
    "Infusion": "INFUSION",
    "Medikament": "MEDICATION",
    "Sauerstoffgabe": "OXYGEN_APPLY",
    "GCS": "GCS_CHECK",
    "Blutentnahme": "BLOOD_DRAW",
    "BGA durchführen": "BLOOD_GAS_ANALYSIS",
    "Ultraschall": "ULTRASOUND_FAST",
    "Umlagern": "REPOSITION",
    "CPR": "CPR",
    "Intubation": "INTUBATION",
    "Absaugen": "SUCTION",
    "HWS-Stabilisieren": "CERVICAL_STABILIZE",
    "Monitor anbauen": "MONITOR_ATTACH",
    "Blutzucker messen": "BLOOD_SUGAR",
    "Temperatur messen": "TEMPERATURE",
    "Thoraxdrainage": "CHEST_DRAIN",
    "Defibrillator": "DEFIBRILLATOR",
    "Blutläufer": "BLOOD_RUNNER",
    "Hole Gegenstand": "FETCH_EQUIPMENT",
    "Pflaster": "REMOVE_PATCH",
    "Raum verlassen": "LEAVE_ROOM",
    "HWS-Verletzung prüfen": "CHECK_CERVICAL_INJURY",
    "Auskultation": "AUSCULTATION",
    "Gabe Traubenzucker/Saft": "GIVE_GLUCOSE_ORAL",
    "CT": "CT_SCAN",
    "Invasive Blutdruckmessung": "ART_LINE_APPLY",
    "Troponin T messen": "TROPONIN_CHECK",
    "Neurologische Untersuchung": "NEURO_EXAM",
    "Wells/Genfer-Score": "WELLS_GENEVA_SCORE",
    "Transfusion einleiten": "BLOOD_TRANSFUSION",
    "Beende Aktion": "CANCEL_ACTION",
}

def parse_time_to_seconds(time_str):
    """Converts a time string like '1:36' to 96 seconds."""
    try:
        if not time_str or ':' not in time_str:
            return 0
        parts = time_str.strip().split(':')
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return 0
    except ValueError:
        return 0

def read_file_with_fallback_encoding(filepath):
    """Reads a file trying UTF-8-BOM first, then UTF-8, then UTF-16LE."""
    for enc in ['utf-8-sig', 'utf-8', 'utf-16le']:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.readlines()
        except (UnicodeDecodeError, UnicodeError):
            continue
    # last resort
    with open(filepath, 'r', encoding='latin-1') as f:
        return f.readlines()

def parse_action_line(line, line_num):
    """Parses a single action line and returns an event dict, or None if unparseable."""
    parts = [p.strip() for p in line.split('|')]

    # Check if it has a wall clock (e.g. 14:32:19 format)
    if len(parts) >= 5 and re.match(r'\d{1,2}:\d{2}:\d{2}', parts[0]):
        wall_clock = parts[0]
        sim_time_raw = parts[1]
        actor = parts[2]
        action = parts[3]
        phase = parts[4]
        details = parts[5] if len(parts) > 5 else ""
    elif len(parts) >= 4:
        # No wall clock (e.g. 6:42)
        wall_clock = None
        sim_time_raw = parts[0]
        actor = parts[1]
        action = parts[2]
        phase = parts[3]
        details = parts[4] if len(parts) > 4 else ""
    else:
        return None

    sim_time_seconds = parse_time_to_seconds(sim_time_raw)

    # Map to canonical English code
    action_code = ACTION_MAP.get(action, "UNKNOWN_ACTION")

    # For 'NPC beauftragen' (delegating), extract WHAT was delegated
    if action_code == "DELEGATE_NPC" and "->" in details:
        match = re.search(r'->\s*(.*?)(?:\||$)', details)
        if match:
            delegated_action = match.group(1).strip()
            delegated_code = ACTION_MAP.get(delegated_action, "UNKNOWN_ACTION")
            action_code = f"DELEGATE_{delegated_code}"

    return {
        "id": line_num,
        "wall_clock": wall_clock,
        "sim_time": sim_time_raw,
        "sim_time_seconds": sim_time_seconds,
        "actor": actor,
        "action_raw": action,
        "action_code": action_code,
        "phase": phase,
        "details": details
    }

def parse_vital_line(line):
    """Parses a vital parameter line and returns a dict, or None."""
    parts = [p.strip() for p in line.split('|')]
    if len(parts) >= 9 and re.match(r'\d{1,2}:\d{2}:\d{2}', parts[0]):
        return {
            "wall_clock": parts[0],
            "sim_time": parts[1],
            "sim_time_seconds": parse_time_to_seconds(parts[1]),
            "gcs": int(parts[2]) if parts[2].isdigit() else None,
            "hr_bpm": int(parts[3]) if parts[3].isdigit() else None,
            "rr_per_min": int(parts[4]) if parts[4].isdigit() else None,
            "spo2_percent": int(parts[5]) if parts[5].isdigit() else None,
            "map": int(parts[6]) if parts[6].isdigit() else None,
            "sys_bp": int(parts[7]) if parts[7].isdigit() else None,
            "dia_bp": int(parts[8]) if parts[8].isdigit() else None,
        }
    return None

def parse_talk_line(line):
    """Parses a Patient Talk or Voice Control log line."""
    parts = [p.strip() for p in line.split('|')]
    if len(parts) >= 3 and re.match(r'\d{1,2}:\d{2}:\d{2}', parts[0]):
        return {
            "wall_clock": parts[0],
            "sim_time": parts[1],
            "sim_time_seconds": parse_time_to_seconds(parts[1]),
            "text": parts[2]
        }
    return None

def is_section_header(line):
    """Detects section headers in newer log format."""
    lower = line.lower().strip().rstrip(':')
    if lower in ['aktion log', 'vital log', 'patient talk log', 'voice control log']:
        return lower
    if line.strip().startswith('Uhrzeit | Zeit |'):
        return 'vital log'
    return None

def parse_txt_log(filepath):
    """
    Reads a VR text log and converts it to a structured session dict.
    Handles both OLD format (flat action lines) and NEW format (with metadata + sections).
    """
    lines = read_file_with_fallback_encoding(filepath)

    # Detect whether this is the new format (has metadata lines like "Modul:", "Patient:", etc.)
    has_metadata = any(l.strip().startswith('Modul:') or l.strip().startswith('Patient:') for l in lines[:10])

    if has_metadata:
        return _parse_new_txt_format(lines)
    else:
        return _parse_old_txt_format(lines)

def _parse_old_txt_format(lines):
    """Original flat format: just action lines, no metadata sections."""
    events = []
    for line_num, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        event = parse_action_line(line, line_num)
        if event:
            events.append(event)
    return events

def _parse_new_txt_format(lines):
    """New enriched format with metadata, Aktion Log, Vital Log, Patient Talk Log, Voice Control Log."""
    session = {
        "metadata": {},
        "events": [],
        "vital_parameters": [],
        "patient_talk": [],
        "voice_control": []
    }

    current_section = "metadata"
    event_counter = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check for section headers
        section = is_section_header(line)
        if section:
            current_section = section
            continue

        if current_section == "metadata":
            # Lines like "Modul: Station" or "Patient: Hypoglykämie (Stufe 1)"
            if ':' in line and '|' not in line:
                key, _, value = line.partition(':')
                session["metadata"][key.strip()] = value.strip()

        elif current_section == "aktion log":
            if '|' in line:
                event_counter += 1
                event = parse_action_line(line, event_counter)
                if event:
                    session["events"].append(event)

        elif current_section == "vital log":
            if '|' in line and not line.startswith('Uhrzeit'):
                vital = parse_vital_line(line)
                if vital:
                    session["vital_parameters"].append(vital)

        elif current_section == "patient talk log":
            if '|' in line:
                talk = parse_talk_line(line)
                if talk:
                    session["patient_talk"].append(talk)

        elif current_section == "voice control log":
            if '|' in line:
                voice = parse_talk_line(line)
                if voice:
                    session["voice_control"].append(voice)

    return session

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    raw_logs_dir = os.path.abspath(os.path.join(script_dir, "../../data/raw_logs"))
    parsed_dir = os.path.abspath(os.path.join(script_dir, "../../data/parsed"))

    os.makedirs(raw_logs_dir, exist_ok=True)
    os.makedirs(parsed_dir, exist_ok=True)

    print(f"Reading logs from: {raw_logs_dir}")

    txt_files = [f for f in os.listdir(raw_logs_dir) if f.endswith(".txt")]

    if not txt_files:
        print("⚠️ No .txt files found in data/raw_logs. Please add some VR log files.")

    for filename in txt_files:
        input_path = os.path.join(raw_logs_dir, filename)
        output_path = os.path.join(parsed_dir, filename.replace(".txt", ".json"))

        print(f"Parsing: {filename}...")
        parsed_data = parse_txt_log(input_path)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(parsed_data, f, indent=4, ensure_ascii=False)

        # Display count
        if isinstance(parsed_data, list):
            count = len(parsed_data)
        else:
            count = len(parsed_data.get("events", []))
        print(f"✅ Saved {count} events to {output_path}")

    print("\nAll parsing done!")
