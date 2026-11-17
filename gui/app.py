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

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
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

from gui import wording
from gui.workers import Backend


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
        self.resize(980, 680)
        self.session = Session()
        self.backend = backend or Backend(self)
        self.screens: dict[str, Screen] = {}

        self._step_labels = [QLabel(text) for text in wording.STEPS]
        bar = QHBoxLayout()
        for label in self._step_labels:
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bar.addWidget(label)
        self._stack = QStackedWidget()
        layout = QVBoxLayout()
        layout.addLayout(bar)
        layout.addWidget(self._stack, 1)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        lock = QAction(wording.LOCK, self)
        lock.triggered.connect(self.lock)
        self.menuBar().addMenu(wording.APP_NAME).addAction(lock)

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
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".replace-o-matic")
    folder = os.path.join(base, "Replace-o-matic") if os.environ.get("LOCALAPPDATA") else base
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "replace-o-matic.log")


def main() -> int:
    # The log records events and error types only: never document text, values or passphrases.
    logging.basicConfig(filename=log_path(), level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName(wording.APP_NAME)
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
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
