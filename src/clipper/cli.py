from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import (
    ClipperError,
    DetectionSettings,
    FFmpegNotFound,
    default_threads,
    find_ffmpeg,
)
from .ffmpeg import ffmpeg_version, has_encoder, nvenc_available
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
            "  clipper --input ./footage --ai --ai-game Valorant --dry-run\n"
            "  clipper --input ./footage --reencode --encoder h264_nvenc\n"
            "  clipper update\n"
            "  clipper gpu\n"
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
        "--proxy-width",
        type=int,
        default=320,
        help="width of the low-res analysis proxy in pixels (default: 320)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="CPU thread cap; 0 = let FFmpeg decide (default: balanced half-core cap)",
    )
    parser.add_argument(
        "--gpu",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="use hardware decode + NVENC when available (default: auto)",
    )
    parser.add_argument(
        "--low-power",
        action="store_true",
        help="2 threads, 2fps/256px proxy, below-normal process priority",
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help="review candidates with a local vision model via Ollama",
    )
    parser.add_argument(
        "--ai-model",
        default="qwen2.5vl:7b",
        help="Ollama vision model (default: qwen2.5vl:7b)",
    )
    parser.add_argument(
        "--ai-game",
        default="generic",
        help="game context for the AI prompt, e.g. Valorant or Apex Legends",
    )
    parser.add_argument(
        "--ai-min-confidence",
        type=float,
        default=0.55,
        help="minimum AI confidence to keep a candidate (default: 0.55)",
    )
    parser.add_argument(
        "--ai-max-candidates",
        type=int,
        default=60,
        help="maximum candidates sent to the vision model (default: 60)",
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
        default="auto",
        choices=["auto", "libx264", "h264_nvenc", "hevc_nvenc", "libx265"],
        help="video encoder used with --reencode (default: auto = NVENC if available)",
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


def _run_gpu_check(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="clipper gpu", description="Check FFmpeg/NVENC/GPU capability")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    bins = find_ffmpeg()
    info: dict[str, object] = {
        "ffmpeg": ffmpeg_version(bins),
        "nvenc_h264_working": nvenc_available(bins),
        "nvenc_hevc_listed": has_encoder("hevc_nvenc", bins),
        "note": (
            "GPU acceleration covers the analysis proxy, re-encode, and local AI. "
            "OpenCV motion scoring and audio RMS remain CPU work."
        ),
    }
    try:
        from .detect.ai import DEFAULT_MODEL, ollama_status

        info["ollama"] = ollama_status()
        info["ai_default_model"] = DEFAULT_MODEL
    except Exception as exc:
        info["ollama"] = {"ok": False, "models": [], "error": str(exc)}
        info["ai_default_model"] = "qwen2.5vl:7b"
    smi = shutil.which("nvidia-smi")
    if smi:
        proc = subprocess.run(
            [
                smi,
                "--query-gpu=name,driver_version,utilization.gpu,utilization.encoder,utilization.decoder",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            errors="replace",
        )
        info["nvidia_smi"] = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    else:
        info["nvidia_smi"] = []

    if args.as_json:
        print(json.dumps(info, indent=2))
        return 0

    print(f"Clipper {__version__}")
    print(f"ffmpeg: {info['ffmpeg']}")
    print(f"NVENC H.264 test encode: {'PASS' if info['nvenc_h264_working'] else 'FAIL'}")
    print(f"NVENC HEVC encoder listed: {'yes' if info['nvenc_hevc_listed'] else 'no'}")
    if info["nvidia_smi"]:
        print("nvidia-smi: " + " | ".join(info["nvidia_smi"]))  # type: ignore[arg-type]
    else:
        print("nvidia-smi: not found")
    ollama = info.get("ollama") or {}
    if ollama.get("ok"):
        models = ", ".join(ollama.get("models", [])) or "(none)"
        print(f"Ollama vision models: {models}")
        print(f"AI review default: {info['ai_default_model']}")
    else:
        print(f"Ollama: unavailable ({ollama.get('error', 'not running')})")
    print(f"note: {info['note']}")
    if not info["nvenc_h264_working"]:
        print("Fix: update the NVIDIA driver, or run on the discrete GPU (laptops may need the NVIDIA GPU forced for this app).")
    return 0


def _run_desktop(argv: list[str]) -> int:
    try:
        from .desktop import main as desktop_main
    except ImportError:
        print(
            "The native desktop app needs PySide6. Install it with:\n"
            "  pip install 'clipper-gg[desktop]'\n"
            "or use the Windows portable build.",
            file=sys.stderr,
        )
        return 2
    return desktop_main(argv)


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
        threads=args.threads if args.threads is not None else default_threads(),
        proxy_width=args.proxy_width,
        gpu=False,
        ai=args.ai,
        ai_model=args.ai_model,
        ai_game=args.ai_game,
        ai_min_confidence=args.ai_min_confidence,
        ai_max_candidates=args.ai_max_candidates,
    )
    if args.low_power:
        settings.apply_low_power()
    settings.validate()

    bins = find_ffmpeg()
    nvenc = nvenc_available(bins)
    # Auto-enable GPU when it actually works; respect an explicit --no-gpu.
    gpu_enabled = bool(args.gpu) if args.gpu is not None else nvenc
    if gpu_enabled and not nvenc:
        print("! NVENC is not usable on this machine; the analysis proxy will use CPU.")
        gpu_enabled = False
    settings.gpu = gpu_enabled
    if args.reencode:
        if args.encoder == "auto":
            args.encoder = "h264_nvenc" if nvenc else "libx264"
        elif args.encoder in {"h264_nvenc", "hevc_nvenc"} and not has_encoder(args.encoder, bins):
            print(f"! {args.encoder} not available in this ffmpeg build; falling back to libx264")
            args.encoder = "libx264"
    if not args.quiet and not args.as_json:
        print(f"Clipper {__version__}")
        print(f"ffmpeg: {ffmpeg_version(bins)}")
        gpu_label = (
            "enabled (NVENC)" if gpu_enabled
            else ("available (off)" if nvenc else "unavailable")
        )
        print(
            f"performance: {settings.threads or 'auto'} threads | "
            f"proxy {settings.proxy_width}px @ {settings.sample_fps:g}fps | GPU: {gpu_label}"
        )
        if settings.ai:
            print(f"AI review: {settings.ai_model} | game: {settings.ai_game or 'generic'}")

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
                threads=settings.threads,
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
            if export_result.reencoded and not args.reencode:
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


def _run_update(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="clipper update",
        description="Check GitHub for a newer Clipper release and optionally install it.",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="download, verify, and run the Windows installer",
    )
    parser.add_argument("--yes", action="store_true", help="skip the install confirmation")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        from .update import (
            RELEASES_PAGE,
            UpdateError,
            check_for_update,
            download_installer,
            launch_installer,
        )

        release = check_for_update()
    except UpdateError as exc:
        if args.json:
            print(json.dumps({"current": __version__, "error": str(exc)}))
        else:
            print(f"Update check failed: {exc}", file=sys.stderr)
            print(f"Releases: {RELEASES_PAGE}", file=sys.stderr)
        return 1

    if release is None:
        if args.json:
            print(json.dumps({"current": __version__, "update": False}))
        else:
            print(f"Clipper {__version__} is up to date.")
        return 0

    if args.json and not args.install:
        print(
            json.dumps(
                {
                    "current": __version__,
                    "update": True,
                    "version": release.version,
                    "page_url": release.page_url,
                    "installer": release.installer_name,
                    "installer_size": release.installer_size,
                    "sha256_listed": release.has_checksums,
                }
            )
        )
        return 0

    print(f"Clipper {release.version} is available (you have {__version__}).")
    print(f"Release: {release.page_url}")
    if release.has_installer:
        size = release.installer_size / (1024 * 1024)
        print(f"Installer: {release.installer_name} ({size:.1f} MB)")
    else:
        print("This release has no Windows installer; download it from the release page.")
    notes = release.notes.strip()
    if notes:
        print("\nRelease notes:")
        for line in notes.splitlines()[:12]:
            print(f"  {line}")

    if not args.install:
        if release.has_installer:
            print("\nInstall it with: clipper update --install")
        return 0

    if not release.has_installer:
        print("Nothing to install automatically.", file=sys.stderr)
        return 1
    if sys.platform != "win32":
        print("The silent installer is Windows-only.", file=sys.stderr)
        return 1
    if not args.yes:
        try:
            answer = input("\nDownload and install now? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            print("Cancelled.")
            return 1

    last = [-1]

    def progress(done: int, total: int) -> None:
        percent = int(done * 100 / total) if total else 0
        if percent != last[0]:
            last[0] = percent
            print(f"\r  downloading {percent:3d}%", end="", flush=True)

    try:
        installer = download_installer(release, progress=progress)
    except UpdateError as exc:
        print(f"\nDownload failed: {exc}", file=sys.stderr)
        return 1
    print("\r  download complete; SHA-256 verified.          ")
    print(f"  {installer}")
    try:
        relaunch = bool(getattr(sys, "frozen", False))
        launch_installer(installer, relaunch=relaunch)
    except UpdateError as exc:
        print(f"Could not start the installer: {exc}", file=sys.stderr)
        return 1
    if relaunch:
        print("Installer started. Clipper will reopen when it finishes.")
    else:
        print("Installer started. Open Clipper from the Start Menu when it finishes.")
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    if raw and raw[0] in {"--version", "-V", "version"}:
        print(f"Clipper {__version__}")
        return 0

    if not raw:
        try:
            return _run_desktop([])
        except Exception as exc:
            print(f"Could not launch the desktop app: {exc}", file=sys.stderr)
            _build_batch_parser().print_help()
            return 1

    if raw[0] in {"update", "upgrade"}:
        return _run_update(raw[1:])

    if raw[0] in {"desktop", "app"}:
        return _run_desktop(raw[1:])

    if raw[0] in {"gpu", "doctor"}:
        return _run_gpu_check(raw[1:])

    if raw[0] in {"ui", "serve", "web"}:
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
