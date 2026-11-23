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
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
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
from .detect.ai import DEFAULT_MODEL, ollama_status
from .ffmpeg import FFmpegError, ffmpeg_version, nvenc_available
from .models import AnalysisSummary
from .pipeline import analyze_target, export_analysis, scan_inputs
from .update import (
    ReleaseInfo,
    UpdateError,
    check_with_cache,
    download_installer,
    is_installed_build,
    launch_installer,
    open_release_page,
)

ASSET_DIR = Path(__file__).resolve().parent / "assets"
VIDEO_ICON = ASSET_DIR / "icon.png"


STYLESHEET = """
QWidget {
    background: #0c0c0e;
    color: #f5f5f7;
    font-family: "Inter";
    font-size: 13px;
}
QMainWindow { background: #0c0c0e; }
QLabel { background: transparent; }
QCheckBox { background: transparent; }
QFrame#Panel {
    background: #121214;
    border: 1px solid #2c2c2e;
    border-radius: 8px;
}
QFrame#DropZone {
    background: #101012;
    border: 1px dashed #38383a;
    border-radius: 6px;
}
QFrame#DropZone:hover { border-color: #4f8bff; }
QLabel#Brand {
    font-family: "IBM Plex Mono";
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 1px;
    color: #ffffff;
}
QLabel#BrandSub {
    font-family: "IBM Plex Mono";
    color: #68686f;
    font-size: 9px;
    letter-spacing: 0.5px;
}
QLabel#Section {
    font-family: "IBM Plex Mono";
    font-size: 10px;
    font-weight: 600;
    color: #a1a1a6;
    letter-spacing: 1px;
}
QLabel#Muted { color: #a1a1a6; font-size: 11px; }
QLabel#Status {
    font-family: "IBM Plex Mono";
    color: #a1a1a6;
    font-size: 10px;
}
QLabel#Summary { color: #a1a1a6; font-size: 11px; }
QLabel#Preview {
    background: #101012;
    border: 1px solid #2c2c2e;
    border-radius: 6px;
    color: #68686f;
}
QPushButton {
    background: #161618;
    border: 1px solid #38383a;
    border-radius: 6px;
    padding: 6px 11px;
    color: #f5f5f7;
    font-weight: 500;
}
QPushButton:hover { background: #1c1c1f; border-color: #4f8bff; }
QPushButton:pressed { background: #101012; }
QPushButton:disabled { color: #68686f; background: #121214; border-color: #2c2c2e; }
QPushButton#Primary {
    background: #f5f5f7;
    color: #0c0c0e;
    font-weight: 600;
    border: none;
    padding: 8px 14px;
}
QPushButton#Primary:hover { background: #ffffff; }
QPushButton#Primary:pressed { background: #d2d2d7; }
QPushButton#Primary:disabled { background: #1c1c1f; color: #68686f; }
QPushButton#Accent {
    background: #3b5cf6;
    color: #ffffff;
    border: none;
    font-weight: 600;
    padding: 6px 12px;
}
QPushButton#Accent:hover { background: #4f8bff; }
QPushButton#Accent:pressed { background: #2f49c9; }
QPushButton#Accent:disabled { background: #1c1c1f; color: #68686f; }
QPushButton#Mono {
    font-family: "IBM Plex Mono";
    font-size: 10px;
    padding: 5px 9px;
}
QPushButton#IconButton {
    background: transparent;
    border: none;
    color: #a1a1a6;
    font-size: 16px;
    padding: 0;
}
QPushButton#IconButton:hover { background: #1c1c1f; color: #ffffff; }
QCheckBox { color: #c7c7cc; spacing: 7px; }
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #48484c;
    border-radius: 3px;
    background: #101012;
}
QCheckBox::indicator:hover { border-color: #4f8bff; }
QCheckBox::indicator:checked { background: #4f8bff; border-color: #4f8bff; }
QFrame#UpdateBar {
    background: #101012;
    border: 1px solid #2c2c2e;
    border-left: 2px solid #4f8bff;
    border-radius: 6px;
}
QFrame#UpdateBar QLabel { color: #c7c7cc; font-size: 12px; }
QFrame#UpdateBar QPushButton { padding: 5px 10px; }
QLineEdit, QComboBox, QSpinBox {
    background: #101012;
    border: 1px solid #38383a;
    border-radius: 6px;
    padding: 6px 8px;
    color: #f5f5f7;
    selection-background-color: #3b5cf6;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #4f8bff; }
QComboBox QAbstractItemView {
    background: #1c1c1f;
    border: 1px solid #38383a;
    selection-background-color: #2c2c2e;
    selection-color: #ffffff;
    outline: 0;
}
QGroupBox {
    border: 1px solid #2c2c2e;
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px 10px 8px 10px;
    color: #a1a1a6;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    font-family: "IBM Plex Mono";
    font-size: 10px;
    color: #a1a1a6;
    letter-spacing: 1px;
}
QSlider::groove:horizontal { height: 3px; background: #2c2c2e; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 12px; margin: -5px 0; border-radius: 6px;
    background: #f5f5f7;
}
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider::sub-page:horizontal { background: #4f8bff; border-radius: 2px; }
QProgressBar {
    background: #161618;
    border: none;
    border-radius: 2px;
    text-align: center;
    color: #a1a1a6;
    height: 10px;
    font-size: 9px;
}
QProgressBar::chunk { background: #4f8bff; border-radius: 2px; }
QTreeWidget {
    background: #101012;
    border: 1px solid #2c2c2e;
    border-radius: 6px;
    alternate-background-color: #121214;
    outline: 0;
}
QTreeWidget::item { padding: 5px 4px; border: none; }
QTreeWidget::item:selected { background: #1c1c1f; color: #ffffff; }
QHeaderView::section {
    background: #121214;
    color: #a1a1a6;
    border: 0;
    border-bottom: 1px solid #2c2c2e;
    padding: 6px 8px;
    font-family: "IBM Plex Mono";
    font-size: 10px;
    letter-spacing: 0.5px;
}
QListWidget {
    background: #101012;
    border: 1px solid #2c2c2e;
    border-radius: 6px;
    color: #a1a1a6;
    outline: 0;
}
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #2c2c2e;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #38383a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #2c2c2e;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle { background: #0c0c0e; }
QSplitter::handle:hover { background: #1c1c1f; }
QToolTip {
    background: #1c1c1f;
    color: #f5f5f7;
    border: 1px solid #38383a;
    padding: 6px;
    font-size: 11px;
}
QDialog { background: transparent; }
QFrame#DialogPanel {
    background: #161618;
    border: 1px solid #38383a;
    border-radius: 10px;
}
QLabel#DialogTitle {
    font-family: "IBM Plex Mono";
    font-size: 10px;
    font-weight: 600;
    color: #a1a1a6;
    letter-spacing: 1px;
}
QLabel#DialogMessage {
    font-family: "Inter";
    font-size: 14px;
    color: #f5f5f7;
}
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


class UpdateCheckWorker(QThread):
    found = Signal(object)
    failed = Signal(str)

    def __init__(self, force: bool = False) -> None:
        super().__init__()
        self.force = force

    def run(self) -> None:
        try:
            release, _cached = check_with_cache(force=self.force)
            self.found.emit(release)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDownloadWorker(QThread):
    progress = Signal(int, int)
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, release: ReleaseInfo) -> None:
        super().__init__()
        self.release = release

    def run(self) -> None:
        try:
            path = download_installer(
                self.release,
                progress=self._progress,
            )
            self.ready.emit(str(path))
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))

    def _progress(self, done: int, total: int) -> None:
        if self.isInterruptionRequested():
            raise UpdateError("Download cancelled.")
        self.progress.emit(done, total)


class DropZone(QFrame):
    pathDropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(68)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        title = QLabel("Drop a folder or video here")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #f5f5f7; font-weight: 500;")
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


def load_app_fonts() -> None:
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    font_dir = ASSET_DIR / "fonts"
    if not font_dir.is_dir():
        return
    for path in sorted(font_dir.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))
    _FONTS_LOADED = True


_FONTS_LOADED = False


class AppDialog(QDialog):
    """Small OpenCode-style modal used instead of the platform QMessageBox."""

    _ACCENTS = {
        "info": "#4f8bff",
        "warning": "#f4b434",
        "critical": "#ed5a5a",
    }

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        confirm: str | None = None,
        cancel: str = "Close",
        kind: str = "info",
        detail: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setWindowTitle(title)
        self._drag_pos = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        panel = QFrame()
        panel.setObjectName("DialogPanel")
        panel.setMinimumWidth(440)
        panel.setMaximumWidth(500)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(0, 0, 0, 190))
        shadow.setOffset(0, 10)
        panel.setGraphicsEffect(shadow)
        outer.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(7)
        dot = QLabel("●")
        dot.setStyleSheet(
            f"color: {self._ACCENTS.get(kind, self._ACCENTS['info'])}; font-size: 9px;"
        )
        heading = QLabel(title.upper())
        heading.setObjectName("DialogTitle")
        close = QPushButton("×")
        close.setObjectName("IconButton")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.reject)
        top.addWidget(dot)
        top.addWidget(heading)
        top.addStretch(1)
        top.addWidget(close)
        layout.addLayout(top)

        body = QLabel(message)
        body.setObjectName("DialogMessage")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(body)

        if detail:
            extra = QLabel(detail)
            extra.setObjectName("Muted")
            extra.setWordWrap(True)
            extra.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(extra)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        cancel_btn = QPushButton(cancel)
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        if confirm:
            confirm_btn = QPushButton(confirm)
            confirm_btn.setObjectName("Accent")
            confirm_btn.setDefault(True)
            confirm_btn.clicked.connect(self.accept)
            actions.addWidget(confirm_btn)
        layout.addLayout(actions)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            center = parent.window().frameGeometry().center()
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


def show_message(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    kind: str = "info",
    detail: str = "",
) -> None:
    AppDialog(parent, title, message, kind=kind, detail=detail).exec()


def ask_confirm(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    confirm: str = "Continue",
    cancel: str = "Not now",
    kind: str = "info",
) -> bool:
    dialog = AppDialog(
        parent,
        title,
        message,
        confirm=confirm,
        cancel=cancel,
        kind=kind,
    )
    return dialog.exec() == QDialog.Accepted


class MainWindow(QMainWindow):
    def __init__(self, initial_input: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"Clipper {__version__}")
        self.resize(1280, 840)
        self.setMinimumSize(1040, 720)
        if VIDEO_ICON.is_file():
            self.setWindowIcon(QIcon(str(VIDEO_ICON)))

        self.qsettings = QSettings("hatermedia", "Clipper")
        load_app_fonts()
        self.summary: AnalysisSummary | None = None
        self.worker: AnalyzeWorker | None = None
        self.export_worker: ExportWorker | None = None
        self.preview_dir = Path(tempfile.mkdtemp(prefix="clipper-desktop-"))
        self.files: list[Path] = []
        self.last_output_dir: str | None = None
        self.nvenc = False
        self._screenshot_path: Path | None = None
        ai_state = ollama_status(timeout=1.5)
        installed = {str(name).lower(): str(name) for name in ai_state.get("models", [])}
        vision = [
            name for name in installed.values()
            if any(token in name.lower() for token in ("vl", "llava", "minicpm", "moondream", "gemma3"))
            and not name.lower().startswith("qwen3")
        ]
        self.ai_models = vision
        self.ai_available = bool(vision)
        self.ai_default = DEFAULT_MODEL if DEFAULT_MODEL.lower() in installed else (vision[0] if vision else DEFAULT_MODEL)
        self.update_release: ReleaseInfo | None = None
        self.update_installer: Path | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_worker: UpdateDownloadWorker | None = None
        self._manual_update_check = False

        try:
            bins = find_ffmpeg()
            self.ffmpeg_ok = True
            self.ffmpeg_text = ffmpeg_version(bins)
            self.nvenc = nvenc_available(bins)
        except Exception:
            self.ffmpeg_ok = False
            self.ffmpeg_text = "FFmpeg not found"
            self.nvenc = False

        self._build_ui()
        self._restore_settings()
        if initial_input:
            self.set_input(initial_input, scan=False)
        self._update_status()
        QTimer.singleShot(2500, lambda: self.check_updates(manual=False))

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
        brand_line = QHBoxLayout()
        brand_line.setSpacing(8)
        brand = QLabel("CLIPPER")
        brand.setObjectName("Brand")
        version_label = QLabel(f"v{__version__}")
        version_label.setObjectName("BrandSub")
        brand_line.addWidget(brand)
        brand_line.addWidget(version_label)
        brand_line.addStretch(1)
        sub = QLabel("local highlight engine")
        sub.setObjectName("BrandSub")
        brand_box.addLayout(brand_line)
        brand_box.addWidget(sub)
        header.addLayout(brand_box)
        header.addStretch(1)
        self.gpu_label = QLabel("nvenc / checking")
        self.gpu_label.setObjectName("Status")
        self.ffmpeg_label = QLabel("ffmpeg / checking")
        self.ffmpeg_label.setObjectName("Status")
        header.addWidget(self.ffmpeg_label)
        header.addWidget(self.gpu_label)
        updates = QPushButton("Updates")
        updates.setObjectName("Mono")
        updates.setToolTip("Check GitHub for a newer Clipper release")
        updates.clicked.connect(lambda: self.check_updates(manual=True))
        header.addWidget(updates)
        github = QPushButton("GitHub ↗")
        github.setObjectName("Mono")
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/hatermedia/clipper")))
        header.addWidget(github)
        outer.addLayout(header)

        self.update_bar = QFrame()
        self.update_bar.setObjectName("UpdateBar")
        update_row = QHBoxLayout(self.update_bar)
        update_row.setContentsMargins(12, 7, 8, 7)
        update_row.setSpacing(8)
        self.update_label = QLabel("")
        update_row.addWidget(self.update_label, 1)
        self.update_action = QPushButton("Download update")
        self.update_action.setObjectName("Accent")
        self.update_action.clicked.connect(self._update_action_clicked)
        update_row.addWidget(self.update_action)
        update_later = QPushButton("Later")
        update_later.clicked.connect(self.update_bar.hide)
        update_row.addWidget(update_later)
        self.update_bar.hide()
        outer.addWidget(self.update_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        # ---------------- left controls ----------------
        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel.setMinimumWidth(370)
        left_panel.setMaximumWidth(410)
        left_shell = QVBoxLayout(left_panel)
        left_shell.setContentsMargins(0, 0, 0, 0)
        left_shell.setSpacing(0)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        controls = QWidget()
        left = QVBoxLayout(controls)
        left.setContentsMargins(16, 14, 16, 8)
        left.setSpacing(8)

        left.addWidget(self._section("01 / FOOTAGE"))
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
        self.file_list.setMaximumHeight(86)
        self.file_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.file_list.setVisible(False)
        left.addWidget(self.file_list)

        left.addSpacing(6)
        left.addWidget(self._section("02 / DETECTION"))
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

        ai_row = QHBoxLayout()
        self.ai = QCheckBox("AI review (local)")
        self.ai.setToolTip(
            "Reviews candidates with a local Ollama vision model. "
            "The game may be inside a Discord stream window."
        )
        self.ai_state = QLabel("")
        self.ai_state.setObjectName("Status")
        ai_row.addWidget(self.ai)
        ai_row.addWidget(self.ai_state)
        ai_row.addStretch(1)
        left.addLayout(ai_row)

        ai_controls = QGridLayout()
        ai_controls.setHorizontalSpacing(8)
        ai_controls.setVerticalSpacing(4)
        ai_controls.addWidget(QLabel("AI model"), 0, 0)
        self.ai_model = QComboBox()
        for model in (self.ai_models or [f"{DEFAULT_MODEL} (not installed)"]):
            self.ai_model.addItem(model)
        preferred = self.ai_model.findText(self.ai_default)
        if preferred >= 0:
            self.ai_model.setCurrentIndex(preferred)
        self.ai_model.setEnabled(self.ai_available)
        ai_controls.addWidget(self.ai_model, 0, 1)
        ai_controls.addWidget(QLabel("Game"), 1, 0)
        self.ai_game = QComboBox()
        for label, value in (
            ("Valorant", "Valorant"),
            ("Apex Legends", "Apex Legends"),
            ("CS2", "Counter-Strike 2"),
            ("Generic", "generic"),
        ):
            self.ai_game.addItem(label, value)
        self.ai_game.setCurrentIndex(3)
        ai_controls.addWidget(self.ai_game, 1, 1)
        left.addLayout(ai_controls)
        self.ai.setEnabled(self.ai_available)

        gpu_row = QHBoxLayout()
        self.gpu = QCheckBox("Use NVIDIA GPU (NVENC)")
        self.gpu.setToolTip(
            "Hardware decode + NVENC for the analysis proxy and re-encode. "
            "OpenCV motion scoring and audio analysis stay on the CPU."
        )
        self.gpu_state = QLabel("")
        self.gpu_state.setObjectName("Status")
        self.gpu_state.setToolTip("OpenCV motion scoring and audio RMS stay on the CPU.")
        gpu_row.addWidget(self.gpu)
        gpu_row.addWidget(self.gpu_state)
        gpu_row.addStretch(1)
        left.addLayout(gpu_row)
        self.gpu.setEnabled(self.nvenc)

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
        self.low_power = QCheckBox("Low-power mode")
        self.low_power.setToolTip("Caps threads at 2, uses a 256px/2fps proxy, and lowers process priority.")
        advanced_layout.addWidget(self.low_power, 4, 0, 1, 2)
        advanced_layout.addWidget(
            QLabel("GPU helps decode/encode; motion scoring remains CPU-bound."),
            5, 0, 1, 2,
        )
        self.advanced.setVisible(False)
        left.addWidget(self.advanced)
        privacy = QLabel("local-only / no uploads")
        privacy.setObjectName("BrandSub")
        left.addWidget(privacy)
        left.addStretch(1)

        left_scroll.setWidget(controls)
        left_shell.addWidget(left_scroll, 1)

        footer = QFrame()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(16, 8, 16, 16)
        footer_layout.setSpacing(7)
        self.analyze_btn = QPushButton("Detect highlights")
        self.analyze_btn.setObjectName("Primary")
        self.analyze_btn.clicked.connect(self.analyze)
        footer_layout.addWidget(self.analyze_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        footer_layout.addWidget(self.progress)
        self.status = QLabel("ready")
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        footer_layout.addWidget(self.status)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_current)
        footer_layout.addWidget(self.cancel_btn)
        left_shell.addWidget(footer)

        splitter.addWidget(left_panel)

        # ---------------- right results ----------------
        right_panel = QFrame()
        right_panel.setObjectName("Panel")
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(16, 16, 16, 16)
        right.setSpacing(10)

        results_header = QHBoxLayout()
        results_header.addWidget(self._section("HIGHLIGHTS"))
        results_header.addStretch(1)
        self.summary_label = QLabel("Nothing analyzed yet")
        self.summary_label.setObjectName("Summary")
        results_header.addWidget(self.summary_label)
        right.addLayout(results_header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["CLIP", "START", "END", "LENGTH", "SCORE", "SIGNAL"])
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

        export_group = QGroupBox("EXPORT")
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
        self.open_folder = QPushButton("Open folder")
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
        # New key so the old "off by default" setting does not stick after upgrade.
        if self.qsettings.contains("gpu_v2"):
            gpu_default = self.qsettings.value("gpu_v2", "false") in (True, "true")
        else:
            gpu_default = self.nvenc
        self.gpu.setChecked(bool(gpu_default) and self.nvenc)
        self.low_power.setChecked(self.qsettings.value("low_power", "false") in (True, "true"))
        self.low_power.toggled.connect(self._low_power_changed)
        self.gpu.toggled.connect(self._gpu_changed)
        self.gpu.setEnabled(self.nvenc)
        self._gpu_changed(self.gpu.isChecked())

        if self.ai_available:
            if self.qsettings.contains("ai_v2"):
                ai_default = self.qsettings.value("ai_v2", "false") in (True, "true")
            else:
                ai_default = True
            self.ai.setChecked(bool(ai_default))
            stored_model = str(self.qsettings.value("ai_model", ""))
            if stored_model and self.ai_model.findText(stored_model) >= 0:
                self.ai_model.setCurrentText(stored_model)
            stored_game = str(self.qsettings.value("ai_game", ""))
            if stored_game:
                game_index = self.ai_game.findData(stored_game)
                if game_index >= 0:
                    self.ai_game.setCurrentIndex(game_index)
        else:
            self.ai.setChecked(False)
        self.ai.toggled.connect(self._ai_changed)
        self.ai_model.currentTextChanged.connect(lambda _: self._ai_changed(self.ai.isChecked()))
        self._ai_changed(self.ai.isChecked())
        self.input_edit.setText(str(self.qsettings.value("input", "")))
        self.input_edit.setCursorPosition(0)
        self.output_edit.setText(str(self.qsettings.value("output", "")))
        self.output_edit.setCursorPosition(0)
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
        self.qsettings.setValue("gpu_v2", self.gpu.isChecked())
        self.qsettings.setValue("ai_v2", self.ai.isChecked())
        self.qsettings.setValue("ai_model", self.ai_model.currentText())
        self.qsettings.setValue("ai_game", str(self.ai_game.currentData()))
        self.qsettings.setValue("low_power", self.low_power.isChecked())
        self.qsettings.setValue("input", self.input_edit.text())
        self.qsettings.setValue("output", self.output_edit.text())
        self.qsettings.setValue("geometry", self.saveGeometry())

    # --------------------------------------------------------------- updates
    def check_updates(self, manual: bool = False) -> None:
        if self.update_check_worker is not None and self.update_check_worker.isRunning():
            return
        self._manual_update_check = manual
        if manual:
            self.update_label.setText("Checking GitHub for updates…")
            self.update_action.setText("Checking…")
            self.update_action.setEnabled(False)
            self.update_bar.show()
        worker = UpdateCheckWorker(force=manual)
        worker.found.connect(self._update_found)
        worker.failed.connect(self._update_check_failed)
        worker.finished.connect(worker.deleteLater)
        self.update_check_worker = worker
        worker.start()

    def _update_found(self, release: object) -> None:
        self.update_check_worker = None
        if release is None:
            self.update_bar.hide()
            if self._manual_update_check:
                show_message(
                    self,
                    "Updates",
                    f"Clipper {__version__} is up to date.",
                )
            return
        assert isinstance(release, ReleaseInfo)
        self.update_release = release
        self.update_installer = None
        if release.has_installer:
            self.update_label.setText(
                f"Clipper {release.version} is available · you have {__version__}"
            )
            self.update_action.setText("Download update")
        else:
            self.update_label.setText(
                f"Clipper {release.version} is available · no installer in this release"
            )
            self.update_action.setText("View release")
        self.update_action.setEnabled(True)
        self.update_bar.show()

    def _update_check_failed(self, message: str) -> None:
        self.update_check_worker = None
        if self._manual_update_check:
            self.update_bar.hide()
            show_message(
                self,
                "Update check failed",
                message,
                kind="warning",
                detail="You can also download the latest release from GitHub.",
            )

    def _update_action_clicked(self) -> None:
        if self.update_installer is not None:
            self._install_update()
            return
        release = self.update_release
        if release is None:
            self.check_updates(manual=True)
            return
        if not release.has_installer:
            open_release_page(release)
            return
        self._download_update(release)

    def _download_update(self, release: ReleaseInfo) -> None:
        if self.update_download_worker is not None and self.update_download_worker.isRunning():
            return
        self.update_label.setText(f"Downloading Clipper {release.version}…")
        self.update_action.setText("Downloading…")
        self.update_action.setEnabled(False)
        worker = UpdateDownloadWorker(release)
        worker.progress.connect(self._download_progress)
        worker.ready.connect(self._download_ready)
        worker.failed.connect(self._download_failed)
        worker.finished.connect(worker.deleteLater)
        self.update_download_worker = worker
        worker.start()

    def _download_progress(self, done: int, total: int) -> None:
        release = self.update_release
        label = f"Clipper {release.version}" if release else "update"
        if total > 0:
            percent = min(100, int(done * 100 / total))
            self.update_label.setText(
                f"Downloading {label}… {percent}% "
                f"({done / (1024 * 1024):.0f} of {total / (1024 * 1024):.0f} MB)"
            )
        else:
            self.update_label.setText(f"Downloading {label}… {done / (1024 * 1024):.0f} MB")

    def _download_ready(self, path: str) -> None:
        self.update_download_worker = None
        release = self.update_release
        self.update_installer = Path(path)
        version = release.version if release else ""
        self.update_label.setText(
            f"Update ready · Clipper {version} downloaded and SHA-256 verified"
        )
        self.update_action.setText("Restart & install")
        self.update_action.setEnabled(True)
        self.update_bar.show()

    def _download_failed(self, message: str) -> None:
        self.update_download_worker = None
        self.update_label.setText("Update download failed")
        self.update_action.setText("Retry")
        self.update_action.setEnabled(True)
        self.update_action.setToolTip(message)
        show_message(
            self,
            "Download failed",
            message,
            kind="warning",
            detail="You can download the release manually from GitHub.",
        )

    def _install_update(self) -> None:
        release = self.update_release
        installer = self.update_installer
        if release is None or installer is None:
            return
        if not is_installed_build():
            show_message(
                self,
                "Install update",
                "This copy is not running from the installed Windows build, so "
                "Clipper will open the release page instead of replacing it.",
            )
            open_release_page(release)
            return
        if not ask_confirm(
            self,
            "Install update",
            f"Install Clipper {release.version} now?",
            confirm="Install and restart",
            detail="Clipper will close, install silently, and reopen.",
        ):
            return
        try:
            launch_installer(installer, wait_pid=os.getpid(), relaunch=True)
        except UpdateError as exc:
            show_message(
                self,
                "Could not start installer",
                str(exc),
                kind="critical",
            )
            return
        self.update_label.setText(f"Installing Clipper {release.version}…")
        self.update_action.setEnabled(False)
        QTimer.singleShot(1200, QApplication.instance().quit)

    def _update_status(self) -> None:
        if self.ffmpeg_ok:
            self.ffmpeg_label.setText("ffmpeg / ready")
            self.ffmpeg_label.setToolTip(self.ffmpeg_text)
        else:
            self.ffmpeg_label.setText("ffmpeg / missing")
            self.ffmpeg_label.setStyleSheet("color: #ed5a5a;")
            self.ffmpeg_label.setToolTip("Install FFmpeg or use the portable build.")
        self._gpu_changed(self.gpu.isChecked())
        self._ai_changed(self.ai.isChecked())

    def _ai_changed(self, checked: bool) -> None:
        if not self.ai_available:
            self.ai_state.setText("ollama / missing")
            self.ai_state.setToolTip("Install Ollama and run: ollama pull qwen2.5vl:7b")
            self.ai.setEnabled(False)
            return
        self.ai.setEnabled(True)
        self.ai_model.setEnabled(checked)
        self.ai_game.setEnabled(checked)
        if checked:
            self.ai_state.setText(f"{self.ai_model.currentText()} / local")
            self.ai_state.setToolTip("Local vision review via Ollama; runs on the GPU when available.")
        else:
            self.ai_state.setText("off")

    def _gpu_changed(self, checked: bool) -> None:
        if not self.nvenc:
            self.gpu_label.setText("nvenc / unavailable")
            self.gpu_label.setStyleSheet("color: #68686f;")
            self.gpu_state.setText("cpu only")
            return
        if checked:
            self.gpu_label.setText("nvenc / on")
            self.gpu_label.setStyleSheet("color: #4f8bff;")
            self.gpu_state.setText("proxy + re-encode")
        else:
            self.gpu_label.setText("nvenc / off")
            self.gpu_label.setStyleSheet("color: #a1a1a6;")
            self.gpu_state.setText("cpu proxy")

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
        self.input_edit.setCursorPosition(0)
        lowered = str(target).lower()
        if "valorant" in lowered:
            self.ai_game.setCurrentIndex(0)
        elif "apex" in lowered:
            self.ai_game.setCurrentIndex(1)
        elif "counter-strike" in lowered or "cs2" in lowered:
            self.ai_game.setCurrentIndex(2)
        if not self.output_edit.text().strip() or self.output_edit.text().strip() == "trimmed":
            base = target.parent if target.is_file() else target
            self.output_edit.setText(str(base / "trimmed"))
        self.summary = None
        self.tree.clear()
        self.preview.setText("Select a clip to preview its peak frame")
        self.export_btn.setEnabled(False)
        self.open_folder.setEnabled(False)
        self.file_list.clear()
        self.file_list.setVisible(False)
        if scan:
            self.scan()

    def scan(self) -> None:
        target = self.input_edit.text().strip()
        if not target:
            show_message(self, "Choose footage", "Pick a folder or drag one onto the drop zone.")
            return
        try:
            files = scan_inputs(target, recursive=self.recursive.isChecked())
        except (ClipperError, OSError) as exc:
            show_message(self, "Scan failed", str(exc), kind="warning")
            return
        self.files = files
        self.file_list.clear()
        for file in files[:200]:
            item = QListWidgetItem(file.name)
            item.setToolTip(str(file))
            self.file_list.addItem(item)
        if files:
            self.file_list.setFixedHeight(min(86, max(38, 24 + 22 * min(len(files), 3))))
        self.file_list.setVisible(bool(files))
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
            ai=self.ai.isChecked() and self.ai_available,
            ai_model=self.ai_model.currentText().replace(" (not installed)", ""),
            ai_game=str(self.ai_game.currentData() or "generic"),
        )
        if self.low_power.isChecked():
            settings.apply_low_power()
        return settings

    def analyze(self) -> None:
        if not self.ffmpeg_ok:
            show_message(
                self,
                "FFmpeg missing",
                "Install FFmpeg or use the portable Windows build.",
                kind="critical",
            )
            return
        if not self.files:
            self.scan()
        if not self.files:
            show_message(
                self,
                "No footage",
                "Choose a folder with supported video files first.",
            )
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
                show_message(self, "Analysis failed", message, kind="critical")

    def _capture_screenshot(self) -> None:
        if self._screenshot_path:
            self._screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.grab().save(str(self._screenshot_path))
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _populate(self, summary: AnalysisSummary) -> None:
        self.tree.clear()
        mono = QFont("IBM Plex Mono")
        mono.setPixelSize(12)
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
                for column in range(5):
                    child.setFont(column, mono)
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
            show_message(self, "Output folder", "Choose an output folder first.")
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
            show_message(
                self,
                "Export finished with errors",
                "\n".join(result.errors[:8]),
                kind="warning",
            )
        else:
            self.export_status.setText(f"Exported {len(result.outputs)} clip(s).")
        self.open_folder.setEnabled(True)

    def _on_export_failed(self, message: str) -> None:
        self._set_running(False)
        if message == "Cancelled":
            self.export_status.setText("Export cancelled.")
        else:
            self.export_status.setText("Export failed.")
            show_message(self, "Export failed", message, kind="critical")

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
        self.ai.setEnabled(not running and self.ai_available)
        self.ai_model.setEnabled(not running and self.ai_available and self.ai.isChecked())
        self.ai_game.setEnabled(not running and self.ai_available and self.ai.isChecked())

    def closeEvent(self, event) -> None:  # noqa: N802
        running = (self.worker and self.worker.isRunning()) or (
            self.export_worker and self.export_worker.isRunning()
        )
        if running:
            if not ask_confirm(
                self,
                "Quit Clipper?",
                "A job is still running. Cancel it and quit?",
                confirm="Quit",
                kind="warning",
            ):
                event.ignore()
                return
            self.cancel_current()
            if self.worker:
                self.worker.wait(5000)
            if self.export_worker:
                self.export_worker.wait(5000)
        for worker in (self.update_check_worker, self.update_download_worker):
            if worker and worker.isRunning():
                worker.requestInterruption()
                if not worker.wait(3000):
                    worker.terminate()
                    worker.wait(500)
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
    load_app_fonts()
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
