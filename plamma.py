#!/usr/bin/env python3
import sys
import os
import base64
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# Force UTF-8 so spinner frames and box-drawing characters render correctly
if hasattr(sys.stdout, "reconfigure"):
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
from rich.panel import Panel
from rich.text import Text

from llm import get_system_prompt, MODEL, check_ollama, stream_response, should_search, OFFLINE_NOTICE
from search import (
    search_surface, search_dark, format_for_llm, format_citations,
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
  [yellow]/img[/yellow]                         Open file picker to choose an image, then ask your question
  [yellow]/showthink[/yellow]                   Toggle: show or hide the model's thinking process
  [yellow]/session -s[/yellow]                  Encrypt & save session — prints codename + one-time token
  [yellow]/session -c <token>[/yellow]          Restore session directly by token
  [yellow]/session -c <codename>[/yellow]       Restore session by codename (will prompt for token)
  [yellow]/session -d <codename>[/yellow]       Delete a saved session permanently
  [yellow]/log [file][/yellow]                  Save session to plaintext markdown
  [yellow]/clear[/yellow]                       Wipe in-memory chat history
  [yellow]/tor[/yellow]                         Check Tor connection status
  [yellow]/newtor[/yellow]                      Rotate Tor circuit (new exit node)
  [yellow]/model[/yellow]                       Show current model
  [yellow]/nuke[/yellow]                        Delete all sessions + self-destruct (prompts for confirm)
  [yellow]/nuke -f[/yellow]                     Same as /nuke but skips confirmation
  [yellow]/help[/yellow]                        Show this help
  [yellow]/exit[/yellow]                        Exit Plamma

[dim]Normal messages auto-search when they contain keywords like price/stock/today/news.[/dim]
[dim]Use /s /d /sd to force a specific search type.[/dim]
[dim]You can also type /img C:\\path\\to\\file.jpg [question] to skip the dialog.[/dim]
[dim]Set PLAMMA_MODEL, OLLAMA_URL, PLAMMA_CTX, TOR_SOCKS_PORT env vars to override defaults.[/dim]
"""

# ── thinking toggle (global state) ───────────────────────────────────────────
_SHOW_THINKING = False


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

def _write(text: str):
    if not text:
        return
    sys.stdout.write(text)
    sys.stdout.flush()


def stream_and_collect(messages: list[dict]) -> str:
    """
    Stream a response from the LLM.
    Handles (tag, text) tuples from stream_response:
      "think" — model reasoning; shown in dim if _SHOW_THINKING, else silent
      "text"  — final answer tokens; always shown
      "error" — always shown
    """
    global _SHOW_THINKING
    collected: list[str] = []

    spinner = _Spinner("thinking")
    spinner.start()

    in_thinking   = False   # currently streaming think tokens to screen
    got_first_text = False

    for tag, chunk in stream_response(messages, think=_SHOW_THINKING):
        if not chunk:
            continue

        if tag == "think":
            if _SHOW_THINKING:
                if not in_thinking:
                    spinner.stop()
                    sys.stdout.write("\033[2m\033[3m◌ thinking:\033[23m\n")  # dim+italic header, drop italic
                    in_thinking = True
                _write(chunk)   # still inside \033[2m dim scope
            # if hiding: spinner keeps running, thinking discarded

        elif tag == "text":
            if in_thinking:
                # close the thinking block
                sys.stdout.write("\033[0m\n\n")
                in_thinking = False
            if not got_first_text:
                spinner.stop()
                got_first_text = True
            collected.append(chunk)
            _write(chunk)

        else:  # "error"
            if in_thinking:
                sys.stdout.write("\033[0m\n")
                in_thinking = False
            spinner.stop()
            _write(chunk)

    # clean up any unclosed thinking block
    if in_thinking:
        sys.stdout.write("\033[0m\n\n")
    if not got_first_text:
        spinner.stop()

    _write("\n")
    return "".join(collected)


# ── search helpers ────────────────────────────────────────────────────────────

def run_search_and_answer(user_input: str, mode: str, session: Session):
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
        f"[dim]Model: {MODEL}[/dim]",
        border_style="cyan",
    ))
    console.print()

    # Startup checks
    if not check_ollama():
        console.print("[bold red]Ollama is not running.[/bold red]")
        console.print("[dim]Start it with: ollama serve[/dim]\n")
    else:
        console.print("[green]Ollama[/green]  connected")

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

        elif low == "/help":
            console.print(HELP_TEXT)

        elif low == "/showthink":
            global _SHOW_THINKING
            _SHOW_THINKING = not _SHOW_THINKING
            state = "[green]ON[/green] — thinking will be echoed" if _SHOW_THINKING else "[yellow]OFF[/yellow] — thinking is hidden"
            console.print(f"  Thinking display: {state}")

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

        elif low == "/model":
            console.print(f"[dim]Model: {MODEL}[/dim]")

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
