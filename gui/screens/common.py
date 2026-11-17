"""Pieces several screens share: a file box, the matter-and-passphrase form,
and a base class for screens that open a matter before doing their work."""

from __future__ import annotations

import os

import sanitizer_service as service
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui import settings, wording
from gui.app import MARGIN, SPACING, Screen

SHORT_PASSPHRASE = 16


def heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSize(font.pointSize() + 4)
    font.setBold(True)
    label.setFont(font)
    return label


def page(screen: QWidget) -> QVBoxLayout:
    """The outer layout every screen uses, so margins and spacing match."""
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
    layout.setSpacing(SPACING)
    return layout


def tab_chain(*widgets: QWidget) -> None:
    """Tab visits the widgets in this order (creation order is not always reading order)."""
    for first, second in zip(widgets, widgets[1:]):
        QWidget.setTabOrder(first, second)


def big(button: QPushButton, height: int = 40) -> QPushButton:
    """A larger button; Enter presses it while it has the focus."""
    button.setMinimumHeight(height)
    button.setAutoDefault(True)
    return button


class DropArea(QFrame):
    """A dashed box that says where to drop a file. The screen handles the drop
    itself and calls ``set_active`` while a file is being dragged over."""

    PLAIN = "#dropArea { border: 2px dashed palette(mid); border-radius: 8px; }"
    ACTIVE = "#dropArea { border: 2px dashed palette(highlight); border-radius: 8px; background: palette(alternate-base); }"

    def __init__(self, text: str, name: str = ""):
        super().__init__()
        self.setObjectName("dropArea")
        self.setAccessibleName(name or wording.A11Y_DROP)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        row = QVBoxLayout(self)
        row.setContentsMargins(16, 24, 16, 24)
        row.addWidget(label)
        self.setMinimumHeight(90)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self.active = active
        self.setStyleSheet(self.ACTIVE if active else self.PLAIN)


def message_label() -> QLabel:
    """A line for errors and results. Empty until something needs saying."""
    label = QLabel("")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class FilePicker(QWidget):
    """A path box with a Browse button."""

    changed = Signal(str)
    submitted = Signal()  # Enter pressed in the path box

    def __init__(self, file_filter: str, save: bool = False, name: str = "", browse_name: str = ""):
        super().__init__()
        self.file_filter, self.save = file_filter, save
        self.edit = QLineEdit()
        self.button = QPushButton(wording.BROWSE)
        self.edit.setAccessibleName(name or wording.A11Y_DOCUMENT)
        self.button.setAccessibleName(browse_name or wording.A11Y_BROWSE_DOCUMENT)
        self.edit.returnPressed.connect(self.submitted)
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


