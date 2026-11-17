"""Choose: the document, the matter file and the passphrase."""

from __future__ import annotations

import os

import sanitizer_service as service
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from gui import wording
from gui.app import Screen
from gui.screens import recent

EXTENSIONS = (".docx", ".pdf", ".txt")


def strength(passphrase: str) -> str:
    """A simple hint, not a guarantee: length and number of words."""
    if len(passphrase) < 8:
        return wording.STRENGTH_WEAK
    if len(passphrase) >= 16 or len(passphrase.split()) >= 4:
        return wording.STRENGTH_GOOD
    return wording.STRENGTH_FAIR


class ChooseScreen(Screen):
    name, step = "choose", 1

    def __init__(self, window):
        super().__init__(window)
        self.setAcceptDrops(True)
        title = QLabel(wording.CHOOSE_TITLE)
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        self.document_label = QLabel(wording.DROP_HERE)
        self.document_label.setStyleSheet("border: 2px dashed gray; padding: 24px;")
        self.document_label.setWordWrap(True)
        self.browse_document = QPushButton(wording.BROWSE)

        self.existing = QRadioButton(wording.MATTER_EXISTING)
        self.new = QRadioButton(wording.MATTER_NEW)
        self.existing.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.existing)
        group.addButton(self.new)
        self.matter_label = QLabel(wording.MATTER_NONE_CHOSEN)
        self.matter_label.setWordWrap(True)
        self.browse_matter = QPushButton(wording.BROWSE)

        self.passphrase = QLineEdit()
        self.passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        self.again = QLineEdit()
        self.again.setEchoMode(QLineEdit.EchoMode.Password)
        self.again_label = QLabel(wording.PASSPHRASE_AGAIN)
        self.hint = QLabel("")
        self.warning = QLabel(wording.NEW_MATTER_WARNING)
        self.warning.setWordWrap(True)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b00020;")
        self.back = QPushButton(wording.BACK)
        self.go_button = QPushButton(wording.CONTINUE)

        form = QFormLayout()
        form.addRow(wording.PASSPHRASE, self.passphrase)
        form.addRow(self.again_label, self.again)

        doc_row = QHBoxLayout()
        doc_row.addWidget(self.document_label, 1)
        doc_row.addWidget(self.browse_document)
        matter_row = QHBoxLayout()
        matter_row.addWidget(self.matter_label, 1)
        matter_row.addWidget(self.browse_matter)
        buttons = QHBoxLayout()
        buttons.addWidget(self.back)
        buttons.addStretch(1)
        buttons.addWidget(self.go_button)

        layout = QVBoxLayout(self)
        for item in (title,):
            layout.addWidget(item)
        layout.addLayout(doc_row)
        layout.addWidget(self.existing)
        layout.addWidget(self.new)
        layout.addLayout(matter_row)
        layout.addLayout(form)
        layout.addWidget(self.hint)
        layout.addWidget(self.warning)
        layout.addWidget(self.error)
        layout.addStretch(1)
        layout.addLayout(buttons)

        self.browse_document.clicked.connect(self._browse_document)
        self.browse_matter.clicked.connect(self._browse_matter)
        self.existing.toggled.connect(self._mode_changed)
        self.passphrase.textChanged.connect(self._update_hint)
        self.back.clicked.connect(lambda: self.window_.go("start"))
        self.go_button.clicked.connect(self.submit)
        self._mode_changed()

    # ---- showing

    def enter(self) -> None:
        """Show what the session already holds (it is empty after a lock)."""
        s = self.session
        self.error.setText("")
        self.go_button.setEnabled(True)
        self.document_label.setText(s.document_path or wording.DROP_HERE)
        if s.matter_path:
            self.new.setChecked(not os.path.exists(s.matter_path))
            self.existing.setChecked(os.path.exists(s.matter_path))
        self.matter_label.setText(s.matter_path or wording.MATTER_NONE_CHOSEN)
        if not s.passphrase:
            self.forget()
        else:
            self.passphrase.setText(s.passphrase)
            self.again.setText(s.passphrase)

    def forget(self) -> None:
        """Clear everything typed here (called by ``MainWindow.lock``)."""
        self.passphrase.clear()
        self.again.clear()
        self.error.setText("")
        self.document_label.setText(wording.DROP_HERE)
        self.matter_label.setText(wording.MATTER_NONE_CHOSEN)

    @property
    def is_new(self) -> bool:
        return self.new.isChecked()

    def _mode_changed(self) -> None:
        for widget in (self.again, self.again_label, self.hint, self.warning):
            widget.setVisible(self.is_new)
        self.browse_matter.setText(wording.BROWSE)
        self._update_hint()

    def _update_hint(self) -> None:
        self.hint.setText(strength(self.passphrase.text()) if self.passphrase.text() else "")

    # ---- choosing files

    def set_document(self, path: str) -> bool:
        """Accept a file if it is usable. Shows the reason if not."""
        self.error.setText("")
        if not os.path.isfile(path):
            self.error.setText(wording.ERR_NOT_FOUND)
        elif not path.lower().endswith(EXTENSIONS):
            self.error.setText(wording.ERR_BAD_TYPE)
        elif path.lower().endswith(".pdf") and not service.pdf_io.available():
            self.error.setText(wording.ERR_NO_PDF)
        else:
            self.session.document_path = path
            self.document_label.setText(path)
            return True
        return False

    def set_matter(self, path: str) -> None:
        self.session.matter_path = path
        self.matter_label.setText(path)

    def _browse_document(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, wording.BROWSE_DOCUMENT_TITLE, "", wording.DOCUMENT_FILTER)
        if path:
            self.set_document(path)

    def _browse_matter(self) -> None:
        if self.is_new:
            path, _ = QFileDialog.getSaveFileName(self, wording.MATTER_SAVE_TITLE, "", wording.MATTER_FILTER)
        else:
            path, _ = QFileDialog.getOpenFileName(self, wording.MATTER_OPEN_TITLE, "", wording.MATTER_FILTER)
        if path:
            self.set_matter(path)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt name)
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.set_document(urls[0])

    # ---- continuing

    def _problem(self) -> str:
        s = self.session
        if not s.document_path:
            return wording.ERR_NO_DOCUMENT
        if not s.matter_path:
            return wording.ERR_NO_MATTER
        if self.is_new and os.path.exists(s.matter_path):
            return wording.ERR_MATTER_EXISTS
        if not self.is_new and not os.path.isfile(s.matter_path):
            return wording.ERR_MATTER_MISSING
        if not self.passphrase.text():
            return wording.ERR_NO_PASSPHRASE
        if self.is_new and self.passphrase.text() != self.again.text():
            return wording.ERR_MISMATCH
        return ""

    def submit(self) -> None:
        problem = self._problem()
        self.error.setText(problem)
        if problem:
            return
        self.session.passphrase = self.passphrase.text()
        self.go_button.setEnabled(False)
        self.error.setText(wording.OPENING_MATTER)
        self.backend.open_matter(self.session.matter_path, self.session.passphrase)

    # ---- background results

    def on_finished(self, job: str, result) -> None:
        if job != "open_matter":
            return
        self.session.vault = result
        recent.add(self.session.matter_path)
        self.window_.go("scanning")

    def on_failed(self, job: str, message: str) -> None:
        if job == "preload":
            return  # reported again if a scan needs the model
        if job == "open_matter":
            self.session.passphrase = ""  # a wrong one must not stay in memory
        self.go_button.setEnabled(True)
        self.error.setText(wording.plain(message))
