"""Native Qt desktop app for Clipper.

This is the primary Windows experience: native folder picker, drag-and-drop,
GPU/NVENC toggle, CPU caps, low-power mode, previews, and export without a
browser or a permanently open command prompt.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .config import (
    Cancelled,
    ClipperError,
    DetectionSettings,
    default_threads,
    find_ffmpeg,
    set_low_priority,
)
from .ffmpeg import FFmpegError, ffmpeg_version, has_encoder
from .models import AnalysisSummary
from .pipeline import analyze_target, export_analysis, scan_inputs

ASSET_DIR = Path(__file__).resolve().parent / "assets"
VIDEO_ICON = ASSET_DIR / "icon.png"


STYLESHEET = """
QWidget {
    background: #06090f;
    color: #e2e8f0;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}
QMainWindow { background: #06090f; }
QFrame#Panel {
    background: #0b111b;
    border: 1px solid #1f2d40;
    border-radius: 14px;
}
QFrame#DropZone {
    background: #070c14;
    border: 1px dashed #2a3b52;
    border-radius: 12px;
}
QFrame#DropZone:hover { border-color: #22d3ee; }
QLabel#Brand { font-size: 16px; font-weight: 800; letter-spacing: 2px; color: white; }
QLabel#BrandSub { color: #64748b; font-size: 10px; }
QLabel#Section { font-size: 13px; font-weight: 700; color: white; }
QLabel#Muted { color: #94a3b8; font-size: 11px; }
QLabel#Status { color: #67e8f9; font-size: 11px; }
QLabel#Summary { color: #94a3b8; font-size: 12px; }
QLabel#Preview {
    background: #070c14;
    border: 1px solid #1f2d40;
    border-radius: 10px;
    color: #64748b;
}
QPushButton {
    background: #111a27;
    border: 1px solid #24344a;
    border-radius: 8px;
    padding: 7px 12px;
    color: #e2e8f0;
}
QPushButton:hover { border-color: #22d3ee; background: #13202f; }
QPushButton:pressed { background: #0d1724; }
QPushButton#Primary {
    background: #22d3ee;
    color: #041018;
    font-weight: 700;
    border: none;
    padding: 9px 16px;
}
QPushButton#Primary:hover { background: #67e8f9; }
QPushButton#Primary:disabled { background: #164e63; color: #64748b; }
QPushButton:disabled { color: #64748b; background: #0b111b; border-color: #1a2536; }
QLineEdit, QComboBox, QSpinBox {
    background: #070c14;
    border: 1px solid #24344a;
    border-radius: 7px;
    padding: 6px 8px;
    color: #e2e8f0;
    selection-background-color: #164e63;
}
QComboBox QAbstractItemView {
    background: #0b111b;
    border: 1px solid #24344a;
    selection-background-color: #164e63;
}
QCheckBox { color: #cbd5e1; spacing: 7px; }
QGroupBox {
    border: 1px solid #1f2d40;
    border-radius: 10px;
    margin-top: 12px;
    padding: 12px 10px 8px 10px;
    color: #94a3b8;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QSlider::groove:horizontal { height: 5px; background: #1e293b; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 15px; margin: -5px 0; border-radius: 7px; background: #22d3ee;
}
QSlider::sub-page:horizontal { background: #22d3ee; border-radius: 2px; }
QProgressBar {
    background: #111a27; border: 1px solid #24344a; border-radius: 5px;
    text-align: center; color: #94a3b8; height: 14px; font-size: 10px;
}
QProgressBar::chunk { background: #22d3ee; border-radius: 5px; }
QTreeWidget {
    background: #070c14; border: 1px solid #1f2d40; border-radius: 10px;
    alternate-background-color: #0b111b;
}
QTreeWidget::item { padding: 4px; }
QTreeWidget::item:selected { background: #123041; color: white; }
QHeaderView::section {
    background: #0b111b; color: #94a3b8; border: 0;
    border-bottom: 1px solid #1f2d40; padding: 6px;
}
QListWidget {
    background: #070c14; border: 1px solid #1f2d40; border-radius: 8px;
    color: #94a3b8;
}
QScrollArea { border: none; background: transparent; }
QToolTip { background: #0b111b; color: #e2e8f0; border: 1px solid #24344a; }
"""


class AnalyzeWorker(QThread):
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, settings: DetectionSettings, recursive: bool, preview_dir: Path) -> None:
        super().__init__()
        self.path = path
        self.settings = settings
        self.recursive = recursive
        self.preview_dir = preview_dir
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _progress(self, fraction: float, message: str) -> None:
        if self._cancel:
            raise Cancelled("cancelled")
        self.progress.emit(fraction, message)

    def run(self) -> None:
        try:
            summary = analyze_target(
                self.path,
                self.settings,
                recursive=self.recursive,
                preview_dir=self.preview_dir,
                progress=self._progress,
            )
            self.done.emit(summary)
        except Cancelled:
            self.failed.emit("Cancelled")
        except Exception as exc:
            self.failed.emit(str(exc))


class ExportWorker(QThread):
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        summary: AnalysisSummary,
        output_dir: str,
        reencode: bool,
        encoder: str,
        crf: int,
        threads: int,
    ) -> None:
        super().__init__()
        self.summary = summary
        self.output_dir = output_dir
        self.reencode = reencode
        self.encoder = encoder
        self.crf = crf
        self.threads = threads
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _progress(self, fraction: float, message: str) -> None:
        if self._cancel:
            raise Cancelled("cancelled")
        self.progress.emit(fraction, message)

    def run(self) -> None:
        try:
            result = export_analysis(
                self.summary,
                output_dir=self.output_dir,
                reencode=self.reencode,
                encoder=self.encoder,
                crf=self.crf,
                preset="veryfast",
                progress=self._progress,
                threads=self.threads,
            )
            self.done.emit(result)
        except Cancelled:
            self.failed.emit("Cancelled")
        except Exception as exc:
            self.failed.emit(str(exc))


class DropZone(QFrame):
    pathDropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(82)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(2)
        title = QLabel("Drop a folder or video here")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        subtitle = QLabel("or use Browse to pick a folder")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("Muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.pathDropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return


class MainWindow(QMainWindow):
    def __init__(self, initial_input: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"Clipper {__version__}")
        self.resize(1280, 840)
        self.setMinimumSize(1040, 720)
        if VIDEO_ICON.is_file():
            self.setWindowIcon(QIcon(str(VIDEO_ICON)))

        self.qsettings = QSettings("hatermedia", "Clipper")
        self.summary: AnalysisSummary | None = None
        self.worker: AnalyzeWorker | None = None
        self.export_worker: ExportWorker | None = None
        self.preview_dir = Path(tempfile.mkdtemp(prefix="clipper-desktop-"))
        self.files: list[Path] = []
        self.last_output_dir: str | None = None
        self.nvenc = False
        self._screenshot_path: Path | None = None

        try:
            bins = find_ffmpeg()
            self.ffmpeg_ok = True
            self.ffmpeg_text = ffmpeg_version(bins)
            self.nvenc = has_encoder("h264_nvenc", bins)
        except Exception:
            self.ffmpeg_ok = False
            self.ffmpeg_text = "FFmpeg not found"
            self.nvenc = False

        self._build_ui()
        self._restore_settings()
        if initial_input:
            self.set_input(initial_input, scan=False)
        self._update_status()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 12, 18, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        logo = QLabel()
        if VIDEO_ICON.is_file():
            pix = QPixmap(str(VIDEO_ICON)).scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo.setPixmap(pix)
        header.addWidget(logo)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel("CLIPPER")
        brand.setObjectName("Brand")
        sub = QLabel("native gameplay highlight trimmer")
        sub.setObjectName("BrandSub")
        brand_box.addWidget(brand)
        brand_box.addWidget(sub)
        header.addLayout(brand_box)
        header.addStretch(1)
        self.gpu_label = QLabel("GPU: checking…")
        self.gpu_label.setObjectName("Status")
        self.ffmpeg_label = QLabel("FFmpeg: checking…")
        self.ffmpeg_label.setObjectName("Muted")
        header.addWidget(self.ffmpeg_label)
        header.addWidget(self.gpu_label)
        github = QPushButton("GitHub ↗")
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/hatermedia/clipper")))
        header.addWidget(github)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        # ---------------- left controls ----------------
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel.setMinimumWidth(370)
        left_panel.setMaximumWidth(410)
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(16, 16, 16, 16)
        left.setSpacing(10)

        left.addWidget(self._section("1 · Footage"))
        path_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("No folder selected")
        self.input_edit.editingFinished.connect(lambda: self.set_input(self.input_edit.text(), scan=False))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_folder)
        path_row.addWidget(self.input_edit, 1)
        path_row.addWidget(browse)
        left.addLayout(path_row)

        self.drop = DropZone()
        self.drop.pathDropped.connect(lambda p: self.set_input(p, scan=True))
        left.addWidget(self.drop)

        row = QHBoxLayout()
        self.recursive = QCheckBox("Include subfolders")
        row.addWidget(self.recursive)
        row.addStretch(1)
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.clicked.connect(self.scan)
        row.addWidget(self.scan_btn)
        left.addLayout(row)

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(105)
        self.file_list.setSelectionMode(QAbstractItemView.NoSelection)
        left.addWidget(self.file_list)

        left.addSpacing(6)
        left.addWidget(self._section("2 · Detection"))
        sensitivity_row = QHBoxLayout()
        sensitivity_row.addWidget(QLabel("Sensitivity"))
        sensitivity_row.addStretch(1)
        self.sensitivity_value = QLabel("50%")
        self.sensitivity_value.setObjectName("Status")
        sensitivity_row.addWidget(self.sensitivity_value)
        left.addLayout(sensitivity_row)
        self.sensitivity = QSlider(Qt.Horizontal)
        self.sensitivity.setRange(0, 100)
        self.sensitivity.setValue(50)
        self.sensitivity.valueChanged.connect(self._sensitivity_changed)
        left.addWidget(self.sensitivity)

        presets = QHBoxLayout()
        for label, value in (("Strict", 32), ("Balanced", 50), ("Loose", 78)):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, v=value: self.sensitivity.setValue(v))
            presets.addWidget(button)
        left.addLayout(presets)

        pad = QGridLayout()
        pad.addWidget(QLabel("Pre-roll (s)"), 0, 0)
        pad.addWidget(QLabel("Post-roll (s)"), 0, 1)
        self.pre = QSpinBox()
        self.pre.setRange(0, 120)
        self.pre.setValue(8)
        self.post = QSpinBox()
        self.post.setRange(0, 120)
        self.post.setValue(5)
        pad.addWidget(self.pre, 1, 0)
        pad.addWidget(self.post, 1, 1)
        left.addLayout(pad)

        self.advanced_toggle = QPushButton("Advanced tuning  ▾")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        left.addWidget(self.advanced_toggle)

        self.advanced = QFrame()
        advanced_layout = QGridLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setHorizontalSpacing(8)
        advanced_layout.setVerticalSpacing(7)
        advanced_layout.addWidget(QLabel("Max clips"), 0, 0)
        self.max_clips = QSpinBox()
        self.max_clips.setRange(1, 200)
        self.max_clips.setValue(30)
        advanced_layout.addWidget(self.max_clips, 0, 1)
        advanced_layout.addWidget(QLabel("Sample FPS"), 1, 0)
        self.sample_fps = QComboBox()
        for label, value in (("2 fps", 2.0), ("4 fps", 4.0), ("8 fps", 8.0)):
            self.sample_fps.addItem(label, value)
        self.sample_fps.setCurrentIndex(1)
        advanced_layout.addWidget(self.sample_fps, 1, 1)
        advanced_layout.addWidget(QLabel("Proxy width"), 2, 0)
        self.proxy_width = QComboBox()
        for label, value in (("256 px", 256), ("320 px", 320), ("480 px", 480)):
            self.proxy_width.addItem(label, value)
        self.proxy_width.setCurrentIndex(1)
        advanced_layout.addWidget(self.proxy_width, 2, 1)
        advanced_layout.addWidget(QLabel("CPU threads"), 3, 0)
        self.threads = QComboBox()
        self.threads.addItem("Balanced", default_threads())
        self.threads.addItem("Low (2)", 2)
        self.threads.addItem("Max (all)", 0)
        advanced_layout.addWidget(self.threads, 3, 1)
        self.gpu = QCheckBox("Use NVIDIA GPU (NVENC)")
        self.gpu.setToolTip("Hardware decode + NVENC for the analysis proxy; NVENC for re-encode.")
        advanced_layout.addWidget(self.gpu, 4, 0, 1, 2)
        self.low_power = QCheckBox("Low-power mode")
        self.low_power.setToolTip("Caps threads at 2, uses a 256px/2fps proxy, and lowers process priority.")
        advanced_layout.addWidget(self.low_power, 5, 0, 1, 2)
        advanced_layout.addWidget(
            QLabel("GPU helps encoding; decoding may still use CPU depending on the codec."),
            6, 0, 1, 2,
        )
        self.advanced.setVisible(False)
        left.addWidget(self.advanced)

        self.analyze_btn = QPushButton("Detect highlights")
        self.analyze_btn.setObjectName("Primary")
        self.analyze_btn.clicked.connect(self.analyze)
        left.addWidget(self.analyze_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        left.addWidget(self.progress)
        self.status = QLabel("Ready")
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        left.addWidget(self.status)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_current)
        left.addWidget(self.cancel_btn)
        left.addStretch(1)

        left_scroll.setWidget(left_panel)
        splitter.addWidget(left_scroll)

        # ---------------- right results ----------------
        right_panel = QFrame()
        right_panel.setObjectName("Panel")
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(16, 16, 16, 16)
        right.setSpacing(10)

        results_header = QHBoxLayout()
        results_header.addWidget(self._section("Highlights"))
        results_header.addStretch(1)
        self.summary_label = QLabel("Nothing analyzed yet")
        self.summary_label.setObjectName("Summary")
        results_header.addWidget(self.summary_label)
        right.addLayout(results_header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["Clip", "Start", "End", "Length", "Score", "Signal"])
        self.tree.setIconSize(QSize(104, 58))
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(5, QHeaderView.Stretch)
        self.tree.currentItemChanged.connect(self._show_preview)
        right.addWidget(self.tree, 1)

        self.preview = QLabel("Select a clip to preview its peak frame")
        self.preview.setObjectName("Preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(170)
        self.preview.setMaximumHeight(210)
        right.addWidget(self.preview)

        export_group = QGroupBox("Export")
        export_layout = QGridLayout(export_group)
        export_layout.setHorizontalSpacing(8)
        export_layout.setVerticalSpacing(7)
        export_layout.addWidget(QLabel("Output"), 0, 0)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose an output folder")
        export_layout.addWidget(self.output_edit, 0, 1)
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self.choose_output)
        export_layout.addWidget(out_browse, 0, 2)
        self.reencode = QCheckBox("Frame-accurate re-encode")
        self.reencode.toggled.connect(self._update_encoder_state)
        export_layout.addWidget(self.reencode, 1, 0, 1, 2)
        self.encoder = QComboBox()
        for label, value in (
            ("Auto (GPU if available)", "auto"),
            ("libx264 (CPU)", "libx264"),
            ("H.264 NVENC", "h264_nvenc"),
            ("HEVC NVENC", "hevc_nvenc"),
            ("libx265 (CPU)", "libx265"),
        ):
            self.encoder.addItem(label, value)
        export_layout.addWidget(self.encoder, 1, 2)
        export_layout.addWidget(QLabel("CRF"), 2, 0)
        self.crf = QSpinBox()
        self.crf.setRange(0, 51)
        self.crf.setValue(20)
        export_layout.addWidget(self.crf, 2, 1)
        self.export_btn = QPushButton("Export clips")
        self.export_btn.setObjectName("Primary")
        self.export_btn.clicked.connect(self.export)
        self.export_btn.setEnabled(False)
        export_layout.addWidget(self.export_btn, 2, 2)
        right.addWidget(export_group)

        export_footer = QHBoxLayout()
        self.export_status = QLabel("")
        self.export_status.setObjectName("Status")
        self.export_status.setWordWrap(True)
        export_footer.addWidget(self.export_status, 1)
        self.open_folder = QPushButton("Open output folder")
        self.open_folder.setEnabled(False)
        self.open_folder.clicked.connect(self.open_output)
        export_footer.addWidget(self.open_folder)
        right.addLayout(export_footer)

        splitter.addWidget(right_panel)
        splitter.setSizes([390, 870])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self._update_encoder_state()

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Section")
        return label

    # ------------------------------------------------------------- settings
    def _restore_settings(self) -> None:
        self.sensitivity.setValue(int(self.qsettings.value("sensitivity", 50)))
        self.pre.setValue(int(self.qsettings.value("pre", 8)))
        self.post.setValue(int(self.qsettings.value("post", 5)))
        self.recursive.setChecked(self.qsettings.value("recursive", "false") in (True, "true"))
        self.gpu.setChecked(self.qsettings.value("gpu", "false") in (True, "true"))
        self.low_power.setChecked(self.qsettings.value("low_power", "false") in (True, "true"))
        self.low_power.toggled.connect(self._low_power_changed)
        self.gpu.setEnabled(self.nvenc)
        if not self.nvenc:
            self.gpu.setChecked(False)
        self.input_edit.setText(str(self.qsettings.value("input", "")))
        self.output_edit.setText(str(self.qsettings.value("output", "")))
        geometry = self.qsettings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        if self.low_power.isChecked():
            self.threads.setCurrentIndex(1)
            self.threads.setEnabled(False)
        self._update_status()

    def _save_settings(self) -> None:
        self.qsettings.setValue("sensitivity", self.sensitivity.value())
        self.qsettings.setValue("pre", self.pre.value())
        self.qsettings.setValue("post", self.post.value())
        self.qsettings.setValue("recursive", self.recursive.isChecked())
        self.qsettings.setValue("gpu", self.gpu.isChecked())
        self.qsettings.setValue("low_power", self.low_power.isChecked())
        self.qsettings.setValue("input", self.input_edit.text())
        self.qsettings.setValue("output", self.output_edit.text())
        self.qsettings.setValue("geometry", self.saveGeometry())

    def _update_status(self) -> None:
        if self.ffmpeg_ok:
            self.ffmpeg_label.setText("FFmpeg ready")
            self.ffmpeg_label.setToolTip(self.ffmpeg_text)
        else:
            self.ffmpeg_label.setText("FFmpeg missing")
            self.ffmpeg_label.setStyleSheet("color: #fb7185;")
            self.ffmpeg_label.setToolTip("Install FFmpeg or use the portable build.")
        self.gpu_label.setText("GPU: NVENC" if self.nvenc else "GPU: CPU mode")
        if not self.nvenc:
            self.gpu_label.setStyleSheet("color: #94a3b8;")

    def _sensitivity_changed(self, value: int) -> None:
        self.sensitivity_value.setText(f"{value}%")

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced.setVisible(checked)
        self.advanced_toggle.setText("Advanced tuning  ▴" if checked else "Advanced tuning  ▾")

    def _low_power_changed(self, checked: bool) -> None:
        self.threads.setEnabled(not checked)
        if checked:
            self.threads.setCurrentIndex(1)
            self.sample_fps.setCurrentIndex(0)
            self.proxy_width.setCurrentIndex(0)

    def _update_encoder_state(self) -> None:
        enabled = self.reencode.isChecked()
        self.encoder.setEnabled(enabled)
        self.crf.setEnabled(enabled)

    def _choose_start(self) -> str:
        current = self.input_edit.text().strip()
        if current and Path(current).exists():
            return current
        return str(Path.home())

    # --------------------------------------------------------------- input
    def choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose gameplay folder", self._choose_start())
        if path:
            self.set_input(path, scan=True)

    def set_input(self, path: str, scan: bool = True) -> None:
        cleaned = str(path).strip().strip('"')
        if not cleaned:
            return
        target = Path(cleaned).expanduser()
        self.input_edit.setText(str(target))
        if not self.output_edit.text().strip() or self.output_edit.text().strip() == "trimmed":
            base = target.parent if target.is_file() else target
            self.output_edit.setText(str(base / "trimmed"))
        self.summary = None
        self.tree.clear()
        self.preview.setText("Select a clip to preview its peak frame")
        self.export_btn.setEnabled(False)
        self.open_folder.setEnabled(False)
        if scan:
            self.scan()

    def scan(self) -> None:
        target = self.input_edit.text().strip()
        if not target:
            QMessageBox.information(self, "Choose footage", "Pick a folder or drag one onto the drop zone.")
            return
        try:
            files = scan_inputs(target, recursive=self.recursive.isChecked())
        except (ClipperError, OSError) as exc:
            QMessageBox.warning(self, "Scan failed", str(exc))
            return
        self.files = files
        self.file_list.clear()
        for file in files[:200]:
            item = QListWidgetItem(file.name)
            item.setToolTip(str(file))
            self.file_list.addItem(item)
        self.summary_label.setText(f"{len(files)} video(s) ready" if files else "No videos found")
        if not files:
            self.status.setText("No supported videos found in that folder.")
        else:
            self.status.setText(f"Ready to analyze {len(files)} video(s).")

    def choose_output(self) -> None:
        start = self.output_edit.text().strip() or self._choose_start()
        path = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if path:
            self.output_edit.setText(path)

    # ------------------------------------------------------------- analysis
    def _build_settings(self) -> DetectionSettings:
        settings = DetectionSettings(
            sensitivity=self.sensitivity.value() / 100.0,
            pre=float(self.pre.value()),
            post=float(self.post.value()),
            max_clips=self.max_clips.value(),
            sample_fps=float(self.sample_fps.currentData()),
            proxy_width=int(self.proxy_width.currentData()),
            threads=int(self.threads.currentData() or 0),
            gpu=self.gpu.isChecked(),
            preview=True,
        )
        if self.low_power.isChecked():
            settings.apply_low_power()
        return settings

    def analyze(self) -> None:
        if not self.ffmpeg_ok:
            QMessageBox.critical(self, "FFmpeg missing", "Install FFmpeg or use the portable Windows build.")
            return
        if not self.files:
            self.scan()
        if not self.files:
            QMessageBox.information(self, "No footage", "Choose a folder with supported video files first.")
            return
        self.summary = None
        self.tree.clear()
        self.preview.setText("Select a clip to preview its peak frame")
        self.export_btn.setEnabled(False)
        self.open_folder.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText("Starting analysis…")
        self._set_running(True)

        settings = self._build_settings()
        self.worker = AnalyzeWorker(
            self.input_edit.text().strip(),
            settings,
            self.recursive.isChecked(),
            self.preview_dir,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_analyzed)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(max(0.0, min(1.0, fraction)) * 100))
        self.status.setText(message)

    def _on_analyzed(self, summary: AnalysisSummary) -> None:
        self.summary = summary
        self._set_running(False)
        self.progress.setValue(100)
        self.status.setText(f"Found {summary.total_clips} clip(s) in {len(summary.files)} file(s).")
        self._populate(summary)
        self.export_btn.setEnabled(summary.total_clips > 0)
        if summary.total_clips > 0:
            self.open_folder.setEnabled(True)
        if self._screenshot_path:
            QTimer.singleShot(1200, self._capture_screenshot)

    def _on_failed(self, message: str) -> None:
        self._set_running(False)
        self.progress.setValue(0)
        if message == "Cancelled":
            self.status.setText("Cancelled.")
        else:
            self.status.setText("Analysis failed.")
            if self._screenshot_path:
                QTimer.singleShot(300, self._capture_screenshot)
            else:
                QMessageBox.critical(self, "Analysis failed", message)

    def _capture_screenshot(self) -> None:
        if self._screenshot_path:
            self._screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.grab().save(str(self._screenshot_path))
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _populate(self, summary: AnalysisSummary) -> None:
        self.tree.clear()
        for analysis in summary.files:
            top = QTreeWidgetItem(
                [
                    analysis.name,
                    "",
                    "",
                    "",
                    f"{len(analysis.clips)} clips" if not analysis.error else "error",
                    analysis.error or "",
                ]
            )
            top.setToolTip(0, analysis.path)
            self.tree.addTopLevelItem(top)
            if analysis.error:
                top.setForeground(5, Qt.red)
                continue
            for index, clip in enumerate(analysis.clips, start=1):
                child = QTreeWidgetItem(
                    [
                        f"{index:02d}",
                        clip.start_label,
                        clip.end_label,
                        clip.duration_label,
                        str(clip.score_pct),
                        clip.reason,
                    ]
                )
                child.setTextAlignment(4, Qt.AlignCenter)
                if index - 1 < len(analysis.previews):
                    preview = analysis.previews[index - 1]
                    if Path(preview).is_file():
                        child.setIcon(0, QIcon(preview))
                        child.setData(0, Qt.UserRole, preview)
                child.setToolTip(0, f"{analysis.name} · peak {clip.peak_label}")
                top.addChild(child)
        self.tree.expandAll()
        self.summary_label.setText(f"{summary.total_clips} clips · {len(summary.files)} files")
        for index in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(index)
            if top.childCount():
                self.tree.setCurrentItem(top.child(0))
                break

    def _show_preview(self, current: QTreeWidgetItem | None, previous=None) -> None:
        if current is None:
            return
        path = current.data(0, Qt.UserRole)
        if not path or not Path(path).is_file():
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            return
        self.preview.setPixmap(
            pix.scaled(self.preview.width() - 16, self.preview.height() - 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.preview.setText("")

    # ---------------------------------------------------------------- export
    def export(self) -> None:
        if not self.summary or self.summary.total_clips == 0:
            return
        output = self.output_edit.text().strip()
        if not output:
            self.choose_output()
            output = self.output_edit.text().strip()
        if not output:
            QMessageBox.information(self, "Output folder", "Choose an output folder first.")
            return
        settings = self._build_settings()
        self._set_running(True)
        self.progress.setValue(0)
        self.export_status.setText("Starting export…")
        self.export_worker = ExportWorker(
            self.summary,
            output,
            self.reencode.isChecked(),
            str(self.encoder.currentData()),
            self.crf.value(),
            settings.threads,
        )
        self.export_worker.progress.connect(self._on_progress)
        self.export_worker.done.connect(self._on_exported)
        self.export_worker.failed.connect(self._on_export_failed)
        self.export_worker.start()

    def _on_exported(self, result) -> None:
        self._set_running(False)
        self.progress.setValue(100)
        self.last_output_dir = str(Path(self.output_edit.text().strip()).resolve())
        if result.errors:
            self.export_status.setText(f"{len(result.outputs)} exported, {len(result.errors)} failed.")
            QMessageBox.warning(self, "Export finished with errors", "\n".join(result.errors[:8]))
        else:
            self.export_status.setText(f"Exported {len(result.outputs)} clip(s).")
        self.open_folder.setEnabled(True)

    def _on_export_failed(self, message: str) -> None:
        self._set_running(False)
        if message == "Cancelled":
            self.export_status.setText("Export cancelled.")
        else:
            self.export_status.setText("Export failed.")
            QMessageBox.critical(self, "Export failed", message)

    def open_output(self) -> None:
        target = self.last_output_dir or self.output_edit.text().strip()
        if target and Path(target).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(target).resolve())))

    def cancel_current(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()
        self.status.setText("Cancelling…")

    def _set_running(self, running: bool) -> None:
        self.analyze_btn.setEnabled(not running)
        self.export_btn.setEnabled(not running and bool(self.summary and self.summary.total_clips))
        self.scan_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.input_edit.setEnabled(not running)
        self.output_edit.setEnabled(not running)

    def closeEvent(self, event) -> None:  # noqa: N802
        running = (self.worker and self.worker.isRunning()) or (
            self.export_worker and self.export_worker.isRunning()
        )
        if running:
            answer = QMessageBox.question(
                self,
                "Quit Clipper?",
                "A job is still running. Cancel it and quit?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.cancel_current()
            if self.worker:
                self.worker.wait(5000)
            if self.export_worker:
                self.export_worker.wait(5000)
        self._save_settings()
        event.accept()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipper-desktop", description="Native Clipper desktop app")
    parser.add_argument("--input", default=None, help="folder or video to preload")
    parser.add_argument("--smoke-test", action="store_true", help="create the window and exit (CI)")
    parser.add_argument("--screenshot", default=None, help="save a window screenshot and exit")
    parser.add_argument("--demo-shot", default=None, help="analyze --input, save a window screenshot, exit")
    args, qt_args = parser.parse_known_args(argv)

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("Clipper")
    app.setOrganizationName("hatermedia")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow(initial_input=args.input)
    window.show()

    if args.demo_shot:
        if not args.input:
            parser.error("--demo-shot requires --input")
        window._screenshot_path = Path(args.demo_shot)
        window.set_input(args.input, scan=True)
        QTimer.singleShot(250, window.analyze)
    elif args.smoke_test:
        QTimer.singleShot(250, app.quit)
    elif args.screenshot:
        def capture() -> None:
            window.grab().save(args.screenshot)
            app.quit()

        QTimer.singleShot(900, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
