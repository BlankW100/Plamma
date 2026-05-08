import hashlib
import json
import random
from datetime import datetime
from pathlib import Path

SESSIONS_DIR  = Path.home() / ".plamma" / "sessions"
REGISTRY_PATH = SESSIONS_DIR / "registry.json"

_ADJECTIVES = [
    "amber", "arctic", "azure", "black", "blazing", "blind", "bright",
    "broken", "burning", "calm", "cold", "crimson", "dark", "dead",
    "deep", "dry", "dusk", "empty", "fallen", "fast", "feral", "fierce",
    "final", "fixed", "flash", "flat", "free", "frosted", "ghost", "gold",
    "grave", "grey", "grim", "hard", "hidden", "hollow", "ice", "iron",
    "jade", "last", "light", "lone", "lost", "low", "lunar", "mute",
    "naked", "night", "numb", "obsidian", "onyx", "pale", "phantom",
    "quiet", "raw", "red", "rising", "rogue", "rust", "scarlet", "shaded",
    "sharp", "silent", "silver", "slow", "smoke", "solar", "solid",
    "static", "steel", "still", "stray", "swift", "torn", "twilight",
    "twisted", "veiled", "violet", "void", "white", "wide", "wild",
    "winter", "worn", "zero",
]

_NOUNS = [
    "arrow", "ash", "aurora", "abyss", "basin", "beacon", "blade", "blaze",
    "bolt", "bridge", "canyon", "chain", "cipher", "circuit", "cliff",
    "cloud", "crater", "current", "dagger", "dawn", "delta", "dune",
    "dust", "echo", "edge", "ember", "epoch", "eye", "fang", "field",
    "flame", "flare", "frost", "gate", "ghost", "glacier", "grave", "grid",
    "harbor", "helix", "hill", "horizon", "hull", "husk", "iris", "key",
    "lake", "lance", "layer", "ledge", "lens", "light", "line", "link",
    "mast", "mirror", "moon", "mote", "needle", "nexus", "node", "nova",
    "null", "orbit", "peak", "point", "probe", "prism", "pulse", "radius",
    "ravine", "reef", "ridge", "rift", "ring", "river", "rock", "route",
    "rune", "shard", "shell", "shield", "shore", "signal", "silt", "sky",
    "slate", "smoke", "snow", "spark", "spine", "star", "stone", "storm",
    "strand", "stream", "summit", "surge", "tomb", "tower", "trace",
    "trail", "vault", "veil", "vortex", "wave", "wire", "wraith", "zone",
]


def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_registry(reg: dict):
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def _unique_codename(existing: set) -> str:
    for _ in range(200):
        name = f"{random.choice(_ADJECTIVES)}-{random.choice(_NOUNS)}"
        if name not in existing:
            return name
    # fallback: append a short hex suffix
    name = f"{random.choice(_ADJECTIVES)}-{random.choice(_NOUNS)}-{random.randint(10,99)}"
    return name


def _is_token(arg: str) -> bool:
    """Return True if arg looks like a Fernet key (44-char base64url), not a codename."""
    try:
        from cryptography.fernet import Fernet
        Fernet(arg.strip().encode())
        return True
    except Exception:
        return False


class Session:
    def __init__(self):
        self.messages: list[dict] = []
        self._started = datetime.now()

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def get_context(self) -> list[dict]:
        return list(self.messages)

    def clear(self):
        self.messages.clear()
        self._started = datetime.now()

    def is_empty(self) -> bool:
        return len(self.messages) == 0

    def save(self, path: str | None = None) -> Path:
        if path is None:
            ts = self._started.strftime("%Y%m%d_%H%M%S")
            path = f"plamma_session_{ts}.md"
        out = Path(path)
        lines = [
            "# Plamma Session\n",
            f"**Date:** {self._started.strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n",
        ]
        for msg in self.messages:
            if msg["role"] == "user":
                lines.append(f"**You:**\n{msg['content']}\n\n")
            elif msg["role"] == "assistant":
                lines.append(f"**Plamma:**\n{msg['content']}\n\n---\n\n")
        out.write_text("".join(lines), encoding="utf-8")
        return out

    def save_encrypted(self) -> tuple[str, str]:
        """
        Encrypt and save the session.
        Returns (token, codename).

        The token is the only decryption key — it is never stored anywhere.
        The codename is a human-readable alias stored in the registry.
        The session file is named sha256(token)[:24] — reveals nothing without the token.
        """
        from cryptography.fernet import Fernet

        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

        key = Fernet.generate_key()
        session_id = hashlib.sha256(key).hexdigest()[:24]

        data = {
            "started": self._started.isoformat(),
            "messages": self.messages,
        }
        encrypted = Fernet(key).encrypt(json.dumps(data).encode("utf-8"))
        (SESSIONS_DIR / f"{session_id}.plamma").write_bytes(encrypted)

        reg = _load_registry()
        codename = _unique_codename(set(reg.keys()))
        reg[codename] = session_id
        _save_registry(reg)

        return key.decode(), codename

    @classmethod
    def load_by_token(cls, token: str) -> "Session":
        """Load directly by Fernet token."""
        from cryptography.fernet import Fernet

        key = token.strip().encode()
        session_id = hashlib.sha256(key).hexdigest()[:24]
        path = SESSIONS_DIR / f"{session_id}.plamma"

        if not path.exists():
            raise FileNotFoundError("No session found for this token.")

        data = json.loads(Fernet(key).decrypt(path.read_bytes()))
        s = cls()
        s.messages = data["messages"]
        s._started = datetime.fromisoformat(data["started"])
        return s

    @classmethod
    def load_by_codename(cls, codename: str, token: str) -> "Session":
        """
        Load by codename + token.
        Verifies the token matches the session registered under that codename
        before attempting decryption.
        """
        from cryptography.fernet import Fernet

        reg = _load_registry()
        if codename not in reg:
            raise KeyError(f"No session with codename '{codename}'.")

        expected_id = reg[codename]
        key = token.strip().encode()
        actual_id = hashlib.sha256(key).hexdigest()[:24]

        if actual_id != expected_id:
            raise ValueError("Token does not match this codename.")

        path = SESSIONS_DIR / f"{expected_id}.plamma"
        if not path.exists():
            raise FileNotFoundError("Session file is missing.")

        data = json.loads(Fernet(key).decrypt(path.read_bytes()))
        s = cls()
        s.messages = data["messages"]
        s._started = datetime.fromisoformat(data["started"])
        return s

    @classmethod
    def delete_session(cls, codename: str) -> bool:
        """Delete the session file and remove the codename from the registry."""
        reg = _load_registry()
        if codename not in reg:
            return False

        session_id = reg.pop(codename)
        path = SESSIONS_DIR / f"{session_id}.plamma"
        if path.exists():
            path.unlink()

        _save_registry(reg)
        return True

    @classmethod
    def list_codenames(cls) -> list[str]:
        return sorted(_load_registry().keys())

    @classmethod
    def nuke_sessions(cls):
        """Delete all session files and the registry."""
        import shutil
        if SESSIONS_DIR.exists():
            shutil.rmtree(SESSIONS_DIR)
