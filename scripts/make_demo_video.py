"""Generate a synthetic 46-second "gameplay" clip with known action windows.

Calm segments use a slow-moving box and quiet pink noise. Action segments use
FFmpeg's testsrc2 pattern and a loud 440 Hz tone, so both detectors have a clear
signal at t=12-20s and t=30-38s.

Usage:
    python scripts/make_demo_video.py --output demo/demo_gameplay.mp4
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SEGMENTS = [
    ("calm", 12.0),
    ("action", 8.0),
    ("calm", 10.0),
    ("action", 8.0),
    ("calm", 8.0),
]
ACTION_WINDOWS = [(12.0, 20.0), (30.0, 38.0)]


def resolve_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        from clipper.config import find_ffmpeg

        return str(find_ffmpeg().ffmpeg)
    except Exception as exc:
        raise SystemExit(
            "ffmpeg not found. Install it and add it to PATH, or set CLIPPER_FFMPEG."
        ) from exc


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-3000:])
        raise SystemExit(f"ffmpeg failed with exit code {proc.returncode}")


def render_calm(ffmpeg: str, output: Path, duration: float) -> None:
    filter_graph = (
        "[0:v][1:v]overlay="
        "x='60+34*t':y='280+45*sin(t/2)':shortest=1,"
        "drawgrid=w=80:h=80:t=1:c=0x1e293b@0.35,"
        "drawbox=x=iw/2-5:y=ih/2-5:w=10:h=10:color=0xf43f5e@0.8:t=fill,"
        "format=yuv420p[v]"
    )
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x0a1020:s=1280x720:r=30:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x1e88e5:s=160x160:r=30:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=color=pink:amplitude=0.012:sample_rate=48000:duration={duration}",
            "-filter_complex",
            filter_graph,
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(output),
        ]
    )


def render_action(ffmpeg: str, output: Path, duration: float) -> None:
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "life=s=1280x720:r=30:mold=10:ratio=0.12:"
            "life_color=0x22d3ee:death_color=0x0b1220:stitch=0",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-filter_complex",
            "[0:v]eq=contrast=1.15:saturation=1.25,"
            "drawgrid=w=80:h=80:t=1:c=0x1e293b@0.35,"
            "drawbox=x=iw/2-5:y=ih/2-5:w=10:h=10:color=0xf43f5e@0.8:t=fill,"
            "format=yuv420p[v];[1:a]volume=0.55[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{duration}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(output),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="demo/demo_gameplay.mp4", help="output MP4 path")
    parser.add_argument("--keep-segments", action="store_true", help="keep intermediate clips")
    args = parser.parse_args()

    ffmpeg = resolve_ffmpeg()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="clipper_demo_") as temp_raw:
        temp = Path(temp_raw)
        list_file = temp / "concat.txt"
        lines: list[str] = []
        cursor = 0.0
        print(f"Generating {sum(d for _, d in SEGMENTS):.0f}s synthetic gameplay -> {output}")
        for index, (kind, duration) in enumerate(SEGMENTS):
            segment = temp / f"segment_{index:02d}.mp4"
            if kind == "action":
                render_action(ffmpeg, segment, duration)
            else:
                render_calm(ffmpeg, segment, duration)
            lines.append(f"file '{segment.as_posix()}'")
            cursor += duration
            print(f"  {kind:<6} {duration:5.1f}s  (t={cursor - duration:.0f}-{cursor:.0f})")
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )

        if args.keep_segments:
            kept = output.parent / "segments"
            kept.mkdir(exist_ok=True)
            for segment in temp.glob("segment_*.mp4"):
                shutil.copy2(segment, kept / segment.name)

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"Done: {output} ({size_mb:.1f} MB)")
    print("Expected highlight windows: " + ", ".join(f"{a:.0f}-{b:.0f}s" for a, b in ACTION_WINDOWS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
