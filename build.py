#!/usr/bin/env python3
"""
Build Launcher.exe (or Launcher on Linux/macOS) using PyInstaller.
Run: python build.py
"""
import subprocess
import sys

subprocess.run([
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--icon=icon.ico",
    "--name=Launcher",
    "--console",
    "--distpath=.",
    "--hidden-import=socks",
    "--hidden-import=requests",
    "launcher.py",
], check=True)

print("\nDone. Run ./Launcher (Linux/macOS) or Launcher.exe (Windows) to start Plamma.")
