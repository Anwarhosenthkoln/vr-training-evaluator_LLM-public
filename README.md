# 🏥 VR Medical Training Evaluation System

Automated evaluation system for medical VR training scenarios.

## 📂 Project Structure

- `data/raw_logs/`: Drop the VR text logs here.
- `data/parsed/`: JSON outputs from the parser will be saved here.
- `src/parser/`: Python code to parse logs into JSON.
- `src/evaluation/`: Python code for the ABCDE rules engine.
- `frontend/`: Web dashboard files.

## 🚀 Getting Started

1. Place your VR logs (`.txt` files) in `data/raw_logs/`.
2. Run the parser inside `src/parser/log_parser.py`.
3. Check the parsed JSON output in `data/parsed/`.
