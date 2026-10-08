import json
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
parsed_dir = os.path.abspath(os.path.join(script_dir, "../../data/parsed"))
reports_dir = os.path.abspath(os.path.join(script_dir, "../../data/reports"))
out_file = os.path.abspath(os.path.join(script_dir, "../../data/reports/sanity_check_results.json"))

def classify_comment(comment):
    if not comment: return "none"
    lower_c = comment.lower()
    
    if "falsch" in lower_c:
        return "incorrect"
    elif "richtig" in lower_c or "korrekt" in lower_c:
        if "hätte" in lower_c or "erst nach" in lower_c or "früher" in lower_c or "bereits beim" in lower_c or "schon zuvor" in lower_c or "bereits" in lower_c:
            return "correct but late/order issue"
        return "correct"
    return "neutral"

def find_engine_flags(event, report):
    sim_time = event.get('sim_time')
    sim_time_sec = event.get('sim_time_seconds')
    action_raw = event.get('action_raw', '')
    action_code = event.get('action_code', '')
    details_lower = event.get('details', '').lower()
    
    flags = []
    
    # Check feedback strings for time or action references
    for fb in report.get("feedback", []):
        fb_lower = fb.lower()
        
        # Check if the feedback mentions the time of this event
        if sim_time and f" {sim_time} " in fb or f"at {sim_time}s " in fb_lower or f"at {sim_time_sec}s" in fb_lower:
            if fb not in flags: flags.append(fb)
            continue
            
        # Hardcode some checks based on action_code
        if action_code == "MEDICATION" and "ketamin" in fb_lower and "ketamin" in details_lower:
            if fb not in flags: flags.append(fb)
        elif action_code == "MEDICATION" and ("adrenalin" in fb_lower or "noradrenalin" in fb_lower) and ("adrenalin" in details_lower):
            if fb not in flags: flags.append(fb)
             
        # Order issues matching action codes roughly
        if action_code == "ULTRASOUND_FAST" and "fast ultrasound" in fb_lower and "order" in fb_lower:
            if fb not in flags: flags.append(fb)
             
        if action_code == "OXYGEN_APPLY" and "oxygen" in fb_lower and "without indication" in fb_lower:
            if fb not in flags: flags.append(fb)

        # Pulse check order violations
        if action_code == "CHECK_PULSE" and "pulse check performed at" in fb_lower and "before breathing" in fb_lower:
            if fb not in flags: flags.append(fb)
            
        # Palpation check order violations
        if action_code == "PALPATION" and "palpation performed at" in fb_lower and "before breathing" in fb_lower:
            if fb not in flags: flags.append(fb)
            
    return flags

def main():
    results = []

    for f in os.listdir(parsed_dir):
        if not f.endswith('.json'): continue
        
        with open(os.path.join(parsed_dir, f), 'r', encoding='utf-8') as fh:
            data = json.load(fh)
            
        events = data if isinstance(data, list) else data.get('events', [])
        
        report_file = os.path.join(reports_dir, f.replace('.json', '_report.json'))
        if not os.path.exists(report_file): continue
        
        with open(report_file, 'r', encoding='utf-8') as fh:
            report = json.load(fh)
            
        for e in events:
            comment = e.get("expert_comment")
            if comment:
                doc_class = classify_comment(comment)
                engine_flags = find_engine_flags(e, report)
                
                match = False
                # If doctor says correct and there are no critical/order flags -> match
                if doc_class == "correct" and not engine_flags:
                    match = True
                # If doctor says incorrect or correct but late -> match if there are engine flags
                elif doc_class in ["incorrect", "correct but late/order issue"] and engine_flags:
                    match = True
                # If doc is neutral, we consider it a match (as it doesn't strictly dictate engine behavior)
                elif doc_class == "neutral":
                    match = True
                    
                results.append({
                    "file": f,
                    "sim_time": e.get("sim_time"),
                    "action_raw": e.get("action_raw"),
                    "details": e.get("details"),
                    "expert_comment": comment,
                    "doc_verdict": doc_class,
                    "engine_flags": engine_flags,
                    "match": match
                })

    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

    total = len(results)
    if total == 0:
        print("No annotated events found.")
        return

    matches = sum(1 for r in results if r["match"])
    print(f"Sanity check complete. Validated {total} annotated events.")
    print(f"Agreement rate: {matches}/{total} ({(matches/total)*100:.1f}%)")

    print("\n--- Mismatches ---")
    for r in results:
        if not r["match"]:
            print(f"[{r['file']}] {r['sim_time']} | {r['action_raw']} - {r['details']}")
            print(f"  Doctor: {r['doc_verdict']} (\"{r['expert_comment']}\")")
            print(f"  Engine Flags: {r['engine_flags']}")
            print()

if __name__ == "__main__":
    main()
