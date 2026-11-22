"""Hybrid highlight detection: audio spikes + visual motion, fused on one timeline."""

from .audio import ScoreTrack, analyze_audio, analyze_wav
from .merge import fuse_tracks, pick_peaks, resample_track
from .visual import analyze_visual

__all__ = [
    "ScoreTrack",
    "analyze_audio",
    "analyze_wav",
    "analyze_visual",
    "fuse_tracks",
    "pick_peaks",
    "resample_track",
]
