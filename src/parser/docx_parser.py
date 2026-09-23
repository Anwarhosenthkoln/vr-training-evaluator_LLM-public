import os
import json
import re

try:
    from docx import Document
except ImportError:
    print("Error: The 'python-docx' library is not installed.")
    print("Please run: pip install python-docx")
    exit(1)

# Import the same ACTION_MAP from log_parser
try:
    from log_parser import ACTION_MAP, parse_time_to_seconds
except ImportError:
    # Fallback if run directly
    ACTION_MAP = {}
    def parse_time_to_seconds(time_str):
        try:
            parts = str(time_str).strip().split(':')
            if len(parts) == 2: return int(parts[0]) * 60 + int(parts[1])
            return 0
        except ValueError:
            return 0

def parse_docx_log(filepath):
    """Parses a VR .docx log, extracting actions, metadata, and vital parameters."""
    doc = Document(filepath)
    
    session_data = {
        "metadata": {},
        "events": [],
        "vital_parameters": []
    }
    
    current_section = "metadata" # can be 'metadata', 'aktion_log', 'vital_log'
    vitals_headers = []
    
    for paragraph in doc.paragraphs:
        line = paragraph.text.strip()
        if not line:
            continue
            
        # Section detection
        if "Aktion Log" in line or line.strip() == "Log:":
            current_section = "aktion_log"
            continue
        elif "Vital Log" in line or "Uhrzeit | Zeit |" in line:
            current_section = "vital_log"
            # Extract headers from the line if it looks like the header row
            if "|" in line and "HR" in line:
                vitals_headers = [h.strip() for h in line.split("|")]
            continue
            
        # Parse based on current section
        if current_section == "metadata":
            if ":" in line:
                parts = line.split(":", 1)
                session_data["metadata"][parts[0].strip()] = parts[1].strip()
                
        elif current_section == "aktion_log":
            # Very similar to txt parser
            if "|" in line:
                parts = [p.strip() for p in line.split('|')]
                # Format: 15:28:50 | 6:25 | Charlie | BGA durchführen | Start | ...
                if len(parts) >= 5 and re.match(r'\d{2}:\d{2}:\d{2}', parts[0]):
                    wall_clock = parts[0]
                    sim_time_raw = parts[1]
                    actor = parts[2]
                    action = parts[3]
                    phase = parts[4]
                    details = parts[5] if len(parts) > 5 else ""
                    
                    action_code = ACTION_MAP.get(action, "UNKNOWN_ACTION")
                    if action_code == "DELEGATE_NPC" and "->" in details:
                        match = re.search(r'->\s*(.*?)(?:\||$)', details)
                        if match:
                            delegated_action = match.group(1).strip()
                            action_code = f"DELEGATE_{ACTION_MAP.get(delegated_action, 'UNKNOWN')}"

                    expert_comment = None
                    # Try to extract the doctor's inline comment, which often appears at the end in parentheses
                    comment_match = re.search(r'\(([^)]+)\)$', details.strip())
                    if comment_match:
                        comment_text = comment_match.group(1).strip()
                        # Verify it looks like a real comment (e.g. contains 'richtig', 'falsch', or is long enough)
                        if len(comment_text) > 5 or any(k in comment_text.lower() for k in ["richtig", "falsch", "korrekt"]):
                            expert_comment = comment_text
                            details = details[:comment_match.start()].strip()

                    session_data["events"].append({
                        "id": len(session_data["events"]) + 1,
                        "wall_clock": wall_clock,
                        "sim_time": sim_time_raw,
                        "sim_time_seconds": parse_time_to_seconds(sim_time_raw),
                        "actor": actor,
                        "action_raw": action,
                        "action_code": action_code,
                        "phase": phase,
                        "details": details,
                        "expert_comment": expert_comment
                    })

        elif current_section == "vital_log":
            # Format: 15:23:00 | 0:35 | 14 | 72 | 12 | 97 | 95 | 114 | 74 
            if "|" in line and re.match(r'\d{2}:\d{2}:\d{2}', line.split("|")[0].strip()):
                parts = [p.strip() for p in line.split('|')]
                
                # Check if this matches our expected columns (approx 9 columns)
                # Uhrzeit | Zeit | GCS | HR | RR | OXY | MEAN | SYS | DIA
                if len(parts) >= 9:
                    vital_entry = {
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
                    session_data["vital_parameters"].append(vital_entry)

    return session_data

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # We will read docx files if you drop them in raw_logs
    raw_logs_dir = os.path.abspath(os.path.join(script_dir, "../../data/raw_logs"))
    parsed_dir = os.path.abspath(os.path.join(script_dir, "../../data/parsed"))
    
    docx_files = [f for f in os.listdir(raw_logs_dir) if f.endswith(".docx")]
    
    if not docx_files:
        print("⚠️ No .docx files found in data/raw_logs.")
    
    for filename in docx_files:
        print(f"Parsing DOCX: {filename}...")
        try:
            input_path = os.path.join(raw_logs_dir, filename)
            output_path = os.path.join(parsed_dir, filename.replace(".docx", ".json"))
            
            parsed_data = parse_docx_log(input_path)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(parsed_data, f, indent=4, ensure_ascii=False)
                
            print(f"✅ Saved DOCX JSON data to {output_path}")
        except Exception as e:
            print(f"❌ Error parsing {filename}: {e}")
