from __future__ import annotations

from clipper.cli import _build_batch_parser
from clipper.presets import DEFAULT_TEMPLATE


def test_cli_accepts_creator_preset_and_reframe() -> None:
    args = _build_batch_parser().parse_args(
        [
            "--input",
            "footage",
            "--export-preset",
            "shorts",
            "--reframe",
            "facecam",
            "--name-template",
            "{game}_{index:02d}",
        ]
    )
    assert args.export_preset == "shorts"
    assert args.reframe == "facecam"
    assert args.name_template == "{game}_{index:02d}"


def test_cli_format_alias_and_defaults() -> None:
    args = _build_batch_parser().parse_args(
        ["--input", "footage", "--format", "square"]
    )
    assert args.export_preset == "square"
    assert args.reframe == "auto"
    assert args.name_template == DEFAULT_TEMPLATE
