"""Detect running games so the AI can step out of the way.

Discord does not expose other apps' Rich Presence to third parties; the reliable
local signal is the process list. Clipper combines a bundled game-title map,
Unreal Engine shipping-process names, and game-library paths so it keeps working
for titles that are not in the curated list yet.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent / "assets"
GAME_TITLES_FILE = ASSET_DIR / "game_titles.json"

# Keep a small fallback for source installs where package data is incomplete.
_FALLBACK_GAMES = {
    "rocketleague.exe": "Rocket League",
    "rocketleague-win64-shipping.exe": "Rocket League",
    "tftclient-win64-shipping.exe": "Teamfight Tactics",
    "league of legends.exe": "League of Legends",
    "mimesis.exe": "Mimesis",
    "mimesis-win64-shipping.exe": "Mimesis",
    "valorant.exe": "Valorant",
    "valorant-win64-shipping.exe": "Valorant",
    "r5apex.exe": "Apex Legends",
    "cs2.exe": "Counter-Strike 2",
}


def _load_known_games() -> dict[str, str]:
    games = dict(_FALLBACK_GAMES)
    try:
        payload = json.loads(GAME_TITLES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return games
    entries = payload.get("processes") if isinstance(payload, dict) else None
    if isinstance(entries, dict):
        for exe, label in entries.items():
            exe_text = str(exe).strip().lower()
            label_text = str(label).strip()
            if exe_text and label_text:
                games[exe_text] = label_text
    return games


KNOWN_GAMES = _load_known_games()

_UNREAL_SUFFIXES = (
    "-win64-shipping.exe",
    "-wing64-shipping.exe",
    "-win64-shipping",
    "-shipping.exe",
)

_GAME_PATH_MARKERS = (
    "\\steamapps\\common\\",
    "\\epic games\\",
    "\\gog games\\",
    "\\riot games\\",
    "\\ubisoft game launcher\\games\\",
    "\\ea games\\",
    "\\xboxgames\\",
    "\\battle.net\\",
)

_NON_GAME_FOLDERS = {
    "launcher",
    "riot client",
    "riot clientux",
    "riot client services",
    "epic games launcher",
    "epic online services",
    "steam",
    "steamvr",
    "battle.net",
    "blizzard",
    "ea desktop",
    "ubisoft connect",
    "gog galaxy",
    "xbox app",
    "playnite",
    "rockstar games launcher",
    "bethesda launcher",
    "paradox launcher",
    "wargaming game center",
    "minecraft launcher",
    "wallpaper_engine",
    "obs-studio",
    "source sdk base 2013",
    "destinations workshop tools",
    "steamworks sdk",
    "commonredist",
    "easyanticheat",
    "battleye",
    "support",
    "redistributables",
}

_LAUNCHER_PATH_MARKERS = (
    "\\riot games\\riot client\\",
    "\\epic games\\launcher\\",
    "\\steam\\bin\\",
    "\\steam\\steam.exe",
    "\\battle.net\\",
    "\\ea desktop\\",
    "\\ubisoft connect\\",
    "\\gog galaxy\\",
    "\\xbox app\\",
    "\\playnite\\",
    "\\rockstar games\\launcher\\",
    "\\bethesda.net launcher\\",
    "\\paradox launcher\\",
    "\\wargaming.net\\gamecenter\\",
    "\\minecraft launcher\\",
)

_NON_GAME_PROCESSES = {
    "steam.exe",
    "steamwebhelper.exe",
    "steamservice.exe",
    "epicgameslauncher.exe",
    "epicwebhelper.exe",
    "riotclientservices.exe",
    "riotclientux.exe",
    "riotclientcrashhandler.exe",
    "riotclient.exe",
    "riot client.exe",
    "leagueclient.exe",
    "leagueclientux.exe",
    "league client.exe",
    "battle.net.exe",
    "agent.exe",
    "origin.exe",
    "eadesktop.exe",
    "eabackgroundservice.exe",
    "ubisoftconnect.exe",
    "upc.exe",
    "galaxyclient.exe",
    "goggalaxy.exe",
    "xboxapp.exe",
    "gamebar.exe",
    "gamingservices.exe",
    "playnite.desktopapp.exe",
    "playnite.fullscreenapp.exe",
    "rockstarlauncher.exe",
    "bethesdanetlauncher.exe",
    "paradoxlauncher.exe",
    "wargaminggamecenter.exe",
    "minecraftlauncher.exe",
    "itch.exe",
    "wallpaper32.exe",
    "wallpaper64.exe",
    "obs64.exe",
    "obs32.exe",
    "discord.exe",
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
}

# Launchers are not games. Match their process families even when a new
# component (crash handler, web helper, UX shell) is added by an update.
_LAUNCHER_PROCESS_PREFIXES = (
    "riotclient",
    "riot client",
    "leagueclient",
    "league client",
    "epicgameslauncher",
    "epicwebhelper",
    "battle.net",
    "blizzard",
    "eadesktop",
    "eabackgroundservice",
    "ubisoftconnect",
    "galaxyclient",
    "goggalaxy",
    "xboxapp",
    "gamebar",
    "gamingservices",
    "playnite",
    "rockstarlauncher",
    "bethesdanet",
    "paradoxlauncher",
    "wargaming",
    "minecraftlauncher",
    "amazon games",
    "nexon",
)


def _is_launcher_process(name: str) -> bool:
    exe = name.strip().lower()
    if exe in _NON_GAME_PROCESSES:
        return True
    return any(exe.startswith(prefix) for prefix in _LAUNCHER_PROCESS_PREFIXES)


class _ProcessEntry32W(ctypes.Structure):
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


def _windows_snapshot() -> list[tuple[str, int]]:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    kernel32.Process32FirstW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessEntry32W),
    ]
    kernel32.Process32NextW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessEntry32W),
    ]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return []
    entries: list[tuple[str, int]] = []
    entry = _ProcessEntry32W()
    entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
    try:
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                entries.append(
                    (str(entry.szExeFile).lower(), int(entry.th32ProcessID))
                )
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return entries


def _windows_process_names() -> set[str]:
    return {name for name, _pid in _windows_snapshot()}


def _windows_process_paths() -> dict[str, str]:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    paths: dict[str, str] = {}
    for name, pid in _windows_snapshot():
        handle = kernel32.OpenProcess(0x1000, 0, pid)
        if not handle:
            continue
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(buffer))
            if kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                paths[name] = buffer.value
        finally:
            kernel32.CloseHandle(handle)
    return paths


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
    return {
        Path(line.strip()).name.lower()
        for line in output.splitlines()
        if line.strip()
    }


def running_process_names() -> set[str]:
    if os.name == "nt":
        return _windows_process_names()
    return _posix_process_names()


def running_process_paths() -> dict[str, str]:
    if os.name == "nt":
        return _windows_process_paths()
    return {}


def _pretty_name(stem: str) -> str:
    text = stem.replace("_", " ").replace("-", " ")
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    cleaned = " ".join(text.split())
    if cleaned and cleaned.islower():
        cleaned = cleaned.title()
    return cleaned or stem


def _custom_games() -> dict[str, str]:
    path = custom_game_names_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(exe).strip().lower(): str(label).strip()
        for exe, label in payload.items()
        if str(exe).strip() and str(label).strip()
    }


def _game_from_path(path: str) -> str | None:
    text = str(path).replace("/", "\\")
    lowered = text.lower()
    if any(marker in lowered for marker in _LAUNCHER_PATH_MARKERS):
        return None
    for marker in _GAME_PATH_MARKERS:
        index = lowered.find(marker)
        if index < 0:
            continue
        remainder = text[index + len(marker) :]
        folder = remainder.split("\\", 1)[0].strip()
        if not folder or folder.lower() in _NON_GAME_FOLDERS:
            continue
        return _pretty_name(folder)
    return None


def detect_running_game() -> str | None:
    names = {str(name).lower() for name in running_process_names()}
    if not names:
        return None
    games = dict(KNOWN_GAMES)
    games.update(_custom_games())
    for exe in names:
        if _is_launcher_process(exe):
            continue
        label = games.get(exe)
        if label:
            return label
    for exe in names:
        if _is_launcher_process(exe):
            continue
        for suffix in _UNREAL_SUFFIXES:
            if exe.endswith(suffix):
                stem = exe[: -len(suffix)]
                if stem and stem not in {"launcher", "crashreportclient"}:
                    return _pretty_name(stem)
    paths = {str(exe).lower(): path for exe, path in running_process_paths().items()}
    for exe, path in paths.items():
        if _is_launcher_process(exe):
            continue
        label = _game_from_path(path)
        if label:
            return label
    return None


PATH_GAME_ALIASES = (
    ("rocket league", "Rocket League"),
    ("rocketleague", "Rocket League"),
    ("teamfight tactics", "Teamfight Tactics"),
    ("tft", "Teamfight Tactics"),
    ("mimesis", "Mimesis"),
    ("valorant", "Valorant"),
    ("apex legends", "Apex Legends"),
    ("apex", "Apex Legends"),
    ("counter-strike", "Counter-Strike 2"),
    ("cs2", "Counter-Strike 2"),
    ("fortnite", "Fortnite"),
    ("grand theft auto", "Grand Theft Auto V"),
    ("gta v", "Grand Theft Auto V"),
    ("rainbow six", "Rainbow Six Siege"),
    ("overwatch", "Overwatch 2"),
    ("league of legends", "League of Legends"),
    ("dota 2", "Dota 2"),
    ("minecraft", "Minecraft"),
    ("roblox", "Roblox"),
    ("pubg", "PUBG: Battlegrounds"),
    ("call of duty", "Call of Duty"),
    ("elden ring", "Elden Ring"),
    ("baldur's gate", "Baldur's Gate 3"),
    ("cyberpunk", "Cyberpunk 2077"),
    ("helldivers", "Helldivers 2"),
    ("lethal company", "Lethal Company"),
    ("content warning", "Content Warning"),
    ("phasmophobia", "Phasmophobia"),
    ("among us", "Among Us"),
    ("the finals", "The Finals"),
    ("marvel rivals", "Marvel Rivals"),
    ("deadlock", "Deadlock"),
    ("escape from tarkov", "Escape from Tarkov"),
    ("warframe", "Warframe"),
    ("genshin", "Genshin Impact"),
    ("honkai", "Honkai: Star Rail"),
    ("palworld", "Palworld"),
    ("valheim", "Valheim"),
    ("rust", "Rust"),
)


def detect_game_from_path(path: str | Path) -> str | None:
    text = str(path).lower()
    for token, label in PATH_GAME_ALIASES:
        if token in text:
            return label
    return None


def custom_game_names_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    return base / "Clipper" / "games.json"
