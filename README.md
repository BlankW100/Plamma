# Plamma

**Private · Local · Uncensored**

Plamma is a terminal-based AI assistant that runs entirely on your machine. It uses a locally hosted model via [Ollama](https://ollama.com), routes all web searches anonymously through [Tor](https://www.torproject.org), and keeps no data off your device. No accounts, no cloud, no logs.

```
 ____  _        _    __  __  __  __    _
|  _ \| |      / \  |  \/  ||  \/  |  / \
| |_) | |     / _ \ | |\/| || |\/| | / _ \
|  __/| |___ / ___ \| |  | || |  | |/ ___ \
|_|   |_____/_/   \_\_|  |_||_|  |_/_/   \_\
```

---

## Features

- **Fully local** — model runs on your hardware via Ollama, nothing is sent to external servers
- **Anonymous search** — surface web and dark web (.onion) searches route through Tor
- **Encrypted session vaults** — save and restore conversations with a one-time token; no plaintext ever touches disk
- **Image analysis** — send images to the model for visual question answering
- **Auto-search** — detects live-data intent in messages and searches automatically
- **Self-destruct** — `/nuke` wipes all session data and removes the program, leaving nothing behind

---

## Requirements

| Requirement | Notes |
|---|---|
| [Python 3.10+](https://www.python.org/downloads/) | For running from source |
| [Ollama](https://ollama.com) | Local LLM runtime |
| A compatible model | Default: `huihui_ai/gemma-4-abliterated` — any Ollama model works |
| [Tor](https://www.torproject.org/download/) | For anonymous search (optional but recommended) |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/BlankW100/Plamma.git
cd Plamma
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install and start Ollama

Download Ollama from [ollama.com](https://ollama.com), then pull a model:

```bash
ollama pull huihui_ai/gemma-4-abliterated
```

Any other Ollama model works — set the `PLAMMA_MODEL` environment variable to use a different one (see [Configuration](#configuration)).

### 4. Set up Tor (optional)

Download the [Tor Expert Bundle](https://www.torproject.org/download/tor/) and extract it.

Copy `torrc.example` to `torrc` and edit the paths to match your Tor installation:

```
SocksPort 9050
ControlPort 9051
```

On **Windows**, update `launcher.bat` with your Tor paths:

```batch
set "TOR_EXE=C:\path\to\tor.exe"
set "TOR_TORRC=C:\path\to\torrc"
```

---

## Running Plamma

### Windows (recommended)

Double-click `launcher.bat`. It will:
1. Check if Tor is running and wait for circuits to build
2. Start Ollama if it is not already running
3. Launch Plamma

### From source (any platform)

```bash
python plamma.py
```

---

## Configuration

All configuration is done through environment variables — no config file to edit.

| Variable | Default | Description |
|---|---|---|
| `PLAMMA_MODEL` | `huihui_ai/gemma-4-abliterated:latest` | Ollama model to use |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `PLAMMA_CTX` | `2048` | Context window size (tokens) |
| `TOR_SOCKS_PORT` | `9050` | Tor SOCKS5 proxy port |
| `TOR_CONTROL_PORT` | `9051` | Tor control port |

**Custom system prompt** — create a `system_prompt.txt` file in the Plamma directory. If present, it overrides the built-in system prompt entirely.

---

## Commands

| Command | Description |
|---|---|
| `/s <query>` | Search surface web via Tor, then answer |
| `/d <query>` | Search dark web (.onion) via Tor, then answer |
| `/sd <query>` | Search both, then answer |
| `/img` | Open file picker to choose an image |
| `/img <path> [question]` | Analyze an image directly |
| `/showthink` | Toggle display of model reasoning |
| `/session -s` | Encrypt and save session — prints codename + token |
| `/session -c <token>` | Restore session by token |
| `/session -c <codename>` | Restore session by codename (prompts for token) |
| `/session -d <codename>` | Delete a saved session permanently |
| `/log [file]` | Export session to plaintext markdown |
| `/clear` | Wipe in-memory chat history |
| `/tor` | Check Tor connection status |
| `/newtor` | Rotate Tor circuit (new exit node) |
| `/model` | Show current model |
| `/nuke` | Delete all sessions + self-destruct (prompts confirm) |
| `/nuke -f` | Same as `/nuke` but skips confirmation |
| `/h <command>` | Detailed help for a command |
| `/help` | Show command list |
| `/exit` | Exit Plamma |

Type `/h session`, `/h nuke`, `/h s`, `/h img`, or `/h tor` for detailed explanations.

---

## Encrypted Sessions

Plamma's session system is designed for users who need privacy beyond a standard chat log.

**Saving:**
```
/session -s
```
Outputs:
```
  Codename : silent-vortex
  Token    : <44-character key>
```

The session is encrypted with a randomly generated [Fernet](https://cryptography.io/en/latest/fernet/) key. The vault file is stored at `~/.plamma/sessions/` and named after a hash of the token — revealing nothing without the key. **The token is never stored anywhere.** Lose it, and the session is permanently unreadable.

**Restoring:**
```
/session -c <token>
/session -c silent-vortex        ← prompts for token
```

**Deleting:**
```
/session -d silent-vortex
```

---

## Auto-Search

Plamma automatically searches the web when it detects live-data intent in a message. This triggers on:

- **Keywords** — `price`, `news`, `latest`, `today`, `stock`, `weather`, `current`, `internet`, `online`, etc.
- **Phrases** — `"search for"`, `"find me"`, `"look up"`, `"check online"`, `"tell me the latest"`, `"research"`, etc.

Use `/s`, `/d`, or `/sd` to force a search regardless of content.

---

## Self-Destruct

```
/nuke
```

Deletes all session vaults and then removes the entire Plamma directory. A detached background process handles the final cleanup after Plamma exits. Use `/nuke -f` to skip the confirmation prompt.

> This cannot be undone. Use `/session -d <codename>` to remove individual sessions instead.

---

## Privacy Notes

- All web traffic from Plamma (search, stock data) routes through Tor when Tor is active
- Session vaults are encrypted at rest — no plaintext conversation data is ever written to disk
- Plamma does not phone home, send telemetry, or require authentication
- The model runs 100% locally via Ollama

---

## Disclaimer

Plamma is a privacy and research tool. You are responsible for how you use it and for complying with applicable laws in your jurisdiction. The developers are not responsible for any misuse.
