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


def _hash_codename(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]


def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        try:
            reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            # Migrate old format: {codename: session_id_str} → hashed-key format
            if reg and isinstance(next(iter(reg.values())), str):
                new_reg: dict = {}
                for name, sid in reg.items():
                    new_reg[_hash_codename(name)] = {
                        "id": sid, "name": name, "saved_at": "unknown"
                    }
                _save_registry(new_reg)
                return new_reg
            return reg
        except Exception:
            return {}
    return {}


def _save_registry(reg: dict):
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def _unique_codename(reg: dict) -> str:
    existing = {entry["name"] for entry in reg.values()}
    for _ in range(200):
        name = f"{random.choice(_ADJECTIVES)}-{random.choice(_NOUNS)}"
        if name not in existing:
            return name
    return f"{random.choice(_ADJECTIVES)}-{random.choice(_NOUNS)}-{random.randint(10, 99)}"


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
        Encrypt and save the session. Returns (token, codename).
        Token = Fernet key — never stored anywhere.
        Registry stores sha256(codename)[:24] as the key, hiding codenames from
        casual inspection; the readable name is stored only in the value.
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
        codename = _unique_codename(reg)
        reg[_hash_codename(codename)] = {
            "id":       session_id,
            "name":     codename,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        _save_registry(reg)

        return key.decode(), codename

    @classmethod
    def load_by_token(cls, token: str) -> "Session":
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
        from cryptography.fernet import Fernet

        reg = _load_registry()
        entry = reg.get(_hash_codename(codename))
        if not entry:
            raise KeyError(f"No session with codename '{codename}'.")

        key = token.strip().encode()
        if hashlib.sha256(key).hexdigest()[:24] != entry["id"]:
            raise ValueError("Token does not match this codename.")

        path = SESSIONS_DIR / f"{entry['id']}.plamma"
        if not path.exists():
            raise FileNotFoundError("Session file is missing.")

        data = json.loads(Fernet(key).decrypt(path.read_bytes()))
        s = cls()
        s.messages = data["messages"]
        s._started = datetime.fromisoformat(data["started"])
        return s

    @classmethod
    def delete_session(cls, codename: str) -> bool:
        reg = _load_registry()
        entry = reg.pop(_hash_codename(codename), None)
        if not entry:
            return False
        path = SESSIONS_DIR / f"{entry['id']}.plamma"
        if path.exists():
            path.unlink()
        _save_registry(reg)
        return True

    @classmethod
    def list_sessions(cls) -> list[tuple[str, str]]:
        """Return [(codename, saved_at)] sorted by name. Read-only — no tokens exposed."""
        reg = _load_registry()
        return sorted(
            [(e["name"], e.get("saved_at", "unknown")) for e in reg.values()],
            key=lambda x: x[0],
        )

    @classmethod
    def list_codenames(cls) -> list[str]:
        return [name for name, _ in cls.list_sessions()]

    @classmethod
    def nuke_sessions(cls):
        import shutil
        if SESSIONS_DIR.exists():
            shutil.rmtree(SESSIONS_DIR)
