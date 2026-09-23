import json
import os
import re

def parse_time_to_seconds(time_str):
    """Converts a time string like '1:36' to 96 seconds."""
    try:
        parts = time_str.split(':')
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return 0
    except ValueError:
        return 0

def parse_txt_log(filepath):
    """Reads a VR text log and converts it to a structured list of events."""
    events = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
                
            parts = [p.strip() for p in line.split('|')]
            
            # Basic parsing log:
            # Format 1 (No wall clock): 6:42 | Dirk | Patient entkleiden | Start | 
            # Format 2 (With wall clock): 14:32:19 | 0:09 | Jens | NPC beauftragen | Start | NPC rufen: Pflege (Kim)
            
            if len(parts) >= 4:
                # Check if it has a wall clock (e.g. 14:32:19 format)
                if len(parts) >= 5 and re.match(r'\d{2}:\d{2}:\d{2}', parts[0]):
                    wall_clock = parts[0]
                    sim_time_raw = parts[1]
                    actor = parts[2]
                    action = parts[3]
                    phase = parts[4]
                    details = parts[5] if len(parts) > 5 else ""
                else:
                    # No wall clock (e.g. 6:42)
                    wall_clock = None
                    sim_time_raw = parts[0]
                    actor = parts[1]
                    action = parts[2]
                    phase = parts[3]
                    details = parts[4] if len(parts) > 4 else ""
                
                sim_time_seconds = parse_time_to_seconds(sim_time_raw)
                
                event = {
                    "id": line_num,
                    "wall_clock": wall_clock,
                    "sim_time": sim_time_raw,
                    "sim_time_seconds": sim_time_seconds,
                    "actor": actor,
                    "action_raw": action,
                    "phase": phase,
                    "details": details
                    # TODO: Person A will add 'action_code' mapping here later!
                }
                events.append(event)
                
    return events

if __name__ == "__main__":
    # Example usage: Person A can run this script to parse a file!
    
    # Path to the raw logs
    raw_logs_dir = "../../data/raw_logs"
    parsed_dir = "../../data/parsed"
    
    # Create the parsed directory if it doesn't exist
    os.makedirs(parsed_dir, exist_ok=True)
    
    # Find all .txt files in the raw_logs folder
    for filename in os.listdir(raw_logs_dir):
        if filename.endswith(".txt"):
            input_path = os.path.join(raw_logs_dir, filename)
            output_path = os.path.join(parsed_dir, filename.replace(".txt", ".json"))
            
            print(f"Parsing: {filename}...")
            parsed_events = parse_txt_log(input_path)
            
            # Save the JSON file
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(parsed_events, f, indent=4, ensure_ascii=False)
                
            print(f"✅ Saved JSON to {output_path}")

    print("All parsing done! The JSON files are ready for Person B (Evaluation Engine).")
