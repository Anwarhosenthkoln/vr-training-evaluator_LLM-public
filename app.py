"""
VR Medical Training Evaluator — Desktop Application Launcher

This script serves as the entrypoint for the standalone .exe package.
It launches a local web server, ensures reports are up-to-date,
and automatically opens the evaluation dashboard in the user's default browser.
"""

import os
import sys
import socket
import http.server
import socketserver
import threading
import time
import webbrowser
import urllib.parse

# Determine if running in a bundled PyInstaller environment
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
    EXE_DIR = os.path.dirname(sys.executable)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = BUNDLE_DIR

# Determine directories
# If user provided a data directory next to the exe, use that; otherwise use bundled data
if os.path.exists(os.path.join(EXE_DIR, "data")):
    DATA_DIR = os.path.join(EXE_DIR, "data")
else:
    DATA_DIR = os.path.join(BUNDLE_DIR, "data")

if os.path.exists(os.path.join(EXE_DIR, "frontend")):
    FRONTEND_DIR = os.path.join(EXE_DIR, "frontend")
else:
    FRONTEND_DIR = os.path.join(BUNDLE_DIR, "frontend")

SRC_DIR = os.path.join(BUNDLE_DIR, "src")
sys.path.insert(0, os.path.join(SRC_DIR, "parser"))
sys.path.insert(0, os.path.join(SRC_DIR, "evaluation"))
sys.path.insert(0, os.path.join(SRC_DIR, "validation"))


class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom request handler that cleanly routes frontend assets and report data."""

    def translate_path(self, path):
        # Strip query strings and hashes
        path = path.split('?', 1)[0].split('#', 1)[0]
        # URL-decode path so percent-encoded spaces (%20) and umlauts (%C3%A4) match the disk
        path = urllib.parse.unquote(path)
        parts = [p for p in path.split('/') if p and p != '..']

        if not parts or parts == ['index.html']:
            return os.path.join(FRONTEND_DIR, "index.html")

        if parts[0] == "frontend":
            sub = os.path.join(*parts[1:]) if len(parts) > 1 else "index.html"
            return os.path.join(FRONTEND_DIR, sub)

        if parts[0] == "data":
            sub = os.path.join(*parts[1:]) if len(parts) > 1 else ""
            return os.path.join(DATA_DIR, sub)

        # Fallback to frontend directory
        return os.path.join(FRONTEND_DIR, *parts)

    def do_GET(self):
        # If accessing root '/', redirect to '/frontend/index.html'
        if self.path == "/" or self.path == "":
            self.send_response(302)
            self.send_header("Location", "/frontend/index.html")
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, format, *args):
        # Suppress routine log output to keep console clean
        pass


def find_free_port(start_port=8080):
    for port in range(start_port, start_port + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start_port


def run_pipeline_if_needed():
    """Runs parsers and engine if raw_logs exist to keep reports fresh."""
    raw_dir = os.path.join(DATA_DIR, "raw_logs")
    parsed_dir = os.path.join(DATA_DIR, "parsed")
    reports_dir = os.path.join(DATA_DIR, "reports")

    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(parsed_dir, exist_ok=True)
    os.makedirs(reports_dir, exist_ok=True)

    try:
        from log_parser import parse_txt_log
        from docx_parser import parse_docx_log
        from engine import evaluate_all_sessions
        import json

        # Process any txt files
        for f in os.listdir(raw_dir):
            if f.endswith(".txt"):
                in_p = os.path.join(raw_dir, f)
                out_p = os.path.join(parsed_dir, f.replace(".txt", ".json"))
                if not os.path.exists(out_p):
                    data = parse_txt_log(in_p)
                    with open(out_p, "w", encoding="utf-8") as out_f:
                        json.dump(data, out_f, indent=4, ensure_ascii=False)

        # Process any docx files
        for f in os.listdir(raw_dir):
            if f.endswith(".docx") and not f.startswith("~$"):
                in_p = os.path.join(raw_dir, f)
                out_p = os.path.join(parsed_dir, f.replace(".docx", ".json"))
                if not os.path.exists(out_p):
                    data = parse_docx_log(in_p)
                    with open(out_p, "w", encoding="utf-8") as out_f:
                        json.dump(data, out_f, indent=4, ensure_ascii=False)

        evaluate_all_sessions()
    except Exception as e:
        # Non-fatal if already pre-generated
        pass


def main():
    print("=" * 65)
    print("  🩺 VR Medical Training Evaluator — Automated Dashboard")
    print("=" * 65)
    print("  Starting up... Checking session data and evaluation reports.")

    run_pipeline_if_needed()

    port = find_free_port(8080)
    server_address = ('127.0.0.1', port)

    try:
        httpd = socketserver.TCPServer(server_address, CustomHTTPRequestHandler)
    except Exception as e:
        print(f"❌ Could not start server: {e}")
        input("Press Enter to exit...")
        return

    url = f"http://127.0.0.1:{port}/frontend/index.html"
    print(f"\n  ✅ Dashboard Server Active at: {url}")
    print("  🌐 Opening your browser automatically...")
    print("\n  [Tip] Keep this window open while using the dashboard.")
    print("  Close this window or press Ctrl+C when finished.")
    print("=" * 65)

    # Open browser after a brief delay so server is ready to accept connections
    def open_browser():
        time.sleep(1.0)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped. Goodbye!")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
