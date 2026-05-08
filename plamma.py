#!/usr/bin/env python3
import sys
import os
import re
import io
import base64
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# Force UTF-8 so spinner frames and box-drawing characters render correctly
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")


def _apply_window_icon():
    """Set the console window icon to icon.ico so it shows in the taskbar."""
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
        None, icon_path, 1, 0, 0, 0x0010 | 0x0040  # IMAGE_ICON, LR_LOADFROMFILE | LR_DEFAULTSIZE
    )
    if hicon:
        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, hicon)  # WM_SETICON SMALL
        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, hicon)  # WM_SETICON BIG


_apply_window_icon()

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import requests
import llm
from llm import get_system_prompt, check_ollama, stream_response, should_search, OFFLINE_NOTICE
from search import (
    search_surface, search_dark, search_i2p, fetch_url_content,
    format_for_llm, format_citations,
    needs_live_data, fetch_finviz, resolve_time_query,
)
from session import Session
from tor_proxy import check_tor, new_identity

console = Console()

BANNER = r"""
 ____  _        _    __  __ __  __    _    
|  _ \| |      / \  |  \/  |  \/  |  / \   
| |_) | |     / _ \ | |\/| | |\/| | / _ \  
|  __/| |___ / ___ \| |  | | |  | |/ ___ \ 
|_|   |_____/_/   \_\_|  |_|_|  |_/_/   \_\
"""

HELP_TEXT = """\
[bold cyan]Commands[/bold cyan]
  [yellow]/s <query>[/yellow]                   Search surface web via Tor, then answer
  [yellow]/d <query>[/yellow]                   Search dark web (.onion) via Tor, then answer
  [yellow]/sd <query>[/yellow]                  Search both, then answer
  [yellow]/d2 <query>[/yellow]                  Search I2P network (.i2p eepsites)
  [yellow]/fetch <url>[/yellow]                 Fetch a URL through Tor and analyse it
  [yellow]/doc <path>[/yellow]                  Analyse a local document (txt md pdf csv...)
  [yellow]/img[/yellow]                         Open file picker — choose an image, then ask a question
  [yellow]/showthink[/yellow]                   Toggle: show or hide the model's thinking process
  [yellow]/toriso[/yellow]                      Toggle: rotate Tor circuit before every search
  [yellow]/session -s[/yellow]                  Encrypt & save session — prints codename + one-time token
  [yellow]/session -c \\[token][/yellow]          Restore session directly by token
  [yellow]/session -c \\[codename][/yellow]       Restore session by codename (prompts for token)
  [yellow]/session -d \\[codename][/yellow]       Permanently delete a saved session
  [yellow]/log \\[file][/yellow]                  Export session to plaintext markdown
  [yellow]/clear[/yellow]                       Wipe in-memory chat history
  [yellow]/tor[/yellow]                         Check Tor connection status
  [yellow]/newtor[/yellow]                      Rotate Tor circuit (new exit node)
  [yellow]/model[/yellow]                       Show current model
  [yellow]/model -a[/yellow]                    List all downloaded models (highlights recommended)
  [yellow]/model \\[name][/yellow]               Switch to a different model + save to plamma.env
  [yellow]/nuke[/yellow]                        Delete all sessions + self-destruct (prompts confirm)
  [yellow]/nuke -f[/yellow]                     Same as /nuke but skips confirmation
  [yellow]/h \\[command][/yellow]                 Detailed help for a specific command
  [yellow]/help[/yellow]                        Show this help
  [yellow]/exit[/yellow]                        Exit Plamma

[dim]Auto-search triggers on keywords like: price, news, latest, current, today...[/dim]
[dim]Also triggers on phrases like: "search for", "find me", "look up", "check online".[/dim]
[dim]Use /s /d /sd /d2 to force a specific search type regardless.[/dim]
[dim]Type /h fetch   /h doc   /h d2   /h toriso   /h session   /h s   /h img   for detailed help.[/dim]
"""

