"""Automatic vertical and square reframing.

Gameplay is usually captured in 16:9 while Shorts, TikTok, and Reels need 9:16.
A center crop throws away the action. This module samples the source, follows
motion (or a detected facecam), smooths the crop path, and emits FFmpeg crop
commands that keep the action in frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MODES = ("auto", "action", "facecam", "center")
MOTION_WIDTH = 320
MOTION_THRESHOLD = 16
MIN_CONFIDENCE = 0.15

_CASCADE = None


class ReframeError(RuntimeError):
    """Raised when a reframe path cannot be planned."""


@dataclass(frozen=True)
class ReframeSample:
    time: float
    x: int
    y: int


@dataclass
class ReframePlan:
    source_width: int
    source_height: int
    crop_width: int
    crop_height: int
    samples: tuple[ReframeSample, ...]
    mode: str
    confidence: float
    reason: str

    @property
    def static_x(self) -> int:
        if not self.samples:
            return max(0, (self.source_width - self.crop_width) // 2)
        return int(np.median([sample.x for sample in self.samples]))

    @property
    def static_y(self) -> int:
        if not self.samples:
            return max(0, (self.source_height - self.crop_height) // 2)
        return int(np.median([sample.y for sample in self.samples]))

    def command_text(self) -> str:
        """sendcmd instructions for the crop filter.

        Times are relative to the start of the rendered clip because the export
        seeks before opening the input, which resets FFmpeg timestamps to zero.
        """

        lines: list[str] = []
        for sample in self.samples:
            x = max(0, min(self.source_width - self.crop_width, int(sample.x)))
            y = max(0, min(self.source_height - self.crop_height, int(sample.y)))
            lines.append(f"{max(0.0, sample.time):.3f} crop@reframe x {x};")
            lines.append(f"{max(0.0, sample.time):.3f} crop@reframe y {y};")
        return "\n".join(lines) + ("\n" if lines else "")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_width": self.source_width,
            "source_height": self.source_height,
            "crop_width": self.crop_width,
            "crop_height": self.crop_height,
            "mode": self.mode,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "samples": len(self.samples),
        }


def _even(value: float, minimum: int = 2) -> int:
    return max(minimum, int(round(value / 2.0)) * 2)


def crop_box(
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
) -> tuple[int, int]:
    """The largest target-aspect box that fits inside the source."""

    if source_width < 2 or source_height < 2:
        raise ReframeError("The source frame size is not usable.")
    if target_width < 1 or target_height < 1:
        raise ReframeError("The target frame size is not usable.")
    target_aspect = float(target_width) / float(target_height)
    source_aspect = float(source_width) / float(source_height)
    if source_aspect > target_aspect:
        crop_height = _even(source_height)
        crop_width = _even(crop_height * target_aspect)
    else:
        crop_width = _even(source_width)
        crop_height = _even(crop_width / target_aspect)
    crop_width = min(crop_width, _even(source_width))
    crop_height = min(crop_height, _even(source_height))
    return crop_width, crop_height


def _smooth(values: list[float], window: int = 7) -> list[float]:
    if len(values) < 3:
        return list(values)
    width = min(len(values) if len(values) % 2 == 1 else len(values) - 1, max(3, window))
    if width < 3:
        return list(values)
    try:
        from scipy.signal import savgol_filter

        return [float(item) for item in savgol_filter(values, width, 2)]
    except Exception:
        kernel = np.ones(width, dtype=np.float64) / width
        padded = np.pad(np.asarray(values, dtype=np.float64), (width // 2, width // 2), mode="edge")
        return [float(item) for item in np.convolve(padded, kernel, mode="valid")][: len(values)]


def _limit_speed(
    values: list[float],
    times: list[float],
    max_pixels_per_second: float,
) -> list[float]:
    if not values or len(values) != len(times):
        return list(values)
    limited = [float(values[0])]
    for index in range(1, len(values)):
        delta_t = max(0.001, times[index] - times[index - 1])
        limit = max_pixels_per_second * delta_t
        previous = limited[-1]
        target = float(values[index])
        limited.append(previous + max(-limit, min(limit, target - previous)))
    return limited


def track_from_centers(
    times: list[float],
    centers_x: list[float],
    centers_y: list[float],
    *,
    source_width: int,
    source_height: int,
    crop_width: int,
    crop_height: int,
) -> tuple[list[int], list[int], float]:
    """Convert motion/face centers into a smooth, clamped crop path."""

    if not times or len(times) != len(centers_x) or len(times) != len(centers_y):
        raise ReframeError("Not enough tracking samples to build a crop path.")
    xs = [center - crop_width / 2.0 for center in centers_x]
    ys = [center - crop_height / 2.0 for center in centers_y]
    xs = _smooth(xs)
    ys = _smooth(ys)
    max_x = max(0, source_width - crop_width)
    max_y = max(0, source_height - crop_height)
    xs = _limit_speed(xs, times, max_pixels_per_second=max(80.0, source_width * 0.55))
    ys = _limit_speed(ys, times, max_pixels_per_second=max(60.0, source_height * 0.55))
    clamped_x = [int(round(max(0.0, min(max_x, value)))) for value in xs]
    clamped_y = [int(round(max(0.0, min(max_y, value)))) for value in ys]
    movement = float(np.mean(np.abs(np.diff(clamped_x)))) if len(clamped_x) > 1 else 0.0
    confidence = min(1.0, 0.35 + movement / max(1.0, source_width * 0.08))
    return clamped_x, clamped_y, confidence


def _cascade():
    global _CASCADE
    if _CASCADE is not None:
        return _CASCADE
    try:
        path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(str(path))
        if cascade.empty():
            return None
    except Exception:
        return None
    _CASCADE = cascade
    return cascade


def _face_center(frame_bgr: np.ndarray) -> tuple[float, float] | None:
    cascade = _cascade()
    if cascade is None:
        return None
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    try:
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.12,
            minNeighbors=5,
            minSize=(max(18, width // 20), max(18, height // 20)),
            maxSize=(max(32, width // 2), max(32, height // 2)),
        )
    except cv2.error:
        return None
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda box: int(box[2]) * int(box[3]))
    return float(x + w / 2), float(y + h / 2)


def _motion_center(current: np.ndarray, previous: np.ndarray) -> tuple[float, float, float]:
    diff = cv2.absdiff(current, previous)
    diff = cv2.GaussianBlur(diff, (0, 0), 3)
    _, mask = cv2.threshold(diff, MOTION_THRESHOLD, 255, cv2.THRESH_TOZERO)
    total = float(mask.sum())
    if total <= 1.0:
        height, width = mask.shape[:2]
        return width / 2.0, height / 2.0, 0.0
    ys, xs = np.nonzero(mask)
    weights = mask[ys, xs].astype(np.float64)
    weight_total = float(weights.sum())
    if weight_total <= 1.0:
        height, width = mask.shape[:2]
        return width / 2.0, height / 2.0, 0.0
    cx = float((xs * weights).sum() / weight_total)
    cy = float((ys * weights).sum() / weight_total)
    activity = min(1.0, weight_total / float(mask.size))
    return cx, cy, activity


def plan_reframe(
    video: str | Path,
    start: float,
    end: float,
    target_width: int,
    target_height: int,
    *,
    mode: str = "auto",
    sample_fps: float = 2.0,
    max_samples: int = 240,
) -> ReframePlan:
    """Sample a clip and produce a smoothed crop path.

    ``mode`` may be ``auto``/``action`` (motion centroid), ``facecam`` (largest
    stable face), or ``center`` (no tracking). A failed facecam read falls back
    to motion instead of failing the export.
    """

    chosen_mode = str(mode or "auto").strip().lower()
    if chosen_mode == "none":
        chosen_mode = "center"
    if chosen_mode not in MODES:
        chosen_mode = "auto"
    if chosen_mode == "auto":
        chosen_mode = "action"
    if end <= start:
        raise ReframeError("The clip has no duration to reframe.")

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ReframeError("OpenCV could not open the source video.")
    try:
        source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0) or 30.0
        if source_width < 2 or source_height < 2:
            raise ReframeError("OpenCV could not read the source frame size.")
        crop_width, crop_height = crop_box(
            source_width, source_height, target_width, target_height
        )
        if (
            chosen_mode == "center"
            or (crop_width >= source_width and crop_height >= source_height)
        ):
            center = ReframePlan(
                source_width=source_width,
                source_height=source_height,
                crop_width=crop_width,
                crop_height=crop_height,
                samples=(
                    ReframeSample(
                        0.0,
                        max(0, (source_width - crop_width) // 2),
                        max(0, (source_height - crop_height) // 2),
                    ),
                ),
                mode="center",
                confidence=1.0,
                reason="center crop",
            )
            return center

        duration = max(0.05, end - start)
        step = max(0.25, 1.0 / max(0.25, float(sample_fps)))
        count = max(2, min(int(max_samples), int(math.ceil(duration / step)) + 1))
        step = max(step, duration / max(1, count - 1))
        start_frame = max(0, int(round(start * fps)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, float(start_frame))

        times: list[float] = []
        centers_x: list[float] = []
        centers_y: list[float] = []
        face_x: list[float] = []
        face_y: list[float] = []
        activity: list[float] = []
        previous = None
        frame_index = start_frame
        next_time = start
        attempts = 0
        max_attempts = max(count * 4, int(duration * fps) + 10)
        while len(times) < count and attempts < max_attempts:
            attempts += 1
            if not capture.grab():
                break
            now = frame_index / fps
            frame_index += 1
            if now + 1e-6 < next_time:
                continue
            ok, frame = capture.retrieve()
            if not ok or frame is None:
                continue
            resized = cv2.resize(
                frame,
                (MOTION_WIDTH, max(2, int(frame.shape[0] * MOTION_WIDTH / max(1, frame.shape[1])))),
                interpolation=cv2.INTER_AREA,
            )
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            if previous is not None:
                cx, cy, amount = _motion_center(gray, previous)
                scale_x = source_width / float(gray.shape[1])
                scale_y = source_height / float(gray.shape[0])
                times.append(max(0.0, now - start))
                centers_x.append(cx * scale_x)
                centers_y.append(cy * scale_y)
                activity.append(amount)
            previous = gray
            if chosen_mode == "facecam":
                face = _face_center(frame)
                if face is not None:
                    face_x.append(face[0])
                    face_y.append(face[1])
            next_time += step
    finally:
        capture.release()

    if len(times) < 2:
        raise ReframeError("The clip was too short to track.")
    if chosen_mode == "facecam" and len(face_x) >= max(2, len(times) // 3):
        centers_x = list(face_x[-len(times):])
        centers_y = list(face_y[-len(times):])
        if len(centers_x) < len(times):
            centers_x = [face_x[0]] * (len(times) - len(centers_x)) + centers_x
            centers_y = [face_y[0]] * (len(times) - len(centers_y)) + centers_y
        reason = "facecam tracking"
    elif chosen_mode == "center" or not any(activity):
        centers_x = [source_width / 2.0] * len(times)
        centers_y = [source_height / 2.0] * len(times)
        reason = "center crop"
    else:
        reason = "action tracking"

    xs, ys, confidence = track_from_centers(
        times,
        centers_x,
        centers_y,
        source_width=source_width,
        source_height=source_height,
        crop_width=crop_width,
        crop_height=crop_height,
    )
    samples = tuple(
        ReframeSample(time=times[index], x=xs[index], y=ys[index])
        for index in range(len(times))
    )
    if samples[0].time > 0.001:
        samples = (ReframeSample(0.0, samples[0].x, samples[0].y), *samples)
    return ReframePlan(
        source_width=source_width,
        source_height=source_height,
        crop_width=crop_width,
        crop_height=crop_height,
        samples=samples,
        mode=chosen_mode,
        confidence=confidence,
        reason=reason,
    )


def center_plan(
    video: str | Path,
    target_width: int,
    target_height: int,
) -> ReframePlan:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ReframeError("OpenCV could not open the source video.")
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        capture.release()
    crop_width, crop_height = crop_box(width, height, target_width, target_height)
    return ReframePlan(
        source_width=width,
        source_height=height,
        crop_width=crop_width,
        crop_height=crop_height,
        samples=(
            ReframeSample(
                0.0,
                max(0, (width - crop_width) // 2),
                max(0, (height - crop_height) // 2),
            ),
        ),
        mode="center",
        confidence=1.0,
        reason="center crop",
    )
