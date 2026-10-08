import json
import os

"""
TEAM COMPARISON FRAMEWORK
This script is a skeleton to compare our evaluation engine's output 
with the other team's output on the same VR log files.

Instructions for use once the other team provides their data:
1. Place their output JSONs in `data/team_b_reports/`
2. Ensure their JSON has a mapped or standard format we can parse.
3. Run this script to generate a comparison table.
"""

def load_our_report(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_their_report(filepath):
    # TODO: Modify this structure based on the other team's actual JSON schema
    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def generate_comparison_table():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    our_reports_dir = os.path.abspath(os.path.join(script_dir, "../../data/reports"))
    their_reports_dir = os.path.abspath(os.path.join(script_dir, "../../data/team_b_reports"))
    
    if not os.path.exists(their_reports_dir):
        print(f"Directory {their_reports_dir} does not exist yet. Waiting for other team's data.")
        return

    report_files = [f for f in os.listdir(our_reports_dir) if f.endswith('_report.json')]
    
    compares = []
    
    for filename in report_files:
        our_path = os.path.join(our_reports_dir, filename)
        their_path = os.path.join(their_reports_dir, filename) # Assuming same naming convention
        
        if not os.path.exists(their_path):
            continue
            
        our_rep = load_our_report(our_path)
        their_rep = load_their_report(their_path)
        
        # Example metrics to compare
        our_score = our_rep.get('overall_score', 'N/A')
        their_score = their_rep.get('score', 'N/A') # Placeholder key
        
        our_criticals = len(our_rep.get('critical_errors', []))
        their_criticals = len(their_rep.get('critical_errors', [])) # Placeholder key
        
        compares.append({
            "log": filename,
            "our_score": our_score,
            "their_score": their_score,
            "our_critical_flags": our_criticals,
            "their_critical_flags": their_criticals
        })
        
    print(f"{'Log File':<50} | {'Our Score':<10} | {'Their Score':<11} | {'Our Crit':<10} | {'Their Crit':<10}")
    print("-" * 100)
    for c in compares:
        print(f"{c['log']:<50} | {c['our_score']:<10} | {c['their_score']:<11} | {c['our_critical_flags']:<10} | {c['their_critical_flags']:<10}")

if __name__ == "__main__":
    generate_comparison_table()
