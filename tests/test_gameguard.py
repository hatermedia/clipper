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
