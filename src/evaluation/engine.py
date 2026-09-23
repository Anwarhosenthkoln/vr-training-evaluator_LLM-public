import json
import os

def evaluate_session(parsed_session_path, output_report_path):
    """
    Reads a parsed JSON file and applies the ABCDE medical rules
    to generate a scoring report.
    """
    with open(parsed_session_path, 'r', encoding='utf-8') as f:
        session_data = json.load(f)

    events = session_data.get('events', [])
    metadata = session_data.get('metadata', {})
    
    # Track the score and what they missed
    report = {
        "session_info": metadata,
        "overall_score": 100, # Start at 100 and deduct for mistakes
        "abcde_breakdown": {
            "A_Airway": {"status": "Missed", "points_deducted": 0},
            "B_Breathing": {"status": "Missed", "points_deducted": 0},
            "C_Circulation": {"status": "Missed", "points_deducted": 0},
            "D_Disability": {"status": "Missed", "points_deducted": 0},
            "E_Exposure": {"status": "Missed", "points_deducted": 0}
        },
        "feedback": [],
        "critical_errors": []
    }

    # Example Check 1: Did they check the Airway?
    has_airway = any(e['action_code'] in ["CHECK_AIRWAY", "INTUBATION", "SUCTION"] for e in events)
    if has_airway:
        report["abcde_breakdown"]["A_Airway"]["status"] = "Passed"
    else:
        report["feedback"].append("[A] Airway was not checked!")
        report["abcde_breakdown"]["A_Airway"]["points_deducted"] = 10
        report["overall_score"] -= 10

    # Example Check 2: Vital Monitoring Time Constraint (Must happen within 600s/10m)
    monitoring_events = [e for e in events if e['action_code'] in ["BP_CUFF_APPLY", "ECG_3LEAD_APPLY", "PULSE_OX_APPLY"]]
    if monitoring_events:
        first_monitor_time = monitoring_events[0]['sim_time_seconds']
        if first_monitor_time > 600:
            report["feedback"].append(f"[Time Warning] Monitoring started at {first_monitor_time}s. Target is < 600s.")
            report["overall_score"] -= 5
    else:
        report["feedback"].append("Critical: No monitoring equipment applied!")
        report["critical_errors"].append("MISSING_STEP_MONITORING")
        report["overall_score"] -= 15

    # Example Check 3: Check for forbidden actions on Ward
    katecholamine_given = [e for e in events if e['action_code'] == "MEDICATION" and ("adrenalin" in e['details'].lower() or "noradrenalin" in e['details'].lower())]
    if katecholamine_given:
        # Per rule 24 in docs: no katecholamines on normal station without emergency team
        report["critical_errors"].append("WRONG_MED_CATECHOLAMINE")
        report["feedback"].append(f"CRITICAL ERROR: Adrenalin/Noradrenalin cannot be given on the normal ward! (Event at {katecholamine_given[0]['sim_time']})")
        report["overall_score"] -= 20

    # Save the output report
    os.makedirs(os.path.dirname(output_report_path), exist_ok=True)
    with open(output_report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=4, ensure_ascii=False)
    
    print(f"Generated report for {os.path.basename(parsed_session_path)} with Score: {report['overall_score']}")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parsed_dir = os.path.abspath(os.path.join(script_dir, "../../data/parsed"))
    reports_dir = os.path.abspath(os.path.join(script_dir, "../../data/reports"))
    
    json_files = [f for f in os.listdir(parsed_dir) if f.endswith(".json")]
    
    if not json_files:
        print("⚠️ No JSON files found. Is Person A finished with the parser?")
        
    for json_file in json_files:
        input_path = os.path.join(parsed_dir, json_file)
        output_path = os.path.join(reports_dir, json_file.replace(".json", "_report.json"))
        evaluate_session(input_path, output_path)
