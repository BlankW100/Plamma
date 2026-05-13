<p align="center">
  <img width="1280" height="640" alt="Plamma" src="https://github.com/user-attachments/assets/5f7aabe4-df51-43bf-99a9-6024ea9a5898" />
</p>

# Plamma

**Private · Local · Uncensored**

Plamma is a terminal-based AI assistant that runs entirely on your machine. It uses a locally hosted model via [Ollama](https://ollama.com), routes all web searches anonymously through [Tor](https://www.torproject.org), and keeps no data off your device. No accounts, no cloud, no logs.

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
| A compatible model | Any Ollama model works — **abliterated or uncensored models recommended** (standard models may refuse requests due to built-in safety filters) |
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

Download Ollama from [ollama.com](https://ollama.com).

#### Choosing a model

> **⚠ Important — read before pulling a model**
>
> Plamma's system prompt instructs the model to respond without filters or refusals.
> This works reliably **only on abliterated or uncensored models**.
> Standard models (Llama, Gemma, Qwen, DeepSeek, Mistral, etc.) have safety filters
> baked into their weights. Those filters **cannot be overridden by a system prompt** —
> the model will still refuse certain requests regardless of what Plamma tells it.

Look for model names containing keywords like:
`abliterated` · `uncensored` · `unfiltered` · `dolphin` · `openhermes` · `nous-hermes`

**Recommended models to try:**

```bash
# Abliterated (fine-tuned to remove refusal behaviour entirely)
ollama pull huihui_ai/gemma-4-abliterated
ollama pull huihui_ai/qwen3-abliterated

# Uncensored (trained on uncensored datasets)
ollama pull dolphin-llama3
ollama pull nous-hermes2
```

You can also use a standard model if you only need the search and privacy features and do not require unrestricted responses. The first-run setup will show all models you have downloaded and flag the recommended ones automatically.

### 4. Set up Tor (optional)

Download the [Tor Expert Bundle](https://www.torproject.org/download/tor/) and extract it.

Copy `torrc.example` to `torrc` and edit the paths to match your Tor installation:

```
SocksPort 9050
ControlPort 9051
```

Set your Tor paths in `plamma.env` (works on all platforms):

```bash
TOR_EXE=/path/to/tor
TOR_TORRC=/path/to/torrc
```

---

## Running Plamma

```bash
python launcher.py
```

This will check/start Tor, check/start Ollama, then launch Plamma — on Windows, macOS, and Linux.

### Run without the launcher

```bash
python plamma.py
```

---

## Configuration

Copy `plamma.env.example` to `plamma.env` and edit it — this is the easiest way to configure Plamma. The file is loaded automatically on startup.

```bash
cp plamma.env.example plamma.env
```

| Variable | Default | Description |
|---|---|---|
| `PLAMMA_MODEL` | `huihui_ai/gemma-4-abliterated:latest` | Ollama model to use |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `PLAMMA_CTX` | `2048` | Context window size (tokens) |
| `TOR_SOCKS_PORT` | `9050` | Tor SOCKS5 proxy port |
| `TOR_CONTROL_PORT` | `9051` | Tor control port |

Real environment variables always take priority over `plamma.env`. You can also switch models at runtime without editing any file — see `/model` below.

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

## Privacy Notes

- All web traffic from Plamma (search, stock data) routes through Tor when Tor is active
- Session vaults are encrypted at rest — no plaintext conversation data is ever written to disk
- Plamma does not phone home, send telemetry, or require authentication
- The model runs 100% locally via Ollama

---

## Disclaimer

Plamma is a privacy and research tool intended for lawful use such as security research, journalism, and academic investigation.

**Regarding uncensored and abliterated models:** These models are distributed by their respective authors and are not created or hosted by this project. Their unrestricted nature means they may produce content that would be filtered by standard models. You are solely responsible for how you use any output.

The developers of Plamma are not responsible for any misuse of this software or any content generated by the models it runs. You are responsible for complying with applicable laws in your jurisdiction.

---

## Forks and Third-Party Distributions

> **⚠ Warning — only trust the official repository**
>
> This project is open source and anyone may fork or redistribute it. The developers of Plamma **cannot verify the integrity or intent of any fork, mirror, or third-party distribution.**
>
> Malicious forks could silently modify `plamma.env` or source files to redirect your Ollama traffic to a remote server, exfiltrating your conversations.
>
> **Always:**
> - Clone from the official repository: `https://github.com/BlankW100/Plamma`
> - Verify the `OLLAMA_URL` in your `plamma.env` is set to `http://localhost:11434`
> - Treat any fork of unknown origin as untrusted
