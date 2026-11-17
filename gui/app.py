"""The window shell: one window, a step bar, a stack of screens.

Run with ``python -m gui.app``. Screens are added in ``gui/screens/`` (see
GUI_PLAN.md, phases 1 to 5); this module only provides the frame they live in:

- ``Session``: what the current task knows so far (file, matter, scan, result).
- ``Screen``: base class. Override ``enter()`` (called each time it is shown)
  and the ``on_*`` handlers for background results.
- ``MainWindow.go(name)``: switch screen. ``MainWindow.backend``: background jobs.
"""

from __future__ import annotations

import sanitizer_core as sc  # noqa: F401  first project import: it sets the offline switches

import logging
import os
import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui import intro, settings, wording
from gui.workers import Backend


MARGIN = 20  # outer margin of every screen
SPACING = 12  # gap between rows on every screen

STEP_PAST = "padding: 6px 10px; border-bottom: 3px solid palette(mid);"
STEP_NOW = "padding: 6px 10px; font-weight: bold; border-bottom: 3px solid palette(highlight);"
STEP_LATER = "padding: 6px 10px; color: palette(mid); border-bottom: 3px solid transparent;"
STEP_NONE = "padding: 6px 10px; color: palette(mid); border-bottom: 3px solid transparent;"


def app_icon() -> QIcon:
    """A plain icon drawn in code: a page with a bar blacked out. No image files."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#ffffff"))
    painter.setPen(QColor("#3b5b8c"))
    painter.drawRoundedRect(10, 4, 44, 56, 5, 5)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#9aa7b8"))
    for top in (14, 40, 48):
        painter.drawRect(18, top, 28, 4)
    painter.setBrush(QColor("#1f2d44"))
    painter.drawRect(18, 26, 28, 8)
    painter.end()
    return QIcon(pixmap)


@dataclass
class Session:
    """State of the task in hand. Cleared by ``MainWindow.new_task()``."""

    document_path: str = ""
    matter_path: str = ""
    passphrase: str = ""  # memory only: never written to settings or logs
    vault: dict | None = None
    scan: object = None  # sanitizer_service.Scan
    result: object = None  # sanitizer_service.Result


class Screen(QWidget):
    """Base class for a screen. ``step`` is its index in the step bar, or None."""

    name = ""
    step: int | None = None

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window_ = window

    @property
    def session(self) -> Session:
        return self.window_.session

    @property
    def backend(self) -> Backend:
        return self.window_.backend

    def enter(self) -> None:
        """Called every time the screen is shown."""

    def forget(self) -> None:
        """Called on Lock and on close: drop passphrases and document text held in widgets."""

    # Background results are routed to the screen that is showing.
    def on_finished(self, job: str, result) -> None: ...
    def on_failed(self, job: str, message: str) -> None:
        QMessageBox.warning(self, wording.APP_NAME, message)

    def on_cancelled(self, job: str) -> None: ...
    def on_progress(self, done: int, total: int) -> None: ...


class MainWindow(QMainWindow):
    def __init__(self, backend: Backend | None = None):
        super().__init__()
        # The title never includes a file or client name: it shows in the taskbar.
        self.setWindowTitle(wording.APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(980, 680)
        self.session = Session()
        self.backend = backend or Backend(self)
        self.screens: dict[str, Screen] = {}

        self._step_labels = [QLabel(text) for text in wording.STEPS]
        bar = QHBoxLayout()
        bar.setSpacing(4)
        for index, label in enumerate(self._step_labels):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(STEP_NONE)
            label.setAccessibleName(
                wording.A11Y_STEP.format(n=index + 1, total=len(wording.STEPS), name=wording.STEPS[index])
            )
            bar.addWidget(label, 1)
        self._stack = QStackedWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(MARGIN, 10, MARGIN, MARGIN)
        layout.setSpacing(SPACING)
        layout.addLayout(bar)
        layout.addWidget(self._stack, 1)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        lock = QAction(wording.LOCK, self)
        lock.setShortcut(QKeySequence(wording.LOCK_SHORTCUT))
        lock.triggered.connect(self.lock)
        self.lock_action = lock
        self.menuBar().addMenu(wording.APP_NAME).addAction(lock)
        help_action = QAction(wording.HELP_INTRO, self)
        help_action.triggered.connect(lambda: intro.open_intro(self))
        self.help_action = help_action
        self.menuBar().addMenu(wording.HELP_MENU).addAction(help_action)

        self.backend.finished.connect(lambda job, result: self._route("on_finished", job, result))
        self.backend.failed.connect(lambda job, message: self._route("on_failed", job, message))
        self.backend.cancelled.connect(lambda job: self._route("on_cancelled", job))
        self.backend.progress.connect(lambda done, total: self._route("on_progress", done, total))

    # ---- screens

    def add_screen(self, screen: Screen) -> None:
        self.screens[screen.name] = screen
        self._stack.addWidget(screen)

    def current(self) -> Screen | None:
        widget = self._stack.currentWidget()
        return widget if isinstance(widget, Screen) else None

    def go(self, name: str) -> None:
        screen = self.screens[name]
        self._stack.setCurrentWidget(screen)
        for index, label in enumerate(self._step_labels):
            font = label.font()
            font.setBold(index == screen.step)
            label.setFont(font)
            label.setEnabled(screen.step is not None and index <= screen.step)
            if screen.step is None:
                label.setStyleSheet(STEP_NONE)
            else:
                label.setStyleSheet(STEP_NOW if index == screen.step else STEP_PAST if index < screen.step else STEP_LATER)
        screen.enter()

    def _route(self, handler: str, *args) -> None:
        screen = self.current()
        if screen is not None:
            getattr(screen, handler)(*args)

    # ---- task state

    def new_task(self) -> None:
        """Forget the document and scan, keep the open matter."""
        keep = self.session
        self.session = Session(matter_path=keep.matter_path, passphrase=keep.passphrase, vault=keep.vault)

    def lock(self) -> None:
        """Forget the passphrase and everything read with it."""
        self.backend.cancel()
        self.session = Session()
        for screen in self.screens.values():
            screen.forget()
        if "start" in self.screens:
            self.go("start")

    # ---- closing

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self.backend.busy:
            answer = QMessageBox.question(self, wording.CLOSE_WHILE_BUSY_TITLE, wording.CLOSE_WHILE_BUSY)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.session = Session()
        self.backend.shutdown()
        event.accept()


def log_path() -> str:
    return os.path.join(settings.app_folder(), "replace-o-matic.log")


def self_test() -> int:
    """Load the model and scan one sentence, with no window. Used to check a
    packaged build: exit code 0 means the bundle is complete and working."""
    import sanitizer_service as service

    proposal = sc.scan_text("John Smith of Acme Corporation lives at 12 Oak Street, Akron, OH 44301.")
    values = {entry["value"] for entry in proposal["proposed"].values()}
    ok = "John Smith" in values and any("Acme" in v for v in values) and any("Akron" in v for v in values)
    loaded = sorted(m for m in ("torch", "transformers", "gliner") if m in sys.modules)
    print(f"self-test: {'ok' if ok and not loaded else 'FAILED'}; found {len(values)} items; "
          f"pdf support: {service.pdf_io.available()}; unwanted modules: {loaded}")
    return 0 if ok and not loaded else 1


def _attach_console() -> None:
    """The Windows build is a windowed program (console=False), so it starts
    with no stdout. Borrow the console it was started from, if any, so that
    ``--self-test`` prints there. Redirected output (``> file``) already works."""
    if os.name != "nt" or sys.stdout is not None:
        return
    import ctypes

    if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        sys.stderr = sys.stdout


def main() -> int:
    if "--self-test" in sys.argv:
        _attach_console()
        return self_test()
    # The log records events and error types only: never document text, values or passphrases.
    logging.basicConfig(filename=log_path(), level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName(wording.APP_NAME)
    app.setWindowIcon(app_icon())
    window = MainWindow()
    try:
        from gui.screens import install  # added in phase 1

        install(window)
        window.go("start")
    except ImportError:
        placeholder = QLabel("Screens are not built yet. See GUI_PLAN.md, phase 1.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        window._stack.addWidget(placeholder)
    window.backend.preload_model()
    window.show()
    QTimer.singleShot(0, lambda: intro.show_if_first_run(window))  # first run only
    return app.exec()


if __name__ == "__main__":
    # Run as a program (python -m gui.app, or the packaged app), this file is the
    # module __main__, while the screens import gui.app: two copies, two Screen
    # classes, and MainWindow.current() would match no screen, so background
    # results would never reach one. Run the gui.app copy instead.
    from gui.app import main as _main

    sys.exit(_main())
