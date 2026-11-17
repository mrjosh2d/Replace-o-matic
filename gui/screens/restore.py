"""Restore an analysis: put the real names back into what came back.

Three ways in: choose a file, drop a file (or dropped text) on the screen, or
paste the text. Pasted text is restored in memory and shown in the window with
Copy and Save as; nothing is written unless the user saves it, because the
result holds the real names."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QByteArray, QMimeData
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import sanitizer_service as service
from gui import wording
from gui.screens.common import DropArea, FilePicker, MatterScreen, OutputRow, confirm_outputs, heading, page, tab_chain

EXTENSIONS = (".docx", ".txt")
PASTED_NAME = "pasted.txt"  # Save as suggests the usual restored name for it: pasted.rehydrated.txt
FILE_TAB, PASTE_TAB = 0, 1
PASTE_PAGE, RESULT_PAGE = 0, 1

# Windows clipboard formats that keep a copy out of clipboard history and cloud
# clipboard sync. Their value is a DWORD; 0 means "no".
_PRIVATE_CLIPBOARD_FORMATS = ("CanIncludeInClipboardHistory", "CanUploadToCloudClipboard")


def copy_private(text: str) -> None:
    """Put ``text`` on the clipboard. On Windows, mark it so it is not kept in
    clipboard history or synced to other devices: it holds the real names."""
    mime = QMimeData()
    mime.setText(text)
    if sys.platform == "win32":
        no = QByteArray(b"\0\0\0\0")
        for name in _PRIVATE_CLIPBOARD_FORMATS:
            mime.setData(f'application/x-qt-windows-mime;value="{name}"', no)
    QApplication.clipboard().setMimeData(mime)


class RestoreScreen(MatterScreen):
    name, step = "restore", None

    def __init__(self, window):
        super().__init__(window, must_exist=True)
        self.setAcceptDrops(True)  # a file or text dropped anywhere on the screen counts

        # ---- from a file
        self.drop_area = DropArea(wording.RESTORE_DROP, name=wording.A11Y_RESTORE_DROP)
        self.document = FilePicker(wording.RESTORE_FILES, name=wording.RESTORE_FILE, browse_name="Browse for the file that came back")
        self.document.submitted.connect(self.start)
        self.output = OutputRow(wording.OUTPUT_RESTORED, "rehydrated")
        self.output.setVisible(False)
        self.document.changed.connect(self._document_changed)
        file_tab = QWidget()
        file_form = QFormLayout()
        file_form.addRow(wording.RESTORE_FILE, self.document)
        file_layout = QVBoxLayout(file_tab)
        file_layout.addWidget(self.drop_area)
        file_layout.addLayout(file_form)
        file_layout.addWidget(self.output)
        file_layout.addStretch(1)

        # ---- paste text: a box to paste into, then the restored text
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText(wording.RESTORE_PASTE_HINT)
        self.paste.setAccessibleName(wording.A11Y_PASTE)
        self.paste.setAcceptDrops(False)  # the screen takes drops, so a dropped file is not pasted as its name
        self.paste.textChanged.connect(lambda: self.message.setText(""))
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setAccessibleName(wording.A11Y_RESTORED_TEXT)
        self.result.setAcceptDrops(False)
        self.copy_button = QPushButton(wording.RESTORE_COPY)
        self.save_button = QPushButton(wording.RESTORE_SAVE_AS)
        self.again_button = QPushButton(wording.RESTORE_PASTE_ANOTHER)
        self.copy_button.clicked.connect(self.copy)
        self.save_button.clicked.connect(self.save)
        self.again_button.clicked.connect(self.paste_another)
        result_page = QWidget()
        result_buttons = QHBoxLayout()
        result_buttons.addWidget(self.copy_button)
        result_buttons.addWidget(self.save_button)
        result_buttons.addStretch(1)
        result_buttons.addWidget(self.again_button)
        result_layout = QVBoxLayout(result_page)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(self.result, 1)
        result_layout.addLayout(result_buttons)
        self.paste_pages = QStackedWidget()
        self.paste_pages.addWidget(self.paste)
        self.paste_pages.addWidget(result_page)
        paste_tab = QWidget()
        paste_layout = QVBoxLayout(paste_tab)
        paste_layout.addWidget(self.paste_pages)

        self.tabs = QTabWidget()
        self.tabs.addTab(file_tab, wording.RESTORE_TAB_FILE)
        self.tabs.addTab(paste_tab, wording.RESTORE_TAB_PASTE)
        self.tabs.currentChanged.connect(self._mode_changed)

        self.go_button.setText(wording.RESTORE)
        layout = page(self)
        layout.addWidget(heading(wording.RESTORE_HEADING))
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.form)
        layout.addWidget(self.message)
        layout.addLayout(self.buttons())
        tab_chain(self.tabs.tabBar(), self.document.edit, self.document.button, self.output.button,
                  self.paste, self.result, self.copy_button, self.save_button, self.again_button,
                  *self.form.tab_widgets(), self.back_button, self.go_button)  # fmt: skip

    # ---- state

    def pasting(self) -> bool:
        return self.tabs.currentIndex() == PASTE_TAB

    def showing_result(self) -> bool:
        return self.pasting() and self.paste_pages.currentIndex() == RESULT_PAGE

    def enter(self) -> None:
        super().enter()
        self.document.set_path("")
        self.output.set_source("")  # forget any name picked earlier
        self._document_changed("")
        self._clear_paste()
        self.tabs.setCurrentIndex(FILE_TAB)
        self.message.setText("")

    def forget(self) -> None:
        super().forget()
        self._clear_paste()

    def _clear_paste(self) -> None:
        """Drop the pasted and restored text: the restored text holds the real names."""
        self.paste.clear()
        self.result.clear()
        self.paste_pages.setCurrentIndex(PASTE_PAGE)
        self._update_go()

    def set_busy(self, busy: bool) -> None:
        super().set_busy(busy)
        self.tabs.setEnabled(not busy)
        self._update_go(busy)

    def _update_go(self, busy: bool = False) -> None:
        # With the restored text showing there is nothing to restore; Paste another starts over.
        self.go_button.setEnabled(not busy and not self.showing_result())

    def _mode_changed(self, _index: int) -> None:
        self.message.setText("")
        self._update_go()

    def _document_changed(self, path: str) -> None:
        path = path.strip()
        self.output.setVisible(bool(path))
        if path:
            self.output.set_source(path, keep_choice=True)

    # ---- restore

    def check(self) -> str | None:
        if self.pasting():
            if self.showing_result() or self.paste.toPlainText().strip():
                return None
            return wording.NEED_PASTE
        path = self.document.path()
        if not path:
            return wording.NEED_DOCUMENT
        if not os.path.isfile(path):
            return wording.DOCUMENT_MISSING
        self.output.matter_path = self.form.path()  # never write over the matter file
        return self.output.check()

    def proceed(self) -> None:
        if self.pasting():
            if self.showing_result():
                self.set_busy(False)
                return
            self.set_busy(True)
            self.backend.restore_text(self.paste.toPlainText(), self.session.vault)
            return
        output = self.output.path()
        if not self.output.picked:  # a name picked in the Save dialog was confirmed there
            chosen = confirm_outputs(self, [output])
            if chosen is None:
                self.set_busy(False)
                return
            output = chosen[0]
        self.set_busy(True)
        self.backend.restore(self.document.path(), self.session.vault, output)

    def on_finished(self, job: str, result) -> None:
        super().on_finished(job, result)
        if job == "restore":
            self.set_busy(False)
            lines = [wording.RESTORE_DONE.format(standins=wording.plural(result.restored, "stand-in"), path=result.output_path)]
            self.message.setText("\n".join(lines + self._notes(result)))
        elif job == "restore_text":
            text, info = result
            self.paste.clear()  # keep only one copy: the restored text
            self.result.setPlainText(text)
            self.paste_pages.setCurrentIndex(RESULT_PAGE)
            self.set_busy(False)
            lines = [wording.RESTORE_PASTE_DONE.format(standins=wording.plural(info.restored, "stand-in"))]
            self.message.setText("\n".join(lines + self._notes(info)))
            self.copy_button.setFocus()
        elif job == "save_text":
            self.set_busy(False)
            self.message.setText(wording.RESTORE_SAVED.format(path=result))

    @staticmethod
    def _notes(result) -> list[str]:
        lines = []
        if result.altered:
            lines.append(wording.RESTORE_ALTERED.format(items=", ".join(result.altered)))
        if result.unknown:
            lines.append(wording.RESTORE_UNKNOWN.format(items=", ".join(result.unknown)))
        return lines

    # ---- the restored text

    def copy(self) -> None:
        copy_private(self.result.toPlainText())
        self.message.setText(wording.RESTORE_COPIED_WINDOWS if sys.platform == "win32" else wording.RESTORE_COPIED)

    def save(self) -> None:
        folder = os.path.dirname(self.session.matter_path) if self.session.matter_path else ""
        start = service.default_output_path(os.path.join(folder, PASTED_NAME), "rehydrated")
        path, _ = QFileDialog.getSaveFileName(self, wording.APP_NAME, start, wording.OUTPUT_FILTERS[".txt"])
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".txt"
        self.set_busy(True)
        self.backend.save_restored_text(self.result.toPlainText(), path, self.session.matter_path or None)

    def paste_another(self) -> None:
        self._clear_paste()
        self.message.setText("")
        self.paste.setFocus()

    # ---- drag and drop

    def _dropped(self, event) -> tuple[str, str]:
        """("file", path) for one .docx or .txt file, ("text", text) for dropped text, else ("", "")."""
        data = event.mimeData()
        if data.hasUrls():
            urls = data.urls()
            path = urls[0].toLocalFile() if len(urls) == 1 else ""
            return ("file", path) if path.lower().endswith(EXTENSIONS) else ("", "")
        if data.hasText() and data.text().strip():
            return "text", data.text()
        return "", ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self.tabs.isEnabled():  # not while a restore is running
            kind, _ = self._dropped(event)
            if kind:
                self.drop_area.set_active(kind == "file")
                event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.drop_area.set_active(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.drop_area.set_active(False)
        kind, value = self._dropped(event)
        if kind == "file":
            self.tabs.setCurrentIndex(FILE_TAB)
            self.document.set_path(value)
        elif kind == "text":
            self.tabs.setCurrentIndex(PASTE_TAB)
            self._clear_paste()
            self.paste.setPlainText(value)
        else:
            return
        event.acceptProposedAction()
