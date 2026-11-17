"""Pieces several screens share: a file box, the matter-and-passphrase form,
and a base class for screens that open a matter before doing their work."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from gui import settings, wording
from gui.app import Screen

SHORT_PASSPHRASE = 16


def heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSize(font.pointSize() + 4)
    font.setBold(True)
    label.setFont(font)
    return label


def message_label() -> QLabel:
    """A line for errors and results. Empty until something needs saying."""
    label = QLabel("")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class FilePicker(QWidget):
    """A path box with a Browse button."""

    changed = Signal(str)

    def __init__(self, file_filter: str, save: bool = False):
        super().__init__()
        self.file_filter, self.save = file_filter, save
        self.edit = QLineEdit()
        self.button = QPushButton(wording.BROWSE)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.edit, 1)
        row.addWidget(self.button)
        self.button.clicked.connect(self.browse)
        self.edit.textChanged.connect(self.changed)

    def path(self) -> str:
        return self.edit.text().strip()

    def set_path(self, path: str) -> None:
        self.edit.setText(path)

    def browse(self) -> None:
        start = os.path.dirname(self.path())
        if self.save:
            path, _ = QFileDialog.getSaveFileName(self, wording.APP_NAME, start, self.file_filter)
        else:
            path, _ = QFileDialog.getOpenFileName(self, wording.APP_NAME, start, self.file_filter)
        if path:
            self.set_path(path)


class MatterForm(QWidget):
    """Matter file and passphrase. A matter file that does not exist yet is a
    new matter: the passphrase is asked twice and the no-recovery warning shown."""

    def __init__(self, must_exist: bool = False):
        super().__init__()
        self.must_exist = must_exist
        self._open_path = ""  # the matter already open in this session, if any
        self.picker = FilePicker(wording.MATTER_FILES)
        self.new_button = QPushButton(wording.MATTER_NEW)
        self.new_button.setVisible(not must_exist)
        self.picker.layout().addWidget(self.new_button)
        self.passphrase = QLineEdit()
        self.again = QLineEdit()
        for box in (self.passphrase, self.again):
            box.setEchoMode(QLineEdit.EchoMode.Password)
        self.again_label = QLabel(wording.PASSPHRASE_AGAIN)
        self.passphrase_label = QLabel(wording.PASSPHRASE)
        self.hint = QLabel("")
        self.warning = QLabel(wording.NEW_MATTER_WARNING)
        self.warning.setWordWrap(True)
        font = self.warning.font()
        font.setBold(True)
        self.warning.setFont(font)
        self.open_note = QLabel(wording.MATTER_OPEN)

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(wording.MATTER, self.picker)
        form.addRow("", self.open_note)
        form.addRow(self.passphrase_label, self.passphrase)
        form.addRow(self.again_label, self.again)
        form.addRow("", self.hint)
        form.addRow("", self.warning)

        self.new_button.clicked.connect(self._new)
        self.picker.changed.connect(self._refresh)
        self.passphrase.textChanged.connect(self._refresh)
        self._refresh()

    # ---- state

    def path(self) -> str:
        return self.picker.path()

    def is_new(self) -> bool:
        return bool(self.path()) and not os.path.exists(self.path())

    def is_open(self) -> bool:
        """True if this matter was opened earlier in the session: no passphrase needed."""
        return bool(self._open_path) and os.path.abspath(self.path()) == os.path.abspath(self._open_path)

    def reset(self, session) -> None:
        """Called when a screen is shown: forget typed passphrases, show the session's matter."""
        self.passphrase.clear()
        self.again.clear()
        self._open_path = session.matter_path if session.vault is not None else ""
        self.picker.set_path(session.matter_path)
        self._refresh()

    def problem(self) -> str | None:
        """Why the form cannot be used yet, or None."""
        if not self.path():
            return wording.NEED_MATTER
        if self.is_open():
            return None
        if self.is_new() and self.must_exist:
            return wording.MATTER_MISSING
        if not self.passphrase.text():
            return wording.NEED_PASSPHRASE
        if self.is_new() and self.passphrase.text() != self.again.text():
            return wording.PASSPHRASES_DIFFER
        return None

    # ---- internals

    def _new(self) -> None:
        start = os.path.dirname(self.path())
        path, _ = QFileDialog.getSaveFileName(self, wording.APP_NAME, start, wording.MATTER_FILES)
        if path:
            self.picker.set_path(path if os.path.splitext(path)[1] else path + ".vault")

    def _refresh(self, *_) -> None:
        opened = self.is_open()
        new = self.is_new() and not self.must_exist and not opened
        self.open_note.setVisible(opened)
        for widget in (self.passphrase_label, self.passphrase):
            widget.setVisible(not opened)
        for widget in (self.again_label, self.again, self.warning, self.hint):
            widget.setVisible(new)
        typed = len(self.passphrase.text())
        self.hint.setText(
            "" if not typed else wording.PASSPHRASE_HINT_SHORT if typed < SHORT_PASSPHRASE else wording.PASSPHRASE_HINT_OK
        )


class MatterScreen(Screen):
    """A screen with a MatterForm. ``start()`` checks the form, opens the matter
    on the background thread if it is not open yet, then calls ``proceed()``."""

    def __init__(self, window, must_exist: bool = False):
        super().__init__(window)
        self.form = MatterForm(must_exist)
        self._opening = None
        self.message = message_label()
        self.go_button = QPushButton(wording.CONTINUE)
        self.go_button.setDefault(True)
        self.go_button.clicked.connect(self.start)
        self.back_button = QPushButton(wording.BACK)
        self.back_button.clicked.connect(lambda: self.window_.go("start"))

    def buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.back_button)
        row.addWidget(self.go_button)
        return row

    def enter(self) -> None:
        self.form.reset(self.session)
        self.set_busy(False)

    def forget(self) -> None:
        self._opening = None
        self.form.passphrase.clear()
        self.form.again.clear()
        self.message.setText("")

    def set_busy(self, busy: bool) -> None:
        self.go_button.setEnabled(not busy)
        if busy:
            self.message.setText(wording.WORKING)

    def check(self) -> str | None:
        """Extra checks before the matter is opened. Override."""
        return None

    def proceed(self) -> None:
        """The matter is open (``session.vault``). Override."""

    def start(self) -> None:
        problem = self.check() or self.form.problem()
        if problem:
            self.message.setText(problem)
            return
        self.message.setText("")
        if self.form.is_open():
            self.proceed()
            return
        self.set_busy(True)
        self._opening = (self.form.path(), self.form.passphrase.text())
        self.backend.open_matter(*self._opening)

    def on_finished(self, job: str, result) -> None:
        if job != "open_matter" or self._opening is None:
            return
        session = self.session
        session.matter_path, session.passphrase = self._opening
        session.vault = result
        self._opening = None
        self.form.reset(session)  # clears the passphrase boxes and shows the matter as open
        if os.path.exists(session.matter_path):  # a new matter is listed once it has been saved
            settings.remember_matter(session.matter_path)
        self.message.setText("")
        self.proceed()

    def on_failed(self, job: str, message: str) -> None:
        if job == "preload" and self.message.text() == wording.WORKING:
            return  # the step in hand is still running
        self._opening = None
        self.set_busy(False)
        self.message.setText(message)