DETAILED_HELP: dict[str, str] = {
    "session": """\
[bold cyan]/session[/bold cyan] — Encrypted session vault

  [yellow]/session -s[/yellow]
    Encrypts the current conversation and saves it to [dim]~/.plamma/sessions/[/dim]
    Prints a [bold]codename[/bold] (e.g. [cyan]silent-vortex[/cyan]) and a [bold]token[/bold] (44-char key).
    Store both safely — the token is [bold red]never saved anywhere[/bold red] and cannot be recovered.
    The vault file is named after a hash of the token, not a passphrase — reveals nothing without the token.

  [yellow]/session -c \\[token][/yellow]
    Restores a session directly using the 44-char token you saved.

  [yellow]/session -c \\[codename][/yellow]
    Looks up the vault by codename, then prompts for the token inline.
    Useful when you remember the codename but want to avoid pasting the token visibly.
    The token is verified against the stored hash before any decryption attempt.

  [yellow]/session -d \\[codename][/yellow]
    Permanently deletes the vault file and removes the codename from the registry.
    Irreversible — the encrypted data is gone.

[dim]No plaintext is ever written to disk. Lose the token = lose the session, permanently.[/dim]""",

    "nuke": """\
[bold red]/nuke[/bold red] — Full self-destruct

  Wipes all saved session vaults, then deletes the entire Plamma directory.
  Nothing is left on the machine after completion.

  [yellow]/nuke[/yellow]      Prompts: type [bold]YES[/bold] (exact, uppercase) to confirm.
  [yellow]/nuke -f[/yellow]   Force — skips confirmation, executes immediately.

  A detached background process handles deletion after Plamma exits, so the
  running executable can be removed too.

[dim]Cannot be undone. Use /session -d \\[codename] to remove individual vaults instead.[/dim]""",

    "log": """\
[bold cyan]/log[/bold cyan] — Export session to plaintext Markdown

  [yellow]/log[/yellow]              Saves to [dim]plamma_session_YYYYMMDD_HHMMSS.md[/dim] in the current folder.
  [yellow]/log myfile.md[/yellow]    Saves to the specified path.

  Output is [bold]readable plaintext[/bold] — not encrypted.
  Do not use this for sensitive research. Use [yellow]/session -s[/yellow] for encrypted saves.""",

    "s": """\
[bold cyan]/s  /d  /sd[/bold cyan] — Web search via Tor

  [yellow]/s <query>[/yellow]    Surface web only — anonymous via Tor (DuckDuckGo HTML).
  [yellow]/d <query>[/yellow]    Dark web .onion only — via Tor (Ahmia, Haystak).
  [yellow]/sd <query>[/yellow]   Both surfaces simultaneously.

  Results are injected into the model's context with inline citations \\[1], \\[2]...
  Sources are listed at the end of the response.

[dim]Auto-search triggers when your message contains live-data keywords (price, news,
latest, current, today...) or explicit phrases (search for, find me, look up, etc.)[/dim]""",

    "img": """\
[bold cyan]/img[/bold cyan] — Image analysis

  [yellow]/img[/yellow]                                    Opens a file picker dialog.
  [yellow]/img C:\\\\path\\\\to\\\\file.jpg[/yellow]              Analyzes the image directly.
  [yellow]/img C:\\\\path\\\\to\\\\file.jpg \\[question][/yellow]  Custom question about the image.

  Supported formats: JPG, PNG, GIF, BMP, WEBP.
  The image is base64-encoded and sent to the model in-context.""",

    "tor": """\
[bold cyan]/tor  /newtor[/bold cyan] — Tor circuit management

  [yellow]/tor[/yellow]       Checks whether Tor is active and routing traffic correctly.
  [yellow]/newtor[/yellow]    Requests a new circuit (new exit node / new anonymous IP).

  All search commands (/s /d /sd) route through Tor automatically.
  If Tor is not running, searches still work but traffic is [bold red]NOT anonymous[/bold red].

[dim]Configure Tor path in launcher.bat via TOR_EXE and TOR_TORRC variables.[/dim]""",

    "model": """\
[bold cyan]/model[/bold cyan] — Model management

  [yellow]/model[/yellow]              Show the currently active model.
  [yellow]/model -a[/yellow]           List all models downloaded on this machine.
                      [bold green]★[/bold green] marks abliterated / uncensored models — recommended for full functionality.
  [yellow]/model \\[name][/yellow]      Switch to the specified model immediately and save to plamma.env.

[dim]Model preference is saved in plamma.env in the Plamma directory.
You can also set PLAMMA_MODEL as an environment variable to override it.[/dim]

[bold yellow]⚠  Compatibility note[/bold yellow]
Plamma's system prompt instructs the model to respond without filters.
This works reliably only on [bold]abliterated or uncensored[/bold] models.
Standard models (Llama, Gemma, Qwen, DeepSeek, Mistral base, etc.) have
safety filters baked into their weights. Those filters [bold]cannot be overridden
by a system prompt[/bold] — the model will still refuse certain requests.
Recommended keywords to look for in a model name:
  [cyan]abliterated · uncensored · unfiltered · dolphin · openhermes · nous-hermes[/cyan]""",

    "fetch": """\
[bold cyan]/fetch[/bold cyan] — Fetch a URL through Tor and analyse it

  [yellow]/fetch <url>[/yellow]
    Downloads the page through Tor (anonymous), strips scripts/ads/nav,
    and feeds the cleaned text to the model for analysis or Q&A.
    Supports http:// and https://. Onion URLs (.onion) also work via Tor.

  After fetching, you can ask follow-up questions — the page content stays
  in the session context.

[dim]Content is truncated at ~8 000 characters if the page is very large.[/dim]
[dim]No browser fingerprint — request goes out as a plain Tor circuit.[/dim]""",

    "doc": """\
[bold cyan]/doc[/bold cyan] — Analyse a local document

  [yellow]/doc <path>[/yellow]
    Reads the file and feeds its content to the model.
    Supported formats: [cyan]txt  md  py  csv  json  log  html  xml  yaml  toml[/cyan]
    PDF support requires:  [yellow]pip install pypdf[/yellow]

  The document content is added to context — follow-up questions work.
  Large files are truncated to fit the model's context window.

[dim]The file never leaves your machine — it is only passed to the local Ollama model.[/dim]""",

    "d2": """\
[bold cyan]/d2[/bold cyan] — Search I2P network

  [yellow]/d2 <query>[/yellow]
    Searches .i2p eepsites via the local I2P HTTP proxy (default port 4444).
    I2P is a separate anonymity network from Tor — different threat model,
    different sites, slower but more resistant to traffic analysis.

  Requires I2P to be installed and running:
    Windows: [dim]https://geti2p.net/en/download[/dim]
    The I2P router must be started before running this command.
    Default proxy: [dim]http://127.0.0.1:4444[/dim]  (override: [yellow]I2P_HTTP_PORT[/yellow] in plamma.env)

[dim]I2P has higher latency than Tor (5–30 s per query is normal).[/dim]
[dim]Dark web (.onion) searches still use /d via Tor.[/dim]""",

    "toriso": """\
[bold cyan]/toriso[/bold cyan] — Circuit isolation mode

  [yellow]/toriso[/yellow]    Toggle on/off. When ON, Plamma requests a new Tor circuit
            (new exit node, new identity) before every search or /fetch call.
            This prevents different queries from being linked to the same circuit.

  [bold]When to use it:[/bold]
    Sensitive research sessions where you don't want queries correlated.
    Any session where timing analysis of your Tor traffic is a concern.

  [bold]Cost:[/bold] adds 2–10 seconds before each search while Tor rebuilds circuits.

[dim]Same as running /newtor before every search, but automatic.[/dim]
[dim]Has no effect if Tor is not running.[/dim]""",
}


