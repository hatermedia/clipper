from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import ClipperError, DetectionSettings, FFmpegNotFound, find_ffmpeg
from .ffmpeg import ffmpeg_version, has_encoder
from .models import AnalysisSummary, fmt_short, fmt_time
from .pipeline import analyze_target, export_analysis


def _build_batch_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clipper",
        description=(
            "Clipper - turn raw gaming footage into highlight clips. "
            "Hybrid audio + motion detection, smart padding, lossless FFmpeg cuts."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  clipper --input ./footage --dry-run\n"
            "  clipper --input ./footage --output ./clips --sensitivity 0.65\n"
            "  clipper --input ./footage --reencode --encoder h264_nvenc\n"
            "  clipper ui\n"
        ),
    )
    parser.add_argument("-i", "--input", required=True, help="input folder or single video")
    parser.add_argument(
        "-o",
        "--output",
        default="./trimmed",
        help="output folder (default: ./trimmed)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="detect highlights and write preview thumbnails without rendering",
    )
    parser.add_argument("--recursive", action="store_true", help="scan subfolders")
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=0.5,
        help="0..1, higher finds more moments (default: 0.5)",
    )
    parser.add_argument("--pre", type=float, default=8.0, help="seconds before peak (default: 8)")
    parser.add_argument("--post", type=float, default=5.0, help="seconds after peak (default: 5)")
    parser.add_argument(
        "--min-clip",
        type=float,
        default=3.0,
        help="discard clips shorter than this (default: 3)",
    )
    parser.add_argument(
        "--max-clips",
        type=int,
        default=30,
        help="maximum clips per video (default: 30)",
    )
    parser.add_argument(
        "--audio-weight",
        type=float,
        default=0.6,
        help="audio contribution to the fused score (default: 0.6)",
    )
    parser.add_argument(
        "--visual-weight",
        type=float,
        default=0.4,
        help="motion contribution to the fused score (default: 0.4)",
    )
    parser.add_argument(
        "--sample-fps",
        type=float,
        default=4.0,
        help="visual sampling rate for the proxy (default: 4)",
    )
    parser.add_argument(
        "--merge-gap",
        type=float,
        default=1.0,
        help="merge clips separated by this many seconds (default: 1)",
    )
    parser.add_argument(
        "--reencode",
        action="store_true",
        help="frame-accurate cuts with libx264/H.264 NVENC instead of stream copy",
    )
    parser.add_argument(
        "--encoder",
        default="libx264",
        choices=["libx264", "h264_nvenc", "hevc_nvenc", "libx265"],
        help="video encoder used with --reencode (default: libx264)",
    )
    parser.add_argument("--crf", type=int, default=20, help="quality for re-encode (default: 20)")
    parser.add_argument(
        "--preset",
        default="veryfast",
        help="x264 preset used with --reencode (default: veryfast)",
    )
    parser.add_argument(
        "--no-previews",
        action="store_true",
        help="skip preview thumbnails during --dry-run",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    parser.add_argument("--quiet", action="store_true", help="suppress progress output")
    parser.add_argument("--version", action="version", version=f"clipper {__version__}")
    return parser


def _build_ui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clipper ui",
        description="Launch the local Clipper web interface.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    parser.add_argument("--reload", action="store_true", help="auto-reload for development")
    return parser


def _run_ui(argv: list[str]) -> int:
    args = _build_ui_parser().parse_args(argv)
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required for the web UI. Install with: pip install uvicorn")
        return 2

    display_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{display_host}:{args.port}"
    print(f"Clipper UI: {url}")
    print("Local-only by default. Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        "clipper.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def _write_report(payload: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = output_dir / f"clipper-report-{stamp}.json"
    report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return report


def _print_summary(summary: AnalysisSummary, show_previews: bool = True) -> None:
    for analysis in summary.files:
        info = analysis.info
        if analysis.error:
            print(f"\n{analysis.name}")
            print(f"  ERROR: {analysis.error}")
            continue
        print(
            f"\n{analysis.name}  {fmt_short(info.duration)}  "
            f"{info.width}x{info.height}  {info.fps:.1f}fps"
        )
        if not analysis.clips:
            print("  No highlights detected. Try --sensitivity 0.7 or a longer --pre/--post.")
        for index, clip in enumerate(analysis.clips, start=1):
            print(
                f"  {index:02d}  {fmt_time(clip.start)} -> {fmt_time(clip.end)}  "
                f"{clip.duration:5.1f}s  score {clip.score_pct:3d}  [{clip.reason}]"
            )
            if show_previews and index - 1 < len(analysis.previews):
                print(f"      preview: {analysis.previews[index - 1]}")
        for warning in analysis.warnings:
            print(f"  ! {warning}")
    print(f"\nTotal: {summary.total_clips} clip(s) from {len(summary.files)} file(s)")


def _make_progress(quiet: bool, as_json: bool):
    if quiet or as_json:
        return None

    last_bucket = {"value": -1}

    def progress(fraction: float, message: str) -> None:
        bucket = int(fraction * 20)
        if bucket != last_bucket["value"]:
            last_bucket["value"] = bucket
            print(f"  {int(fraction * 100):3d}%  {message}")

    return progress


def _run_batch(args: argparse.Namespace) -> int:
    settings = DetectionSettings(
        sensitivity=args.sensitivity,
        pre=args.pre,
        post=args.post,
        min_clip=args.min_clip,
        max_clips=args.max_clips,
        audio_weight=args.audio_weight,
        visual_weight=args.visual_weight,
        sample_fps=args.sample_fps,
        merge_gap=args.merge_gap,
        preview=not args.no_previews,
    )
    settings.validate()

    bins = find_ffmpeg()
    if not args.quiet and not args.as_json:
        print(f"Clipper {__version__}")
        print(f"ffmpeg: {ffmpeg_version(bins)}")
        if args.reencode and args.encoder != "libx264" and not has_encoder(args.encoder, bins):
            print(f"! {args.encoder} not available in this ffmpeg build; falling back to libx264")
            args.encoder = "libx264"

    output_dir = Path(args.output).expanduser().resolve()
    preview_dir = output_dir / "previews" if args.dry_run and settings.preview else None
    progress = _make_progress(args.quiet, args.as_json)

    summary = analyze_target(
        args.input,
        settings,
        recursive=args.recursive,
        preview_dir=preview_dir,
        exclude=output_dir,
        progress=progress,
    )

    payload: dict[str, object] = {
        "tool": "clipper",
        "version": __version__,
        "ffmpeg": ffmpeg_version(bins),
        "dry_run": bool(args.dry_run),
        "summary": summary.to_dict(),
    }

    export_result = None
    if not args.dry_run:
        if summary.total_clips > 0:
            export_result = export_analysis(
                summary,
                output_dir=output_dir,
                reencode=args.reencode,
                encoder=args.encoder,
                crf=args.crf,
                preset=args.preset,
                progress=progress,
            )
            payload["export"] = export_result.to_dict()
        else:
            payload["export"] = {"outputs": [], "errors": [], "clips_total": 0}

    report_path = _write_report(payload, output_dir)
    payload["report"] = str(report_path)

    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        _print_summary(summary, show_previews=args.dry_run)
        if args.dry_run:
            print(f"\nDry run: nothing rendered. Report: {report_path}")
            if preview_dir is not None:
                print(f"Previews: {preview_dir}")
        elif export_result is not None:
            print(f"\nExported {len(export_result.outputs)} clip(s) to {output_dir}")
            for output in export_result.outputs:
                print(f"  {output}")
            if export_result.reencoded:
                print(
                    f"  ({len(export_result.reencoded)} clip(s) were re-encoded because "
                    "stream copy was not container-compatible.)"
                )
            for error in export_result.errors:
                print(f"  ERROR: {error}")
            if export_result.errors:
                print("  Tips: try --reencode, or check that the output folder is writable.")
            print(f"Report: {report_path}")

    had_errors = any(item.error for item in summary.files) or bool(
        export_result and export_result.errors
    )
    return 4 if had_errors else 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    if raw and raw[0] in {"ui", "serve", "web"}:
        return _run_ui(raw[1:])

    if raw and raw[0] in {"detect", "batch", "run", "trim"}:
        raw = raw[1:]

    parser = _build_batch_parser()
    args = parser.parse_args(raw)

    try:
        return _run_batch(args)
    except FFmpegNotFound as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (ClipperError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
