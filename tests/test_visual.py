from __future__ import annotations

import numpy as np

from clipper.detect.visual import motion_scores


def test_motion_scores_separates_action_from_static() -> None:
    calm = [np.full((180, 320, 3), 18, dtype=np.uint8) for _ in range(8)]
    action: list[np.ndarray] = []
    for index in range(8):
        frame = np.zeros((180, 320, 3), dtype=np.uint8)
        frame[:, : (index + 1) * 35] = 255
        action.append(frame)
    scores = motion_scores(calm + action)
    assert scores.size == 16
    assert float(scores[8:].max()) > float(scores[:8].max()) + 0.05


def test_motion_scores_empty() -> None:
    assert motion_scores([]).size == 0
