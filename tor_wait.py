"""
Used by launcher.bat to block until Tor circuits are ready.
Exit 0 = Tor is up and routing traffic.
Exit 1 = not ready yet.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from tor_proxy import check_tor
sys.exit(0 if check_tor() else 1)
