"""Scanning: progress and Cancel. The scan itself runs on the background thread."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from gui import wording
from gui.app import Screen
from gui.screens.common import heading


class ScanningScreen(Screen):
    name, step = "scanning", 2

    def __init__(self, window):
        super().__init__(window)
        self.status = QLabel(wording.LOADING_MODEL)
        self.bar = QProgressBar()
        self.cancel_button = QPushButton(wording.CANCEL)
        self.cancel_button.clicked.connect(self.cancel)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.addWidget(heading(wording.SCANNING))
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        layout.addStretch(1)
        layout.addLayout(row)

    def enter(self) -> None:
        self.status.setText(wording.LOADING_MODEL)
        self.bar.setRange(0, 0)  # busy until the first part is reported
        self.cancel_button.setEnabled(True)
        self.session.scan = None
        self.backend.scan(self.session.document_path, self.session.vault)

    def cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.status.setText(wording.CANCELLING)
        self.backend.cancel()

    def _back(self, message: str) -> None:
        self.window_.screens["choose"].pending_message = message
        self.window_.go("choose")

    def on_progress(self, done: int, total: int) -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        if self.cancel_button.isEnabled():
            self.status.setText(wording.SCAN_PROGRESS.format(done=done, total=total))

    def on_finished(self, job: str, result) -> None:
        if job == "scan":
            self.session.scan = result
            self.window_.go("review")

    def on_cancelled(self, job: str) -> None:
        if job == "scan":
            self._back(wording.SCAN_CANCELLED)

    def on_failed(self, job: str, message: str) -> None:
        if job == "scan":
            self._back(message)
