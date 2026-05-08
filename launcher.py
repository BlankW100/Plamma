#!/usr/bin/env python3
"""
Plamma launcher — cross-platform.
1. Check / start Tor, wait for circuits.
2. Check / start Ollama.
3. Launch Plamma (compiled exe or plamma.py from source).
"""
import os
import sys
import shutil
import socket
import subprocess
import time
from pathlib import Path

# ── UTF-8 output ──────────────────────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _apply_window_icon():
    """Set the console window icon (taskbar + title bar) to icon.ico on Windows."""
    if sys.platform != "win32":
        return
    import ctypes
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    icon_path = os.path.join(base, "icon.ico")
    if not os.path.exists(icon_path):
        return
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if not hwnd:
        return
    hicon = ctypes.windll.user32.LoadImageW(
        None, icon_path, 1, 0, 0, 0x0010 | 0x0040
    )
    if hicon:
        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, hicon)
        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, hicon)


_apply_window_icon()

# ── Base directory ────────────────────────────────────────────────────────────
# Compiled with PyInstaller: sys.executable IS the .exe — use its directory.
# Running from source:       __file__ is launcher.py — use its directory.
BASE: Path = (
    Path(sys.executable).parent
    if getattr(sys, "frozen", False)
    else Path(__file__).parent
)

IS_WIN   = sys.platform == "win32"
IS_MAC   = sys.platform == "darwin"

# ── Load plamma.env ───────────────────────────────────────────────────────────
def _load_env():
    env_file = BASE / "plamma.env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and k not in os.environ:
                os.environ[k] = v

_load_env()

SOCKS_PORT   = int(os.environ.get("TOR_SOCKS_PORT",   "9050"))
OLLAMA_PORT  = 11434

# ── Port / Tor helpers ────────────────────────────────────────────────────────
def _port_open(port: int, timeout: float = 0.8) -> bool:
    try:
        c = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        c.close()
        return True
    except Exception:
        return False


def _is_tor_routing() -> bool:
    """True only when Tor port is open AND circuits are built (traffic actually routes)."""
    if not _port_open(SOCKS_PORT):
        return False
    try:
        import requests
        proxies = {
            "http":  f"socks5h://127.0.0.1:{SOCKS_PORT}",
            "https": f"socks5h://127.0.0.1:{SOCKS_PORT}",
        }
        r = requests.get(
            "https://check.torproject.org/api/ip",
            proxies=proxies,
            timeout=15,
        )
        return r.json().get("IsTor", False)
    except Exception:
        return False


# ── Tor path detection ────────────────────────────────────────────────────────
def _find_tor() -> tuple[str | None, str | None]:
    """
    Return (tor_exe_path, torrc_path).
    Respects TOR_EXE / TOR_TORRC env vars set in plamma.env or the environment.
    Falls back to platform-specific default locations and PATH.
    """
    tor_exe   = os.environ.get("TOR_EXE")
    tor_torrc = os.environ.get("TOR_TORRC")

    if tor_exe and Path(tor_exe).exists() and tor_torrc:
        return tor_exe, tor_torrc

    # ── Candidate locations per platform ─────────────────────────────────────
    if IS_WIN:
        home = Path(os.environ.get("USERPROFILE", Path.home()))
        exe_candidates = [
            home / "tor" / "tor" / "tor.exe",
            Path(os.environ.get("APPDATA", "")) / "tor" / "tor" / "tor.exe",
            Path("C:/tor/tor/tor.exe"),
            Path("C:/Program Files/Tor/tor.exe"),
        ]
        rc_candidates = [
            home / "tor" / "torrc",
            Path(os.environ.get("APPDATA", "")) / "tor" / "torrc",
            BASE / "torrc",
        ]
    elif IS_MAC:
        exe_candidates = [
            Path("/opt/homebrew/bin/tor"),   # Homebrew ARM (M1/M2)
            Path("/usr/local/bin/tor"),      # Homebrew Intel
            Path("/usr/bin/tor"),
        ]
        rc_candidates = [
            Path("/opt/homebrew/etc/tor/torrc"),
            Path("/usr/local/etc/tor/torrc"),
            Path("/etc/tor/torrc"),
            Path.home() / ".torrc",
            BASE / "torrc",
        ]
    else:  # Linux
        exe_candidates = [
            Path("/usr/bin/tor"),
            Path("/usr/sbin/tor"),
            Path("/usr/local/bin/tor"),
            Path("/snap/bin/tor"),
        ]
        rc_candidates = [
            Path("/etc/tor/torrc"),
            Path.home() / ".torrc",
            BASE / "torrc",
        ]

    # PATH lookup covers any non-standard install (e.g. virtual env, custom prefix)
    path_tor = shutil.which("tor")
    if path_tor:
        exe_candidates.insert(0, Path(path_tor))

    found_exe  = next((str(p) for p in exe_candidates if p.exists()), None)
    found_rc   = next((str(p) for p in rc_candidates  if p.exists()), None)

    return (tor_exe or found_exe), (tor_torrc or found_rc)


