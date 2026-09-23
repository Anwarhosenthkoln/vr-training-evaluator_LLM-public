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
    "Troponin T messen": "TROPONIN_CHECK"
}

def parse_time_to_seconds(time_str):
    """Converts a time string like '1:36' to 96 seconds."""
    try:
        if not time_str or ':' not in time_str:
            return 0
        parts = time_str.strip().split(':')
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3: # HH:MM:SS (unlikely for sim time but just in case)
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return 0
    except ValueError:
        return 0

def read_file_with_fallback_encoding(filepath):
    """Reads a file trying UTF-8 first, then UTF-16LE if it fails."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.readlines()
    except UnicodeDecodeError:
        with open(filepath, 'r', encoding='utf-16le') as f:
            return f.readlines()

def parse_txt_log(filepath):
    """Reads a VR text log and converts it to a structured list of events."""
    events = []
    
    lines = read_file_with_fallback_encoding(filepath)
    
    for line_num, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
            
        parts = [p.strip() for p in line.split('|')]
        
        # Check if it has a wall clock (e.g. 14:32:19 format)
        if len(parts) >= 5 and re.match(r'\d{2}:\d{2}:\d{2}', parts[0]):
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
            continue # Skip malformed lines
        
        sim_time_seconds = parse_time_to_seconds(sim_time_raw)
        
        # Map to canonical English code
        action_code = ACTION_MAP.get(action, "UNKNOWN_ACTION")
        
        # For 'NPC beauftragen' (delegating), we might want to extract WHAT was delegated
        if action_code == "DELEGATE_NPC" and "->" in details:
            # details looks like: "Pflege -> BGA durchführen"
            match = re.search(r'->\s*(.*?)(?:\||$)', details)
            if match:
                delegated_action = match.group(1).strip()
                # We can also map the delegated action
                delegated_code = ACTION_MAP.get(delegated_action, "UNKNOWN_ACTION")
                action_code = f"DELEGATE_{delegated_code}"

        event = {
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
        events.append(event)
                
    return events

if __name__ == "__main__":
    # Get the directory of the current script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Path to the raw logs (relative to script location)
    raw_logs_dir = os.path.abspath(os.path.join(script_dir, "../../data/raw_logs"))
    parsed_dir = os.path.abspath(os.path.join(script_dir, "../../data/parsed"))
    
    # Create directories if they don't exist
    os.makedirs(raw_logs_dir, exist_ok=True)
    os.makedirs(parsed_dir, exist_ok=True)
    
    print(f"Reading logs from: {raw_logs_dir}")
    
    # Find all .txt files in the raw_logs folder
    txt_files = [f for f in os.listdir(raw_logs_dir) if f.endswith(".txt")]
    
    if not txt_files:
        print("⚠️ No .txt files found in data/raw_logs. Please add some VR log files.")
    
    for filename in txt_files:
        input_path = os.path.join(raw_logs_dir, filename)
        output_path = os.path.join(parsed_dir, filename.replace(".txt", ".json"))
        
        print(f"Parsing: {filename}...")
        parsed_events = parse_txt_log(input_path)
        
        # Save the JSON file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(parsed_events, f, indent=4, ensure_ascii=False)
            
        print(f"✅ Saved {len(parsed_events)} events to {output_path}")

    print("\nAll parsing done! The JSON files are ready for Person B (Evaluation Engine).")
