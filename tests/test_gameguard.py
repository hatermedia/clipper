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