# ── Start helpers ─────────────────────────────────────────────────────────────
def _start_background(cmd: list[str]):
    """Start a process in the background with no visible window."""
    if IS_WIN:
        subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


# ── Display ───────────────────────────────────────────────────────────────────
def _cls():
    os.system("cls" if IS_WIN else "clear")


_COMPACT_BANNER = r"""
    ____  _
   |  _ \| | __ _ _ __ ___  _ __ ___   __ _
   | |_) | |/ _` | '_ ` _ \| '_ ` _ \ / _` |
   |  __/| | (_| | | | | | | | | | | | (_| |
   |_|   |_|\__,_|_| |_| |_|_| |_| |_|\__,_|
   Private · Local · Uncensored
"""


def _banner():
    print(_COMPACT_BANNER)


def _step(n: int, name: str, msg: str):
    print(f"  [{n}/3]  {name:<8} ....  {msg}", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if IS_WIN:
        os.system("chcp 65001 >nul 2>&1")

    _cls()
    _banner()

    # ── [1/3] Tor ─────────────────────────────────────────────────────────────
    if _is_tor_routing():
        _step(1, "Tor", "already running")
    else:
        tor_exe, torrc = _find_tor()

        if _port_open(SOCKS_PORT):
            # Port is open but circuits not built yet — just wait
            _step(1, "Tor", "building circuits ...")
        elif tor_exe:
            _step(1, "Tor", "starting ...")
            cmd = [tor_exe] + (["-f", torrc] if torrc else [])
            _start_background(cmd)
        else:
            _step(1, "Tor", "NOT FOUND — searches will not be anonymous")
            print(
                "         Install Tor and set TOR_EXE / TOR_TORRC in plamma.env\n"
                "         or as environment variables.\n"
            )

        # Wait for circuits (skip if Tor was not found at all)
        if tor_exe or _port_open(SOCKS_PORT):
            print("         Waiting for circuits", end="", flush=True)
            ready = False
            for _ in range(60):           # 60 × 4 s = up to 4 minutes
                time.sleep(4)
                print(".", end="", flush=True)
                if _is_tor_routing():
                    ready = True
                    break
            print()
            _step(1, "Tor", "ready" if ready else "timeout — continuing without Tor")

    # ── [2/3] Ollama ──────────────────────────────────────────────────────────
    if _port_open(OLLAMA_PORT):
        _step(2, "Ollama", "already running")
    else:
        ollama = shutil.which("ollama")
        if not ollama:
            # Common non-PATH install locations
            candidates = (
                [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"]
                if IS_WIN else []
            )
            ollama = next((str(p) for p in candidates if p.exists()), None)

        if not ollama:
            _step(2, "Ollama", "NOT FOUND")
            print("         Install Ollama from https://ollama.com")
            input("\n  Press Enter to exit.")
            sys.exit(1)

        _step(2, "Ollama", "starting ...")
        _start_background([ollama, "serve"])

        print("         Waiting for Ollama", end="", flush=True)
        ready = False
        for _ in range(30):              # 30 × 2 s = up to 60 seconds
            time.sleep(2)
            print(".", end="", flush=True)
            if _port_open(OLLAMA_PORT):
                ready = True
                break
        print()

        if ready:
            _step(2, "Ollama", "ready")
        else:
            _step(2, "Ollama", "failed to start")
            input("\n  Press Enter to exit.")
            sys.exit(1)

    # ── [3/3] Plamma ──────────────────────────────────────────────────────────
    _step(3, "Plamma", "launching ...")
    print()

    # Look for a compiled Plamma exe first (dist/ subdir, then same dir as launcher)
    if IS_WIN:
        exe_name = "Plamma.exe"
    else:
        exe_name = "Plamma"

    plamma_exe = BASE / "dist" / exe_name
    if not plamma_exe.exists():
        plamma_exe = BASE / exe_name

    if plamma_exe.exists():
        subprocess.run([str(plamma_exe)])
    else:
        # Fall back: run from source with the current Python interpreter
        plamma_script = BASE / "plamma.py"
        if not plamma_script.exists():
            print("  ERROR: Cannot find plamma.py or a compiled Plamma executable.")
            print(f"  Expected: {plamma_exe}  or  {plamma_script}")
            input("  Press Enter to exit.")
            sys.exit(1)
        subprocess.run([sys.executable, str(plamma_script)])

    print()
    print("  Session ended.")
    input("  Press Enter to close.")


if __name__ == "__main__":
    main()
