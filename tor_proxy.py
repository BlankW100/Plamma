import os
import requests

SOCKS5_HOST      = os.environ.get("TOR_SOCKS_HOST", "127.0.0.1")
SOCKS5_PORT      = int(os.environ.get("TOR_SOCKS_PORT", "9050"))
TOR_CONTROL_PORT = int(os.environ.get("TOR_CONTROL_PORT", "9051"))

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Accept-Language": "en-US,en;q=0.5",
}


def get_session() -> requests.Session:
    s = requests.Session()
    proxy = f"socks5h://{SOCKS5_HOST}:{SOCKS5_PORT}"
    s.proxies = {"http": proxy, "https": proxy}
    s.headers.update(_HEADERS)
    return s


def check_tor() -> bool:
    """Returns True only when Tor is running AND circuits are built (can route traffic)."""
    import socket
    try:
        c = socket.create_connection(("127.0.0.1", SOCKS5_PORT), timeout=1)
        c.close()
    except Exception:
        return False
    try:
        s = get_session()
        r = s.get("https://check.torproject.org/api/ip", timeout=15)
        return r.json().get("IsTor", False)
    except Exception:
        return False


def new_identity() -> tuple[bool, str]:
    try:
        from stem import Signal
        from stem.control import Controller

        with Controller.from_port(port=TOR_CONTROL_PORT) as ctrl:
            ctrl.authenticate()
            ctrl.signal(Signal.NEWNYM)
        return True, "New Tor circuit acquired."
    except ImportError:
        return False, "stem not installed. Run: pip install stem"
    except Exception as e:
        return False, f"Control port error: {e}\nEnsure torrc has: ControlPort {TOR_CONTROL_PORT}"
