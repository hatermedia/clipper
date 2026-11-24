from __future__ import annotations

from clipper import gameguard


def test_detects_rocket_league(monkeypatch) -> None:
    monkeypatch.setattr(
        gameguard,
        "running_process_names",
        lambda: {"explorer.exe", "rocketleague.exe"},
    )
    assert gameguard.detect_running_game() == "Rocket League"


def test_detects_mimesis(monkeypatch) -> None:
    monkeypatch.setattr(
        gameguard,
        "running_process_names",
        lambda: {"mimesis-win64-shipping.exe"},
    )
    assert gameguard.detect_running_game() == "Mimesis"


def test_no_game(monkeypatch) -> None:
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