# ── model helpers ─────────────────────────────────────────────────────────────

_UNCENSORED_SIGNALS = {
    "abliterat",       # covers abliterated / abliteration
    "uncensored",
    "unfiltered",
    "dolphin",
    "openhermes",
    "nous-hermes",
    "wizard-vicuna",
    "jailbreak",
    "unrestricted",
    "natasi",
    "dark-",
}


def _is_recommended(model_name: str) -> tuple[bool, str]:
    """Return (is_recommended, matched_signal) for a model name."""
    low = model_name.lower()
    for sig in _UNCENSORED_SIGNALS:
        if sig in low:
            label = sig.replace("abliterat", "abliterated").rstrip("-")
            return True, label
    return False, ""


def _fetch_models() -> list[str]:
    """Return list of model names installed in Ollama, or [] on failure."""
    try:
        r = requests.get(f"{llm.OLLAMA_URL}/api/tags", timeout=5)
        if r.ok:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


def _save_model_config(model_name: str):
    """Write / update PLAMMA_MODEL in plamma.env."""
    env_path = Path(__file__).parent / "plamma.env"
    lines: list[str] = []
    found = False
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("PLAMMA_MODEL="):
                lines.append(f"PLAMMA_MODEL={model_name}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"PLAMMA_MODEL={model_name}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _first_run_picker(ollama_ok: bool):
    """Interactive model picker shown when plamma.env does not exist yet."""
    if not ollama_ok:
        return

    models = _fetch_models()
    if not models:
        return

    console.print("\n[bold cyan]First-run setup[/bold cyan] — no model configured.\n")
    console.print(
        "[bold yellow]⚠  Important[/bold yellow]\n"
        "Plamma is built for [bold]abliterated or uncensored[/bold] models.\n"
        "Standard models (Llama, Gemma, Qwen, DeepSeek, Mistral, etc.) have\n"
        "safety filters baked into their weights that [bold red]cannot be bypassed[/bold red]\n"
        "by a system prompt — they will still refuse certain requests.\n\n"
        "Look for model names containing:\n"
        "  [cyan]abliterated · uncensored · unfiltered · dolphin · openhermes[/cyan]\n"
    )
    console.print("[bold]Models installed on this machine:[/bold]\n")

    for i, name in enumerate(models, 1):
        rec, label = _is_recommended(name)
        if rec:
            console.print(f"  [bold green][{i:2}] ★ {name}[/bold green]  [dim]← {label}[/dim]")
        else:
            console.print(f"       [{i:2}]   {name}")

    console.print(
        "\n[dim][bold green]★[/bold green] = recommended (unrestricted model)[/dim]\n"
        "[dim]Press Enter to skip and use the built-in default.[/dim]"
    )
    sys.stdout.write("\n  Pick a number: ")
    sys.stdout.flush()
    try:
        raw = input().strip()
    except (KeyboardInterrupt, EOFError):
        console.print()
        return

    if not raw:
        console.print("[dim]Using default model.[/dim]\n")
        return

    try:
        idx = int(raw) - 1
        if 0 <= idx < len(models):
            chosen = models[idx]
            _save_model_config(chosen)
            llm.set_model(chosen)
            console.print(f"\n[green]Model set to:[/green] [bold]{chosen}[/bold]")
            console.print("[dim]Saved to plamma.env — used on all future launches.[/dim]\n")
        else:
            console.print("[yellow]Number out of range — using default model.[/yellow]\n")
    except ValueError:
        console.print("[yellow]Invalid input — using default model.[/yellow]\n")

# ── thinking / toriso toggles ────────────────────────────────────────────────
_SHOW_THINKING = False
_TORISO_MODE   = False


def _read_document(path_str: str) -> tuple[str, str]:
    """Read a document from disk. Returns (content, error_message)."""
    path = Path(path_str.strip('"').strip("'"))
    if not path.exists():
        return "", f"File not found: {path}"

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text, ""
        except ImportError:
            return "", "PDF support requires pypdf. Run: pip install pypdf"
        except Exception as e:
            return "", f"PDF read error: {e}"

    _TEXT_TYPES = {".txt",".md",".py",".csv",".json",".log",".html",".xml",
                   ".yaml",".yml",".toml",".cfg",".ini",".rst",""}
    if suffix in _TEXT_TYPES:
        try:
            return path.read_text(encoding="utf-8", errors="replace"), ""
        except Exception as e:
            return "", f"Read error: {e}"

    return "", f"Unsupported file type '{suffix}'. Supported: txt md py csv json log html xml yaml toml pdf"


# ── spinner shown while waiting for the first token ──────────────────────────

class _Spinner:
    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str = "thinking"):
        self._label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        sys.stdout.write("\r\033[2K")   # clear the spinner line
        sys.stdout.flush()

    def _run(self):
        i = 0
        while not self._stop.is_set():
            frame = self._FRAMES[i % len(self._FRAMES)]
            # after 15 s with no output, hint that the model may be loading
            label = "loading model, please wait" if i >= 150 else self._label
            sys.stdout.write(f"\r  \033[36m{frame}\033[0m \033[2m{label}...\033[0m")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1


# ── streaming output ──────────────────────────────────────────────────────────

