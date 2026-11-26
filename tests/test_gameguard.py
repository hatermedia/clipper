from __future__ import annotations

import pytest

from clipper import gameguard


@pytest.fixture(autouse=True)
def _no_real_path_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gameguard, "running_process_paths", lambda: {})


def test_detects_rocket_league(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gameguard,
        "running_process_names",
        lambda: {"explorer.exe", "rocketleague.exe"},
    )
    assert gameguard.detect_running_game() == "Rocket League"


def test_detects_mimesis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gameguard,
        "running_process_names",
        lambda: {"mimesis-win64-shipping.exe"},
    )
    assert gameguard.detect_running_game() == "Mimesis"


def test_detects_new_unreal_title_by_process_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gameguard,
        "running_process_names",
        lambda: {"my-new-game-win64-shipping.exe"},
    )
    assert gameguard.detect_running_game() == "My New Game"


def test_detects_game_from_steam_library_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gameguard, "running_process_names", lambda: {"game.exe"})
    monkeypatch.setattr(
        gameguard,
        "running_process_paths",
        lambda: {
            "game.exe": r"D:\SteamLibrary\steamapps\common\SomeCoolGame\Binaries\Win64\game.exe"
        },
    )
    assert gameguard.detect_running_game() == "Some Cool Game"


def test_ignores_steam_tool_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gameguard, "running_process_names", lambda: {"wallpaper64.exe"})
    monkeypatch.setattr(
        gameguard,
        "running_process_paths",
        lambda: {
            "wallpaper64.exe": r"D:\SteamLibrary\steamapps\common\wallpaper_engine\wallpaper64.exe"
        },
    )
    assert gameguard.detect_running_game() is None


def test_ignores_riot_client_launcher_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gameguard,
        "running_process_names",
        lambda: {
            "RiotClientServices.exe",
            "RiotClientCrashHandler.exe",
            "RiotClientUX.exe",
            "Riot Client.exe",
            "explorer.exe",
        },
    )
    monkeypatch.setattr(
        gameguard,
        "running_process_paths",
        lambda: {
            "riotclientservices.exe": r"D:\Riot Games\Riot Client\RiotClientServices.exe",
            "riotclientcrashhandler.exe": r"D:\Riot Games\Riot Client\RiotClientCrashHandler.exe",
        },
    )
    assert gameguard.detect_running_game() is None


def test_ignores_common_launchers(monkeypatch: pytest.MonkeyPatch) -> None:
    launchers = {
        "steam.exe": r"D:\Steam\steam.exe",
        "leagueclient.exe": r"D:\Riot Games\League of Legends\LeagueClient.exe",
        "epicgameslauncher.exe": r"D:\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
        "battle.net.exe": r"D:\Battle.net\Battle.net.exe",
        "eadesktop.exe": r"D:\EA Desktop\EA Desktop\EADesktop.exe",
        "ubisoftconnect.exe": r"D:\Ubisoft\Ubisoft Connect\UbisoftConnect.exe",
        "galaxyclient.exe": r"D:\GOG Galaxy\GalaxyClient.exe",
        "xboxapp.exe": r"C:\Program Files\WindowsApps\Microsoft.GamingApp\XboxApp.exe",
        "playnite.desktopapp.exe": r"D:\Playnite\Playnite.DesktopApp.exe",
        "rockstarlauncher.exe": r"D:\Rockstar Games\Launcher\RockstarLauncher.exe",
        "itch.exe": r"D:\itch\itch.exe",
    }
    monkeypatch.setattr(
        gameguard, "running_process_names", lambda: set(launchers)
    )
    monkeypatch.setattr(
        gameguard, "running_process_paths", lambda: launchers
    )
    assert gameguard.detect_running_game() is None


def test_ignores_launcher_install_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gameguard, "running_process_names", lambda: {"helper.exe"}
    )
    monkeypatch.setattr(
        gameguard,
        "running_process_paths",
        lambda: {
            "helper.exe": r"D:\Riot Games\Riot Client\helper.exe",
        },
    )
    assert gameguard.detect_running_game() is None


def test_riot_game_still_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gameguard,
        "running_process_names",
        lambda: {"VALORANT-Win64-Shipping.exe", "RiotClientServices.exe"},
    )
    monkeypatch.setattr(gameguard, "running_process_paths", lambda: {})
    assert gameguard.detect_running_game() == "Valorant"


def test_custom_game_names(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    custom = tmp_path / "games.json"
    custom.write_text('{"mygame.exe": "My Game"}', encoding="utf-8")
    monkeypatch.setattr(gameguard, "custom_game_names_path", lambda: custom)
    monkeypatch.setattr(
        gameguard, "running_process_names", lambda: {"mygame.exe"}
    )
    assert gameguard.detect_running_game() == "My Game"


def test_no_game(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gameguard,
        "running_process_names",
        lambda: {"explorer.exe", "chrome.exe"},
    )
    assert gameguard.detect_running_game() is None


def test_title_map_contains_no_launchers() -> None:
    for exe in (
        "riotclient.exe",
        "riotclientservices.exe",
        "riotclientcrashhandler.exe",
        "leagueclient.exe",
        "steam.exe",
        "epicgameslauncher.exe",
        "battle.net.exe",
        "eadesktop.exe",
        "ubisoftconnect.exe",
        "galaxyclient.exe",
        "xboxapp.exe",
        "playnite.desktopapp.exe",
    ):
        assert exe not in gameguard.KNOWN_GAMES


def test_path_auto_detects_game() -> None:
    assert (
        gameguard.detect_game_from_path(r"D:\Videos\NVIDIA\Rocket League\clip.mp4")
        == "Rocket League"
    )
    assert (
        gameguard.detect_game_from_path(r"D:\Videos\NVIDIA\Mimesis\clip.mp4")
        == "Mimesis"
    )
    assert gameguard.detect_game_from_path(r"D:\Videos\misc\clip.mp4") is None
