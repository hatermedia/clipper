from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d

from .audio import ScoreTrack

PROXY_WIDTH = 320
PROXY_HEIGHT = 180


def motion_scores(frames: list[np.ndarray]) -> np.ndarray:
    """Compute per-frame visual activity from grayscale/BGR frames.

    Combines mean absolute difference (camera flicks, explosions), the 90th
    percentile difference (small bright flashes such as kill-feed popups), and
    whole-frame brightness changes (flashes / fades).
    """

    if not frames:
        return np.array([])

    scores = np.zeros(len(frames), dtype=np.float32)
    prev: np.ndarray | None = None
    prev_mean = 0.0
    for index, frame in enumerate(frames):
        if frame.ndim == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        gray = cv2.resize(gray, (PROXY_WIDTH, PROXY_HEIGHT), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        mean = float(gray.mean())
        if prev is not None:
            diff = cv2.absdiff(gray, prev)
            motion = float(diff.mean()) / 255.0
            strong = float(np.percentile(diff, 90)) / 255.0
            flash = abs(mean - prev_mean) / 255.0
            scores[index] = 0.55 * motion + 0.35 * strong + 0.10 * flash
        prev = gray
        prev_mean = mean
    return scores


def _normalise(scores: np.ndarray, sample_fps: float) -> np.ndarray:
    if scores.size == 0:
        return scores
    p99 = float(np.percentile(scores, 99))
    if p99 < 0.01:
        return np.zeros_like(scores)

    # Raw frame-differencing is tiny during smooth camera motion and huge on a
    # hard cut. Combine a p95-scaled signal with a percentile rank so sustained
    # action is visible without letting one scene cut flatten everything else.
    p95 = max(float(np.percentile(scores, 95)), 1e-4)
    scaled = np.clip(scores / p95, 0.0, 1.0)
    order = np.argsort(np.argsort(scores)).astype(np.float32)
    rank = order / max(1.0, float(scores.size - 1))
    combined = 0.65 * scaled + 0.35 * rank

    combined = np.clip(combined, 0.0, 1.0)
    peak = float(np.percentile(combined, 99))
    if peak > 0:
        combined = np.clip(combined / peak, 0.0, 1.0)
    sigma = max(0.5, 0.6 * sample_fps)
    return gaussian_filter1d(combined, sigma=sigma, mode="nearest").astype(np.float32)


def analyze_visual(proxy_path: Path | str, sample_fps: float = 4.0) -> ScoreTrack:
    """Read the low-fps proxy with OpenCV and score visual activity."""

    cap = cv2.VideoCapture(str(proxy_path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open proxy video: {proxy_path}")

    actual_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if actual_fps <= 0.1:
        actual_fps = sample_fps

    scores: list[float] = []
    prev: np.ndarray | None = None
    prev_mean = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            mean = float(gray.mean())
            if prev is None:
                scores.append(0.0)
            else:
                diff = cv2.absdiff(gray, prev)
                motion = float(diff.mean()) / 255.0
                strong = float(np.percentile(diff, 90)) / 255.0
                flash = abs(mean - prev_mean) / 255.0
                scores.append(0.55 * motion + 0.35 * strong + 0.10 * flash)
            prev = gray
            prev_mean = mean
    finally:
        cap.release()

    raw = np.asarray(scores, dtype=np.float32)
    if raw.size == 0:
        return ScoreTrack(np.array([]), np.array([]))
    times = np.arange(raw.size, dtype=np.float64) / actual_fps
    return ScoreTrack(times, _normalise(raw, actual_fps))
