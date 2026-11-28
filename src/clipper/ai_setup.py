"""Optional Ollama backend: find and start an Ollama the user installed.

Clipper's normal AI path is the bundled llama.cpp runtime
(``detect/llama_runtime.py``). Ollama is still supported as an optional
backend for the CLI and older configurations, but Clipper no longer downloads
or silently installs it, and it never kills Ollama processes it did not start.
Install Ollama yourself from https://ollama.com if you want to use it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from .detect.ai import ollama_status

CREATE_NO_WINDOW = 0x08000000
CancelFn = Callable[[], bool]

_SERVER_PROCESS: subprocess.Popen[bytes] | None = None


def ollama_executable() -> Path | None:
    """Find an installed Ollama executable."""

    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return candidate
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidate = Path(program_files) / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return candidate
    found = shutil.which("ollama")
    if found:
        candidate = Path(found)
        if candidate.is_file():
            return candidate
    if local:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                user_path = str(winreg.QueryValueEx(key, "Path")[0])
            for entry in user_path.split(";"):
                entry = os.path.expandvars(entry.strip())
                if not entry:
                    continue
                candidate = Path(entry) / "ollama.exe"
                if candidate.is_file():
                    return candidate
        except (ImportError, OSError):
            pass
    return None


def stop_ollama_server() -> None:
    """Stop only the headless server Clipper started, if any."""

    global _SERVER_PROCESS
    process = _SERVER_PROCESS
    _SERVER_PROCESS = None
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            pass


def launch_ollama_server() -> bool:
    """Launch a headless Ollama process without waiting for HTTP readiness."""

    global _SERVER_PROCESS
    if bool(ollama_status(timeout=1.0).get("ok")):
        return True
    executable = ollama_executable()
    if executable is None:
        return False
    if _SERVER_PROCESS is not None and _SERVER_PROCESS.poll() is None:
        return True
    try:
        _SERVER_PROCESS = subprocess.Popen(
            [str(executable), "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError:
        return False
    return True


def start_ollama_server(
    wait: float = 20.0,
    cancelled: CancelFn | None = None,
) -> bool:
    """Start the local Ollama server if it is not already answering."""

    global _SERVER_PROCESS
    if not launch_ollama_server():
        return False
    deadline = time.monotonic() + max(1.0, wait)
    while time.monotonic() < deadline:
        if cancelled and cancelled():
            return False
        if bool(ollama_status(timeout=1.0).get("ok")):
            return True
        process = _SERVER_PROCESS
        if process is not None and process.poll() is not None:
            _SERVER_PROCESS = None
            return False
        time.sleep(0.5)
    return False