def _has_markdown(text: str) -> bool:
    """True if text contains a table, code fence, or heading."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|") and s.count("|") >= 3:
            return True
        if s.startswith("```"):
            return True
        if s.startswith("#") and len(s) > 1 and s[1] in "# \t":
            return True
    return False


def _render_response(text: str):
    """
    Render a model response with proper formatting.
    Markdown tables are rendered as Rich Table objects (with row lines so cells
    never merge into a wall of text).  Everything else goes through Markdown.
    """
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    in_table = False
    buf: list[str] = []

    for line in lines:
        s = line.strip()
        is_table_line = s.startswith("|") and s.endswith("|")
        if is_table_line:
            if not in_table:
                if buf:
                    sections.append(("text", buf))
                buf = []
                in_table = True
            buf.append(line)
        else:
            if in_table:
                sections.append(("table", buf))
                buf = []
                in_table = False
            buf.append(line)

    if buf:
        sections.append(("table" if in_table else "text", buf))

    for kind, chunk_lines in sections:
        content = "\n".join(chunk_lines)
        if kind == "table":
            _render_md_table(content)
        else:
            stripped = content.strip()
            if stripped:
                console.print(Markdown(stripped))
    console.print()


def _render_md_table(table_str: str):
    """Parse a Markdown table string and render it as a Rich Table with row lines."""
    rows = [l for l in table_str.strip().splitlines() if l.strip()]
    if len(rows) < 2:
        console.print(table_str)
        return

    def _cells(row: str) -> list[str]:
        return [c.strip() for c in row.strip().strip("|").split("|")]

    headers   = _cells(rows[0])
    data_rows = [_cells(r) for r in rows[2:] if not re.match(r"^\s*\|[\s\-|]+\|\s*$", r)]

    table = Table(show_lines=True, header_style="bold cyan", show_edge=True, padding=(0, 1))
    for h in headers:
        table.add_column(h)

    for row in data_rows:
        while len(row) < len(headers):
            row.append("")
        table.add_row(*row[: len(headers)])

    console.print(table)


def _write(text: str):
    if not text:
        return
    sys.stdout.write(text)
    sys.stdout.flush()


def stream_and_collect(messages: list[dict]) -> str:
    """
    Collect a response from the LLM.
    Text is buffered silently while the spinner runs, then rendered once:
      - Markdown (tables / code / headings) → _render_response (rich formatting)
      - Plain text → streamed out directly after collection
    Thinking tags are shown live only when _SHOW_THINKING is on.
    """
    global _SHOW_THINKING
    collected: list[str] = []

    spinner = _Spinner("thinking")
    spinner.start()

    in_thinking = False

    for tag, chunk in stream_response(messages, think=_SHOW_THINKING):
        if not chunk:
            continue

        if tag == "think":
            if _SHOW_THINKING:
                if not in_thinking:
                    spinner.stop()
                    sys.stdout.write("\033[2m\033[3m◌ thinking:\033[23m\n")
                    in_thinking = True
                _write(chunk)
            # if hiding: spinner keeps running, thinking discarded

        elif tag == "text":
            if in_thinking:
                sys.stdout.write("\033[0m\n\n")
                in_thinking = False
            if not collected:
                spinner._label = "generating"  # first token arrived
            collected.append(chunk)
            # intentionally NOT writing here — buffer silently

        else:  # "error"
            if in_thinking:
                sys.stdout.write("\033[0m\n")
                in_thinking = False
            spinner.stop()
            _write(chunk)

    if in_thinking:
        sys.stdout.write("\033[0m\n\n")
    spinner.stop()

    full = "".join(collected)
    if _has_markdown(full):
        _render_response(full)   # rich tables + formatted markdown
    else:
        _write(full)
        _write("\n")

    return full


# ── search helpers ────────────────────────────────────────────────────────────

def run_search_and_answer(user_input: str, mode: str, session: Session):
    global _TORISO_MODE
    # Strip the command prefix to get the actual query/message
    if mode == "surface":
        query = user_input[3:].strip()
    elif mode == "dark":
        query = user_input[3:].strip()
    else:  # both
        query = user_input[4:].strip()

    if not query:
        console.print("[red]Please provide a query after the command.[/red]")
        return

    if _TORISO_MODE:
        with console.status("[dim]Rotating Tor circuit (toriso)...[/dim]"):
            new_identity()

    results = []

    if mode in ("surface", "both"):
        with console.status("[cyan]Searching surface web via Tor...[/cyan]"):
            results.extend(search_surface(query))

    if mode in ("dark", "both"):
        with console.status("[red]Searching dark web (.onion) via Tor...[/red]"):
            results.extend(search_dark(query))

    # Re-index results sequentially
    idx = 1
    for r in results:
        if "error" not in r:
            r["index"] = idx
            idx += 1

    useful = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    if errors:
        for e in errors:
            console.print(f"[yellow]  ! {e['error']}[/yellow]")

    messages = [{"role": "system", "content": get_system_prompt()}]
    messages += session.get_context()

    if useful:
        console.print(f"[green]● Live data[/green]  [dim]{len(useful)} result(s)[/dim]")
        messages.append({
            "role": "system",
            "content": format_for_llm(useful) + "\n\nAnswer the question using the results above. Cite sources inline as [1], [2], etc. List the URLs at the end.",
        })
    else:
        console.print("[yellow]⚠ Offline — search returned no results[/yellow]")
        messages.append({"role": "system", "content": OFFLINE_NOTICE})

    messages.append({"role": "user", "content": query})

    console.print("\n[bold green]Plamma:[/bold green]")
    response = stream_and_collect(messages)

    # Append citation footer if we had results
    if useful:
        footer = format_citations(useful)
        sys.stdout.write(footer + "\n\n")
        sys.stdout.flush()
        response += footer

    session.add("user", query)
    session.add("assistant", response)


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def _open_file_dialog() -> str | None:
    """Show a native Windows file-picker dialog. Returns chosen path or None if cancelled."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()                      # hide the blank Tk window
        root.wm_attributes("-topmost", True) # ensure dialog appears on top
        path = filedialog.askopenfilename(
            title="Select an image for Plamma",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"),
                ("All files",   "*.*"),
            ],
        )
        root.destroy()
        return path if path else None
    except Exception as e:
        console.print(f"[red]File dialog failed: {e}[/red]")
        return None


