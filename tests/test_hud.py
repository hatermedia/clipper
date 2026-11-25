from clipper.detect.hud import HudLine, chat_cue, display_text, event_lines

import pytest


def test_round_banner_is_matched() -> None:
    lines = [HudLine(1.0, "WON"), HudLine(1.1, "ENEMY TEAM ELIMINATED")]
    hits = event_lines("round", lines)
    assert len(hits) == 2
    assert "WON" in display_text(hits)


def test_shot_on_goal_is_not_a_goal() -> None:
    lines = [HudLine(1.0, "SHOT ON GOAL"), HudLine(2.0, "LOVELYSCORED!")]
    hits = event_lines("goal", lines)
    assert len(hits) == 1
    assert display_text(hits, 1) == "LOVELY SCORED"


def test_auto_callout_is_not_chat_banter() -> None:
    lines = [
        HudLine(1.0, "(Broadcast)MrNegative spotted an ENEMY in B"),
        HudLine(2.0, "(Team) Tea: lol"),
    ]
    cue = chat_cue(lines)
    assert cue is not None
    assert "lol" in cue.text


def test_hud_display_cleans_concatenated_words() -> None:
    assert display_text([HudLine(1.0, "ENEMY TEAM ELIMINATED")], 1) == "ENEMY TEAM ELIMINATED"
    assert display_text([HudLine(1.0, "SPIKEDEFUSED")], 1) == "SPIKE DEFUSED"


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("round", "VICTORY"),
        ("round", "SPIKE DEFUSED"),
        ("goal", "GOAL SCORED"),
        ("multikill", "ACE"),
        ("multikill", "TRIPLE KILL"),
        ("clutch", "CLUTCH"),
        ("clutch", "1V3"),
        ("save", "EPIC SAVE"),
        ("demo", "DEMOLITION"),
    ],
)
def test_every_hud_event_kind_is_matched(kind: str, text: str) -> None:
    hits = event_lines(kind, [HudLine(1.0, text)])
    assert [line.text for line in hits] == [text]


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("goal", "SHOT ON GOAL"),
        ("round", "WONDERFUL"),
        ("multikill", "ACEVENTURA"),
        ("save", "SAVED BY THE BELL"),
        ("demo", "DEMONSTRATION"),
    ],
)
def test_hud_event_patterns_do_not_overmatch(kind: str, text: str) -> None:
    assert event_lines(kind, [HudLine(1.0, text)]) == []
