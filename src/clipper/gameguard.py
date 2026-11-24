"""Detect running games so the AI can step out of the way.

Discord does not expose other apps' Rich Presence to third parties; the reliable
local signal is the process list. Clipper uses that to pause AI work and unload
the Ollama model while a game is running, keeping VRAM free for the game.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path

KNOWN_GAMES = {
    "rocketleague.exe": "Rocket League",
    "rocketleague-win64-shipping.exe": "Rocket League",
    "mimesis.exe": "Mimesis",
    "mimesis-win64-shipping.exe": "Mimesis",
    "valorant.exe": "Valorant",
    "valorant-win64-shipping.exe": "Valorant",
    "r5apex.exe": "Apex Legends",
    "cs2.exe": "Counter-Strike 2",
    "fortniteclient-win64-shipping.exe": "Fortnite",
    "gta5.exe": "Grand Theft Auto V",
    "rainbowsix.exe": "Rainbow Six Siege",
    "rainbowsix_dx11.exe": "Rainbow Six Siege",
    "overwatch.exe": "Overwatch",
    "leagueclient.exe": "League of Legends",
    "league of legends.exe": "League of Legends",
    "dota2.exe": "Dota 2",
    "minecraft.exe": "Minecraft",
    "javaw.exe": "Minecraft",
    "robloxplayerbeta.exe": "Roblox",
    "pubg.exe": "PUBG",
    "cod.exe": "Call of Duty",
    "eldenring.exe": "Elden Ring",
    "bg3.exe": "Baldur's Gate 3",
    "cyberpunk2077.exe": "Cyberpunk 2077",
    "helldivers2.exe": "Helldivers 2",
    "lethalcompany.exe": "Lethal Company",
    "contentwarning.exe": "Content Warning",
    "peak.exe": "PEAK",
    "repoonline.exe": "REPO",
    "phasmophobia.exe": "Phasmophobia",
    "amongus.exe": "Among Us",
    "gtav.exe": "Grand Theft Auto V",
}


def _windows_process_names() -> set[str]:
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    kernel32.Process32FirstW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32NextW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return set()
    names: set[str] = set()
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                names.add(str(entry.szExeFile).lower())
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return names


def _posix_process_names() -> set[str]:
    try:
        output = subprocess.check_output(
            ["ps", "-A", "-o", "comm="],
            text=True,
            timeout=4,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {Path(line.strip()).name.lower() for line in output.splitlines() if line.strip()}


def running_process_names() -> set[str]:
    if os.name == "nt":
        return _windows_process_names()
    return _posix_process_names()


def detect_running_game() -> str | None:
    names = running_process_names()
    if not names:
        return None
    for exe, label in KNOWN_GAMES.items():
        if exe in names:
            return label
    return None


def custom_game_names_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    return base / "Clipper" / "games.json"