def ask_replace(parent, existing: list[str], successors: list[str]) -> str:
    """Ask what to do about outputs that already exist: "new", "replace" or "cancel"."""
    box = QMessageBox(QMessageBox.Icon.Question, wording.REPLACE_TITLE,
                      wording.REPLACE_TEXT.format(existing="\n".join(existing)), parent=parent)  # fmt: skip
    box.setInformativeText(wording.REPLACE_NEW_NAMES.format(names="\n".join(os.path.basename(p) for p in successors)))
    new = box.addButton(wording.REPLACE_SAVE_NEW, QMessageBox.ButtonRole.AcceptRole)
    replace = box.addButton(wording.REPLACE_REPLACE, QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(new)
    box.exec()
    return {new: "new", replace: "replace"}.get(box.clickedButton(), "cancel")


def confirm_outputs(parent, paths: list[str | None]) -> list[str | None] | None:
    """``paths`` as they should be used, with any that already exist replaced by a new
    name if the user chooses that, or None if they cancel. Nothing exists: no question."""
    existing = [p for p in paths if p and os.path.exists(p)]
    if not existing:
        return paths
    successors = {p: service.successor_path(p) for p in existing}
    answer = ask_replace(parent, existing, list(successors.values()))
    if answer == "cancel":
        return None
    if answer == "replace":
        return paths
    return [successors.get(p, p) if p else p for p in paths]


class OutputRow(QWidget):
    """"Save the ... as: <path> [Change...]". The path starts as the service's default for
    the document; Change opens a Save dialog and keeps the new name only if the service
    accepts it. Refusals show on a line under the row, in staff words."""

    def __init__(self, label_text: str, label: str):
        super().__init__()
        self.label = label  # "sanitized" or "rehydrated" (the service's word)
        self.input_path = ""
        self.matter_path = ""
        self.picked = False
        self._path = ""
        self.caption = QLabel(label_text)
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setAccessibleName(wording.A11Y_OUTPUT_PATH)
        self.button = QPushButton(wording.CHANGE)
        self.button.setAccessibleName(wording.A11Y_OUTPUT_CHANGE)
        self.button.clicked.connect(self.change)
        self.problem = message_label()
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.caption)
        row.addWidget(self.path_label, 1)
        row.addWidget(self.button)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addLayout(row)
        column.addWidget(self.problem)

    def path(self) -> str:
        return self._path

    def set_source(self, input_path: str, matter_path: str = "", keep_choice: bool = False) -> None:
        """Use ``input_path`` as the document. Unless ``keep_choice`` and the user already
        picked a name, the path goes back to the default."""
        self.input_path, self.matter_path = input_path, matter_path
        if not (keep_choice and self.picked):
            self.picked = False
            self._path = service.default_output_path(input_path, self.label) if input_path else ""
        self.path_label.setText(self._path)
        self.problem.setText("")

    def check(self) -> str | None:
        """The reason the current path cannot be used, in staff words (also shown), or None."""
        reason = service.check_output_path(self.input_path, self._path, self.label, self.matter_path or None)
        text = wording.for_staff(reason) if reason else None
        self.problem.setText(text or "")
        return text

    def change(self) -> None:
        formats = service.output_formats(self.input_path, self.label)
        filters = [wording.OUTPUT_FILTERS.get(ext, f"(*{ext})") for ext in formats]
        current = os.path.splitext(self._path)[1].lower()
        initial = filters[formats.index(current)] if current in formats else filters[0]
        path, chosen = QFileDialog.getSaveFileName(self, wording.APP_NAME, self._path, ";;".join(filters), initial)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            index = filters.index(chosen) if chosen in filters else 0
            path += formats[index]
        reason = service.check_output_path(self.input_path, path, self.label, self.matter_path or None)
        if reason:
            self.problem.setText(wording.for_staff(reason))  # keep the old path
            return
        self._path, self.picked = path, True
        self.path_label.setText(path)
        self.problem.setText("")


class MatterForm(QWidget):
    """Matter file and passphrase. A matter file that does not exist yet is a
    new matter: the passphrase is asked twice and the no-recovery warning shown.
    ``submitted`` fires when Enter is pressed in any of its boxes."""

    submitted = Signal()

    def __init__(self, must_exist: bool = False):
        super().__init__()
        self.must_exist = must_exist
        self._open_path = ""  # the matter already open in this session, if any
        self.picker = FilePicker(
            wording.MATTER_FILES, name=wording.A11Y_MATTER, browse_name=wording.A11Y_BROWSE_MATTER
        )
        self.new_button = QPushButton(wording.MATTER_NEW)
        self.new_button.setVisible(not must_exist)
        self.picker.layout().addWidget(self.new_button)
        self.passphrase = QLineEdit()
        self.again = QLineEdit()
        for box in (self.passphrase, self.again):
            box.setEchoMode(QLineEdit.EchoMode.Password)
            box.returnPressed.connect(self.submitted)
        self.picker.submitted.connect(self.submitted)
        self.passphrase.setAccessibleName(wording.PASSPHRASE)
        self.again.setAccessibleName(wording.PASSPHRASE_AGAIN)
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

    def tab_widgets(self) -> list[QWidget]:
        return [self.picker.edit, self.picker.button, self.new_button, self.passphrase, self.again]

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
        big(self.go_button).setDefault(True)  # Enter in any box also presses it
        self.go_button.clicked.connect(self.start)
        self.form.submitted.connect(self.start)
        self.back_button = big(QPushButton(wording.BACK))
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
        self.form.setEnabled(not busy)
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
        if self.form.passphrase.isVisible():
            self.form.passphrase.setFocus()
            self.form.passphrase.selectAll()
