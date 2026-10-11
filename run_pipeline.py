"""
VR Medical Training Evaluator — End-to-End Pipeline Runner

Usage:
    python run_pipeline.py                  # Parse all raw logs and generate evaluation reports
    python run_pipeline.py --file <path>    # Evaluate a single .txt or .docx log file
    python run_pipeline.py --serve          # Start local web dashboard server
    python run_pipeline.py --validate       # Run sanity check against doctor annotations
"""

import os
import sys
import argparse
import subprocess
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, "src")
DATA_DIR = os.path.join(BASE_DIR, "data")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

# Ensure src modules can be imported
sys.path.insert(0, os.path.join(SRC_DIR, "parser"))
sys.path.insert(0, os.path.join(SRC_DIR, "evaluation"))
sys.path.insert(0, os.path.join(SRC_DIR, "validation"))


def run_full_pipeline():
    print("=" * 60)
    print("🏥 VR Medical Training Evaluator — Full Pipeline Execution")
    print("=" * 60)

    # Step 1: Text logs
    print("\n[1/3] Parsing raw .txt logs...")
    try:
        from log_parser import parse_txt_log
        import json
        raw_dir = os.path.join(DATA_DIR, "raw_logs")
        parsed_dir = os.path.join(DATA_DIR, "parsed")
        txt_count = 0
        for f in os.listdir(raw_dir):
            if f.endswith(".txt"):
                in_path = os.path.join(raw_dir, f)
                out_path = os.path.join(parsed_dir, f.replace(".txt", ".json"))
                data = parse_txt_log(in_path)
                with open(out_path, "w", encoding="utf-8") as out_f:
                    json.dump(data, out_f, indent=4, ensure_ascii=False)
                txt_count += 1
        print(f"  ✅ Parsed {txt_count} .txt log files.")
    except Exception as e:
        print(f"  ❌ Error parsing .txt logs: {e}")

    # Step 2: DOCX logs
    print("\n[2/3] Parsing raw .docx logs...")
    try:
        from docx_parser import parse_docx_log
        import json
        docx_count = 0
        for f in os.listdir(raw_dir):
            if f.endswith(".docx") and not f.startswith("~$"):
                in_path = os.path.join(raw_dir, f)
                out_path = os.path.join(parsed_dir, f.replace(".docx", ".json"))
                data = parse_docx_log(in_path)
                with open(out_path, "w", encoding="utf-8") as out_f:
                    json.dump(data, out_f, indent=4, ensure_ascii=False)
                docx_count += 1
        print(f"  ✅ Parsed {docx_count} .docx log files.")
    except Exception as e:
        print(f"  ❌ Error parsing .docx logs: {e}")

    # Step 3: Evaluation Engine
    print("\n[3/3] Running Clinical Evaluation Engine...")
    try:
        from engine import evaluate_all_sessions
        evaluate_all_sessions()
        print("  ✅ All evaluation reports successfully generated in data/reports/")
    except Exception as e:
        print(f"  ❌ Error running evaluation engine: {e}")

    print("\n" + "=" * 60)
    print("🎉 Pipeline run complete!")
    print("To view results in dashboard, run:")
    print("    python run_pipeline.py --serve")
    print("=" * 60)


def evaluate_single_file(file_path):
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return

    ext = os.path.splitext(file_path)[1].lower()
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    parsed_out = os.path.join(DATA_DIR, "parsed", f"{base_name}.json")
    report_out = os.path.join(DATA_DIR, "reports", f"{base_name}_report.json")

    print(f"Processing single file: {file_path}")
    import json
    if ext == ".txt":
        from log_parser import parse_txt_log
        parsed_data = parse_txt_log(file_path)
        with open(parsed_out, "w", encoding="utf-8") as f:
            json.dump(parsed_data, f, indent=4, ensure_ascii=False)
    elif ext == ".docx":
        from docx_parser import parse_docx_log
        parsed_data = parse_docx_log(file_path)
        with open(parsed_out, "w", encoding="utf-8") as f:
            json.dump(parsed_data, f, indent=4, ensure_ascii=False)
    else:
        print(f"❌ Unsupported format: {ext}. Only .txt and .docx are supported.")
        return

    from engine import evaluate_session
    report = evaluate_session(parsed_out, report_out)

    print("\n" + "=" * 60)
    print(f"📊 Evaluation Report for: {base_name}")
    print(f"Score:    {report.get('overall_score')} / 100 ({report.get('verdict')})")
    cov = report.get('coverage', {})
    print(f"Coverage: {cov.get('evaluated_actions')}/{cov.get('total_actions')} actions evaluated ({cov.get('coverage_percent')}%)")
    crit = report.get('critical_errors', [])
    print(f"Critical Errors: {len(crit)}")
    for err in crit:
        print(f"  - {err}")
    print(f"\nDetailed report saved to: {report_out}")
    print("=" * 60)


def run_sanity_check():
    print("Running Sanity Check against Doctor Annotations...")
    from sanity_check import main as sanity_main
    sanity_main()


def start_server(port=8080):
    from app import CustomHTTPRequestHandler
    import socketserver
    
    server_address = ('127.0.0.1', port)
    with socketserver.TCPServer(server_address, CustomHTTPRequestHandler) as httpd:
        url = f"http://127.0.0.1:{port}/frontend/index.html"
        print(f"\n🚀 Dashboard server started at: {url}")
        print("Press Ctrl+C to stop the server.\n")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


def main():
    parser = argparse.ArgumentParser(description="VR Medical Training Evaluator")
    parser.add_argument("--file", "-f", type=str, help="Process and evaluate a single log file")
    parser.add_argument("--serve", "-s", action="store_true", help="Launch local dashboard web server")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Port for web server (default: 8080)")
    parser.add_argument("--validate", "-v", action="store_true", help="Run sanity check validation")

    args = parser.parse_args()

    if args.file:
        evaluate_single_file(args.file)
    elif args.serve:
        start_server(args.port)
    elif args.validate:
        run_sanity_check()
    else:
        run_full_pipeline()


if __name__ == "__main__":
    main()