def run_image_message(user_input: str, session: Session):
    raw = user_input[4:].strip()  # strip "/img"

    # ── path resolution ────────────────────────────────────────────────────────
    if not raw:
        # No path typed → open the file picker dialog
        console.print("[dim]  Opening file picker...[/dim]")
        path = _open_file_dialog()
        if not path:
            console.print("[yellow]No image selected.[/yellow]")
            return
        # Ask for the question inline after the dialog closes
        sys.stdout.write("  \033[94mQuestion\033[0m \033[2m(Enter = describe it)\033[0m: ")
        sys.stdout.flush()
        try:
            question = input().strip() or "Describe this image in detail."
        except (KeyboardInterrupt, EOFError):
            return
    elif raw.startswith('"'):
        # Quoted path: /img "C:\my folder\pic.jpg" optional question
        end = raw.find('"', 1)
        if end == -1:
            console.print("[red]Missing closing quote around path.[/red]")
            return
        path = raw[1:end]
        question = raw[end + 1:].strip() or "Describe this image in detail."
    else:
        # Unquoted: /img C:\pic.jpg optional question
        parts = raw.split(maxsplit=1)
        path = parts[0]
        question = parts[1] if len(parts) > 1 else "Describe this image in detail."

    # ── validation ─────────────────────────────────────────────────────────────
    if not os.path.exists(path):
        console.print(f"[red]File not found: {path}[/red]")
        return

    ext = os.path.splitext(path)[1].lower()
    if ext not in _IMAGE_EXTS:
        console.print(f"[yellow]Warning: '{ext}' may not be supported.[/yellow]")

    # ── encode & send ──────────────────────────────────────────────────────────
    try:
        with open(path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        console.print(f"[red]Could not read image: {e}[/red]")
        return

    fname = os.path.basename(path)
    console.print(f"[dim]  image: {fname}[/dim]")

    messages = [{"role": "system", "content": get_system_prompt()}]
    messages += session.get_context()
    messages.append({
        "role": "user",
        "content": question,
        "images": [image_b64],
    })

    console.print("\n[bold green]Plamma:[/bold green]")
    response = stream_and_collect(messages)

    session.add("user", f"[Image: {fname}] {question}")
    session.add("assistant", response)


def run_normal_message(user_input: str, session: Session):
    global _TORISO_MODE
    # Resolve time/timezone queries locally — no web search needed
    time_fact = resolve_time_query(user_input)

    keyword_hit, tickers = needs_live_data(user_input)

    if time_fact and not tickers:
        do_search = False
    else:
        do_search = keyword_hit or bool(tickers)

    live_data = ""
    if time_fact:
        live_data += time_fact + "\n\n"

    useful: list[dict] = []

    if do_search:
        if _TORISO_MODE:
            with console.status("[dim]Rotating Tor circuit (toriso)...[/dim]"):
                new_identity()
        if tickers:
            with console.status(f"[cyan]Fetching live data for {', '.join(tickers)}...[/cyan]"):
                stock_data = fetch_finviz(tickers)
            if stock_data:
                console.print(f"[dim]  stock data fetched for {', '.join(tickers)}[/dim]")
                live_data += stock_data + "\n\n"

        with console.status("[cyan]Searching surface web via Tor...[/cyan]"):
            results = search_surface(user_input)

        useful = [r for r in results if "error" not in r]
        if useful:
            idx = 1
            for r in useful:
                r["index"] = idx
                idx += 1
            live_data += format_for_llm(useful)

    messages = [{"role": "system", "content": get_system_prompt()}]
    messages += session.get_context()

    if live_data and not do_search:
        # Time resolved locally — no search was done
        console.print("[green]● Live data[/green]  [dim]resolved locally[/dim]")
        messages.append({
            "role": "system",
            "content": live_data + "\n\nAnswer the question using the fact above. Be direct and concise.",
        })
    elif do_search and live_data:
        console.print("[green]● Live data[/green]")
        messages.append({
            "role": "system",
            "content": live_data + "\n\nUse the data above to answer accurately. Cite sources inline as [1], [2], etc. and list URLs at the end.",
        })
    elif do_search and not live_data:
        console.print("[yellow]⚠ Offline — could not retrieve live data[/yellow]")
        messages.append({"role": "system", "content": OFFLINE_NOTICE})

    messages.append({"role": "user", "content": user_input})

    console.print("\n[bold green]Plamma:[/bold green]")
    response = stream_and_collect(messages)

    if useful:
        footer = format_citations(useful)
        sys.stdout.write(footer + "\n\n")
        sys.stdout.flush()
        response += footer

    session.add("user", user_input)
    session.add("assistant", response)


# ── shutdown ──────────────────────────────────────────────────────────────────

def _shutdown_services():
    if sys.platform == "win32":
        for name in ("tor.exe", "ollama.exe"):
            subprocess.run(
                ["taskkill", "/F", "/IM", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    # On Linux/macOS, Tor and Ollama are managed externally — don't kill them


# ── self-destruct ─────────────────────────────────────────────────────────────

def _self_destruct():
    """
    1. Wipe all session data from ~/.plamma/
    2. Spawn a detached cleanup process that deletes the Plamma directory
       after this process exits, then terminate.
    """
    import shutil

    # Delete session data synchronously first
    plamma_data = Path.home() / ".plamma"
    if plamma_data.exists():
        shutil.rmtree(plamma_data, ignore_errors=True)

    # Determine the directory to erase (script dir or PyInstaller bundle dir)
    if getattr(sys, "frozen", False):
        target = str(Path(sys.executable).parent.resolve())
    else:
        target = str(Path(__file__).parent.resolve())

    pid = os.getpid()

    if sys.platform == "win32":
        # Batch script: wait until our PID disappears, then rmdir the target
        script = tempfile.NamedTemporaryFile(suffix=".cmd", delete=False, mode="w", encoding="utf-8")
        script.write(
            "@echo off\n"
            ":wait\n"
            f"tasklist /FI \"PID eq {pid}\" 2>nul | find /I \"{pid}\" >nul\n"
            "if %errorlevel%==0 (timeout /t 1 /nobreak >nul & goto wait)\n"
            "timeout /t 1 /nobreak >nul\n"
            f"rmdir /s /q \"{target}\"\n"
            "del \"%~f0\"\n"
        )
        script.close()
        subprocess.Popen(
            ["cmd", "/c", script.name],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_CONSOLE,
            close_fds=True,
        )
    else:
        script = tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="w", encoding="utf-8")
        script.write(
            "#!/bin/sh\n"
            f"while kill -0 {pid} 2>/dev/null; do sleep 1; done\n"
            f"rm -rf \"{target}\"\n"
            "rm -- \"$0\"\n"
        )
        script.close()
        os.chmod(script.name, 0o700)
        subprocess.Popen(["/bin/sh", script.name], start_new_session=True, close_fds=True)

    sys.exit(0)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    console.print(Text(BANNER, style="bold cyan"))
    console.print(Panel.fit(
        "[bold white]Private · Local · Uncensored[/bold white]\n"
        f"[dim]Model: {llm.MODEL}[/dim]",
        border_style="cyan",
    ))
    console.print()

    # ── OLLAMA_URL remote host warning ───────────────────────────────────────
    from urllib.parse import urlparse as _urlparse
    _parsed = _urlparse(llm.OLLAMA_URL)
    if _parsed.hostname not in ("127.0.0.1", "localhost", "::1", None):
        console.print(
            "\n[bold red]⚠  SECURITY WARNING[/bold red]\n"
            f"  OLLAMA_URL is set to a remote host: [bold]{llm.OLLAMA_URL}[/bold]\n"
            "  All conversation data will be sent to that server [bold red]unencrypted[/bold red].\n"
            "  Set [yellow]OLLAMA_URL=http://localhost:11434[/yellow] in plamma.env to use a local model.\n"
        )
        sys.stdout.write("  Press Enter to continue anyway, or Ctrl+C to exit: ")
        sys.stdout.flush()
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
        console.print()

    # Startup checks
    ollama_ok = check_ollama()
    if not ollama_ok:
        console.print("[bold red]Ollama is not running.[/bold red]")
        console.print("[dim]Start it with: ollama serve[/dim]\n")
    else:
        console.print("[green]Ollama[/green]  connected")

    # First-run model picker — only when plamma.env doesn't exist yet
    if not (Path(__file__).parent / "plamma.env").exists():
        _first_run_picker(ollama_ok)

    console.print("[dim]Checking Tor...[/dim]", end=" ")
    sys.stdout.flush()
    tor_ok = check_tor()
    if tor_ok:
        console.print("[green]Tor[/green]     active — searches are anonymous")
    else:
        console.print("[yellow]Tor[/yellow]     NOT detected — searches will NOT be anonymous")
        console.print(
            "[dim]  Start Tor first (see setup instructions). "
            "/s /d /sd will still work but without Tor protection.[/dim]"
        )

    console.print(f"\n[dim]Type [yellow]/help[/yellow] for commands.[/dim]\n")

    session = Session()

    while True:
        try:
            sys.stdout.write("\033[94mYou: \033[0m")
            sys.stdout.flush()
            user_input = input().strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Shutting down...[/dim]")
            _shutdown_services()
            break

        if not user_input:
            continue

        low = user_input.lower()

        if low in ("/exit", "/quit", "exit", "quit"):
            console.print("[dim]Shutting down...[/dim]")
            _shutdown_services()
            break

        elif low.startswith("/h ") or low == "/h":
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                console.print("[dim]Usage: /h \\[command][/dim]")
                console.print("[dim]Available: [yellow]session  nuke  log  s  img  tor  model  fetch  doc  d2  toriso[/yellow][/dim]")
            else:
                key = parts[1].strip().lstrip("/").lower()
                # normalise aliases
                if key in ("d", "sd", "search", "dark", "surface"):
                    key = "s"
                if key == "newtor":
                    key = "tor"
                if key in ("models", "model"):
                    key = "model"
                if key == "i2p":
                    key = "d2"
                info = DETAILED_HELP.get(key)
                if info:
                    console.print(info)
                else:
                    console.print(f"[yellow]No detailed help for '{key}'.[/yellow]")
                    console.print("[dim]Available: [yellow]session  nuke  log  s  img  tor  model  fetch  doc  d2  toriso[/yellow][/dim]")

        elif low == "/help":
            console.print(HELP_TEXT)

        elif low == "/showthink":
            global _SHOW_THINKING
            _SHOW_THINKING = not _SHOW_THINKING
            state = "[green]ON[/green] — thinking will be echoed" if _SHOW_THINKING else "[yellow]OFF[/yellow] — thinking is hidden"
            console.print(f"  Thinking display: {state}")

        elif low == "/toriso":
            global _TORISO_MODE
            _TORISO_MODE = not _TORISO_MODE
            state = "[green]ON[/green] — circuit rotated before every search" if _TORISO_MODE else "[yellow]OFF[/yellow]"
            console.print(f"  Circuit isolation: {state}")

        elif low.startswith("/fetch "):
            url = user_input[7:].strip()
            if not url.startswith(("http://", "https://")):
                console.print("[red]Usage: /fetch <url>  (must start with http:// or https://)[/red]")
            else:
                with console.status(f"[cyan]Fetching {url} via Tor...[/cyan]"):
                    result = fetch_url_content(url)
                if "error" in result:
                    console.print(f"[red]Fetch failed: {result['error']}[/red]")
                else:
                    title = result.get("title", url)
                    content = result["content"]
                    console.print(f"[dim]  Fetched: {title}  ({len(content)} chars)[/dim]")
                    messages = [{"role": "system", "content": get_system_prompt()}]
                    messages += session.get_context()
                    messages.append({
                        "role": "system",
                        "content": (
                            f"The user fetched the following page via Tor:\n"
                            f"URL: {url}\nTitle: {title}\n\n"
                            f"--- PAGE CONTENT START ---\n{content}\n--- PAGE CONTENT END ---\n\n"
                            "Use this content to answer the user's question."
                        ),
                    })
                    messages.append({"role": "user", "content": f"Analyse and summarise: {url}"})
                    console.print("\n[bold green]Plamma:[/bold green]")
                    response = stream_and_collect(messages)
                    session.add("user", f"[Fetched: {url}]")
                    session.add("assistant", response)

        elif low.startswith("/doc "):
            path_arg = user_input[5:].strip()
            content, err = _read_document(path_arg)
            if err:
                console.print(f"[red]{err}[/red]")
            else:
                MAX_DOC = 12_000
                truncated = len(content) > MAX_DOC
                if truncated:
                    content = content[:MAX_DOC] + f"\n\n[truncated — original: {len(content)} chars]"
                console.print(f"[dim]  Document loaded: {Path(path_arg).name}  ({len(content)} chars{' — truncated' if truncated else ''})[/dim]")
                messages = [{"role": "system", "content": get_system_prompt()}]
                messages += session.get_context()
                messages.append({
                    "role": "system",
                    "content": (
                        f"The user provided the following document ({Path(path_arg).name}):\n\n"
                        f"--- DOCUMENT START ---\n{content}\n--- DOCUMENT END ---\n\n"
                        "Use this document to answer the user's questions."
                    ),
                })
                messages.append({"role": "user", "content": f"Analyse and summarise this document: {Path(path_arg).name}"})
                console.print("\n[bold green]Plamma:[/bold green]")
                response = stream_and_collect(messages)
                session.add("user", f"[Document: {Path(path_arg).name}]")
                session.add("assistant", response)

        elif low.startswith("/d2 "):
            query = user_input[4:].strip()
            if not query:
                console.print("[red]Usage: /d2 <query>[/red]")
            else:
                if _TORISO_MODE:
                    with console.status("[dim]Rotating Tor circuit (toriso)...[/dim]"):
                        new_identity()
                with console.status("[magenta]Searching I2P network...[/magenta]"):
                    results = search_i2p(query)
                idx = 1
                for r in results:
                    if "error" not in r:
                        r["index"] = idx
                        idx += 1
                useful = [r for r in results if "error" not in r]
                errors = [r for r in results if "error" in r]
                for e in errors:
                    console.print(f"[yellow]  ! {e['error']}[/yellow]")
                messages = [{"role": "system", "content": get_system_prompt()}]
                messages += session.get_context()
                if useful:
                    console.print(f"[magenta]● I2P[/magenta]  [dim]{len(useful)} result(s)[/dim]")
                    messages.append({
                        "role": "system",
                        "content": format_for_llm(useful) + "\n\nAnswer the question using the I2P results above. Cite sources inline as [1], [2], etc.",
                    })
                else:
                    console.print("[yellow]⚠ No I2P results — is I2P running?[/yellow]")
                    messages.append({"role": "system", "content": OFFLINE_NOTICE})
                messages.append({"role": "user", "content": query})
                console.print("\n[bold green]Plamma:[/bold green]")
                response = stream_and_collect(messages)
                if useful:
                    footer = format_citations(useful)
                    sys.stdout.write(footer + "\n\n")
                    sys.stdout.flush()
                    response += footer
                session.add("user", query)
                session.add("assistant", response)

        elif low == "/clear":
            session.clear()
            console.print("[green]Session cleared.[/green]")

        elif low.startswith("/session"):
            _parts = user_input.split(maxsplit=2)
            sub = _parts[1].lower() if len(_parts) > 1 else ""

            if sub == "-s":
                if session.is_empty():
                    console.print("[yellow]Nothing to save — session is empty.[/yellow]")
                else:
                    try:
                        token, codename = session.save_encrypted()
                        console.print("\n[bold green]Session encrypted and saved.[/bold green]")
                        console.print(f"  Codename : [bold cyan]{codename}[/bold cyan]")
                        console.print(f"  Token    : [bold yellow]{token}[/bold yellow]")
                        console.print("\n[dim]Store both safely. The token cannot be recovered — lose it and the session is gone forever.[/dim]")
                        console.print("[dim]Restore with [yellow]/session -c <token>[/yellow] or [yellow]/session -c <codename>[/yellow] (will prompt for token).[/dim]")
                    except Exception as e:
                        console.print(f"[red]Failed to save session: {e}[/red]")

            elif sub == "-c":
                if len(_parts) < 3:
                    console.print("[yellow]Usage: /session -c <token|codename>[/yellow]")
                else:
                    arg = _parts[2].strip()
                    from session import _is_token
                    try:
                        if _is_token(arg):
                            session = Session.load_by_token(arg)
                        else:
                            # arg is a codename — prompt for token
                            sys.stdout.write("  \033[94mToken\033[0m \033[2m(for codename: ")
                            sys.stdout.write(arg)
                            sys.stdout.write(")\033[0m: ")
                            sys.stdout.flush()
                            try:
                                token = input().strip()
                            except (KeyboardInterrupt, EOFError):
                                console.print("\n[yellow]Cancelled.[/yellow]")
                                console.print()
                                continue
                            session = Session.load_by_codename(arg, token)
                        console.print(f"[green]Session restored.[/green] [dim]{len(session.messages)} messages loaded.[/dim]")
                    except FileNotFoundError:
                        console.print("[red]No session found.[/red]")
                    except KeyError as e:
                        console.print(f"[red]{e}[/red]")
                    except ValueError:
                        console.print("[red]Token does not match that codename.[/red]")
                    except Exception:
                        console.print("[red]Invalid or corrupted token.[/red]")

            elif sub == "-d":
                if len(_parts) < 3:
                    console.print("[yellow]Usage: /session -d <codename>[/yellow]")
                else:
                    codename = _parts[2].strip()
                    deleted = Session.delete_session(codename)
                    if deleted:
                        console.print(f"[green]Session '[bold]{codename}[/bold]' deleted.[/green]")
                    else:
                        console.print(f"[red]No session with codename '{codename}'.[/red]")

            else:
                console.print("[yellow]Usage: /session -s | -c <token|codename> | -d <codename>[/yellow]")

        elif low in ("/nuke", "/nuke -f"):
            force = low == "/nuke -f"
            if not force:
                console.print("\n[bold red]WARNING[/bold red]  This will:")
                console.print("  [red]•[/red] Permanently delete all saved encrypted sessions")
                console.print("  [red]•[/red] Delete the entire Plamma program directory")
                console.print("  [red]•[/red] Leave nothing recoverable on this machine")
                console.print("\n[dim]Type [bold]YES[/bold] to confirm, anything else to cancel:[/dim] ", end="")
                sys.stdout.flush()
                try:
                    confirm = input().strip()
                except (KeyboardInterrupt, EOFError):
                    confirm = ""
                if confirm != "YES":
                    console.print("[green]Aborted.[/green]")
                    console.print()
                    continue
            console.print("[dim]Wiping sessions...[/dim]")
            Session.nuke_sessions()
            console.print("[red]Initiating self-destruct — goodbye.[/red]")
            _self_destruct()

        elif low.startswith("/log"):
            if session.is_empty():
                console.print("[yellow]Nothing to save — session is empty.[/yellow]")
            else:
                parts = user_input.split(maxsplit=1)
                path = parts[1] if len(parts) > 1 else None
                saved = session.save(path)
                console.print(f"[green]Saved:[/green] {saved}")

        elif low == "/tor":
            with console.status("Checking Tor..."):
                ok = check_tor()
            if ok:
                console.print("[green]Tor: ACTIVE[/green]")
            else:
                console.print("[red]Tor: NOT CONNECTED[/red]")

        elif low == "/newtor":
            with console.status("Rotating Tor circuit..."):
                ok, msg = new_identity()
            if ok:
                console.print(f"[green]{msg}[/green]")
            else:
                console.print(f"[yellow]{msg}[/yellow]")

        elif low.startswith("/model"):
            _mparts = user_input.split(maxsplit=1)
            _msub   = _mparts[1].strip() if len(_mparts) > 1 else ""

            if not _msub:
                rec, label = _is_recommended(llm.MODEL)
                tag = f"  [bold green]★ {label}[/bold green]" if rec else ""
                console.print(f"[dim]Model: [bold]{llm.MODEL}[/bold]{tag}[/dim]")

            elif _msub.lower() == "-a":
                models = _fetch_models()
                if not models:
                    console.print("[red]Could not reach Ollama to list models.[/red]")
                else:
                    table = Table(
                        show_header=True,
                        header_style="bold cyan",
                        show_edge=False,
                        padding=(0, 1),
                    )
                    table.add_column("", width=2, no_wrap=True)
                    table.add_column("Model", no_wrap=True)
                    table.add_column("Type", style="dim", no_wrap=True)
                    table.add_column("", no_wrap=True)

                    # recommended first, then the rest
                    recommended = [(n, *_is_recommended(n)) for n in models if _is_recommended(n)[0]]
                    others      = [(n, *_is_recommended(n)) for n in models if not _is_recommended(n)[0]]

                    for name, rec, label in recommended:
                        active_str = "[bold cyan](active)[/bold cyan]" if name == llm.MODEL else ""
                        table.add_row(
                            "[bold green]★[/bold green]",
                            f"[bold]{name}[/bold]",
                            f"[green]{label}[/green]",
                            active_str,
                        )

                    for name, rec, label in others:
                        active_str = "[bold cyan](active)[/bold cyan]" if name == llm.MODEL else ""
                        table.add_row(" ", name, "", active_str)

                    console.print()
                    console.print(table)
                    console.print(
                        "\n[dim][bold green]★[/bold green] = recommended (unrestricted)   "
                        "Use [yellow]/model \\[name][/yellow] to switch.[/dim]"
                    )
                    console.print(
                        "[dim][bold yellow]⚠[/bold yellow]  Standard models have built-in safety filters "
                        "that cannot be bypassed by a system prompt.[/dim]"
                    )

            else:
                llm.set_model(_msub)
                _save_model_config(_msub)
                rec, label = _is_recommended(_msub)
                console.print(f"[green]Model switched to:[/green] [bold]{_msub}[/bold]")
                if rec:
                    console.print(f"[green]★ Recognised as an unrestricted model ({label}).[/green]")
                else:
                    console.print(
                        "[bold yellow]⚠[/bold yellow]  [dim]This model does not appear to be abliterated/uncensored. "
                        "Safety filters may still be active — some requests might be refused.[/dim]"
                    )
                console.print("[dim]Saved to plamma.env.[/dim]")

        elif low == "/img" or low.startswith("/img "):
            run_image_message(user_input, session)

        elif low.startswith("/sd "):
            run_search_and_answer(user_input, "both", session)

        elif low.startswith("/s "):
            run_search_and_answer(user_input, "surface", session)

        elif low.startswith("/d "):
            run_search_and_answer(user_input, "dark", session)

        elif low.startswith("/"):
            console.print(f"[yellow]Unknown command. Type /help for available commands.[/yellow]")

        else:
            run_normal_message(user_input, session)

        console.print()


if __name__ == "__main__":
    main()
