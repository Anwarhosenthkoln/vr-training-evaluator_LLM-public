"""
Build script to compile VR Medical Evaluator into a standalone Windows Executable (.exe)
using PyInstaller.

Usage:
    python build_exe.py
"""

import os
import subprocess
import sys

def build():
    print("=" * 60)
    print("🔨 Compiling VR Medical Evaluator to Standalone Executable...")
    print("=" * 60)

    base_dir = os.path.dirname(os.path.abspath(__file__))

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "VR_Medical_Evaluator",
        "--add-data", f"{os.path.join(base_dir, 'frontend')};frontend",
        "--add-data", f"{os.path.join(base_dir, 'data')};data",
        "--add-data", f"{os.path.join(base_dir, 'src')};src",
        "--hidden-import", "docx",
        "--hidden-import", "docx.oxml",
        "--hidden-import", "docx.oxml.ns",
        os.path.join(base_dir, "app.py")
    ]

    print("Running command:\n", " ".join(cmd), "\n")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        exe_path = os.path.join(base_dir, "dist", "VR_Medical_Evaluator.exe")
        print("\n" + "=" * 60)
        print("🎉 Build Successful!")
        print(f"Single-file standalone application created at:\n{exe_path}")
        print("=" * 60)
    else:
        print("\n❌ Build failed with exit code:", result.returncode)

if __name__ == "__main__":
    build()
