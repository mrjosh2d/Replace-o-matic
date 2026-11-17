"""Scanning: progress bar, Cancel, hand the result to the session."""

from __future__ import annotations

import sanitizer_core as sc
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout

from gui import wording
from gui.app import Screen


class ScanningScreen(Screen):
    name, step = "scanning", 2

    def __init__(self, window):
        super().__init__(window)
        self.heading = QLabel(wording.SCANNING)
        self.heading.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.note = QLabel("")
        self.count = QLabel("")
        self.bar = QProgressBar()
        self.cancel_button = QPushButton(wording.CANCEL)
        self.again = QPushButton(wording.CHOOSE_ANOTHER)
        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.note)
        layout.addWidget(self.bar)
        layout.addWidget(self.count)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.again)
        layout.addStretch(1)
        self.cancel_button.clicked.connect(self.cancel)
        self.again.clicked.connect(lambda: self.window_.go("choose"))
        self._stopping = False

    def enter(self) -> None:
        s = self.session
        self._stopping = False
        self.heading.setText(wording.SCANNING)
        self.bar.setRange(0, 0)  # busy until the first count arrives
        self.count.setText("")
        self.note.setText("" if sc._default_detector is not None else wording.LOADING_MODEL_NOTE)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.again.hide()
        s.scan = None
        self.backend.scan(s.document_path, s.vault)

    def cancel(self) -> None:
        self._stopping = True
        self.cancel_button.setEnabled(False)
        self.note.setText(wording.STOPPING)
        self.backend.cancel()

    def _back_to_choose(self, message: str = "") -> None:
        self.window_.go("choose")
        self.window_.screens["choose"].error.setText(message)

    # ---- background results

    def on_progress(self, done: int, total: int) -> None:
        if self._stopping:
            return
        self.note.setText("")
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.count.setText(wording.SCAN_COUNT.format(done=done, total=total))

    def on_finished(self, job: str, result) -> None:
        if job != "scan":
            return
        if self._stopping:  # cancel clicked just as it finished: discard
            self._back_to_choose(wording.SCAN_CANCELLED)
            return
        self.session.scan = result
        count = len(result.items)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.note.setText("")
        if "review" in self.window_.screens:
            self.window_.go("review")
        else:
            self.heading.setText(wording.SCAN_DONE_NO_REVIEW.format(count=count))
            self.cancel_button.hide()
            self.again.show()

    def on_cancelled(self, job: str) -> None:
        if job == "scan":
            self.session.scan = None
            self._back_to_choose(wording.SCAN_CANCELLED)

    def on_failed(self, job: str, message: str) -> None:
        if job == "scan":
            self._back_to_choose(wording.plain(message))
