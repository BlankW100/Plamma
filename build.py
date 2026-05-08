#!/usr/bin/env python3
"""
Build Launcher.exe (or Launcher on Linux/macOS) using PyInstaller.
Run: python build.py
"""
import subprocess
import sys
from pathlib import Path


def pause(msg="  Press Enter to close."):
    try:
        input(msg)
    except EOFError:
        pass


# Check PyInstaller is available
result = subprocess.run(
    [sys.executable, "-m", "PyInstaller", "--version"],
    capture_output=True,
)
if result.returncode != 0:
    print("  ERROR: PyInstaller not found.")
    print("  Fix:   pip install pyinstaller")
    pause()
    sys.exit(1)

# icon is optional — skip flag if not present
icon_args = ["--icon=icon.ico"] if Path("icon.ico").exists() else []

print("  Building Launcher...\n")
result = subprocess.run([
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    *icon_args,
    "--name=Launcher",
    "--console",
    "--distpath=.",
    "--hidden-import=socks",
    "--hidden-import=requests",
    "launcher.py",
])

print()
if result.returncode == 0:
    name = "Launcher.exe" if sys.platform == "win32" else "Launcher"
    print(f"  Done. Double-click {name} to start Plamma.")
else:
    print("  Build failed. Check the output above for details.")

pause()
