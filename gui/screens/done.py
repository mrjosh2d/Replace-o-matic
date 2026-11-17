"""Done: what was written and where, anything to check, and what to do next."""

from __future__ import annotations

import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton

from gui import settings, wording
from gui.app import Screen
from gui.screens.common import big, heading, message_label, page, tab_chain


class DoneScreen(Screen):
    name, step = "done", 4

    def __init__(self, window):
        super().__init__(window)
        self.summary = message_label()
        self.check_label = QLabel(wording.CHECK_THESE)
        self.check_label.setWordWrap(True)
        self.residue = QListWidget()
        self.residue.setAccessibleName(wording.A11Y_RESIDUE)
        self.folder_button = big(QPushButton(wording.OPEN_FOLDER))
        self.key_button = big(QPushButton(wording.MAKE_KEY))
        self.another_button = big(QPushButton(wording.SANITIZE_ANOTHER))
        self.another_button.setDefault(True)
        row = QHBoxLayout()
        row.addWidget(self.folder_button)
        row.addStretch(1)
        row.addWidget(self.key_button)
        row.addWidget(self.another_button)
        layout = page(self)
        layout.addWidget(heading(wording.DONE_HEADING))
        layout.addWidget(self.summary)
        layout.addWidget(self.check_label)
        layout.addWidget(self.residue, 1)
        layout.addStretch(0)
        layout.addLayout(row)
        tab_chain(self.residue, self.folder_button, self.key_button, self.another_button)
        self.folder_button.clicked.connect(self.open_folder)
        self.key_button.clicked.connect(self.make_key)
        self.another_button.clicked.connect(self.another)

    def enter(self) -> None:
        result, session = self.session.result, self.session
        settings.remember_matter(session.matter_path)
        lines = [
            wording.DONE_OUTPUT.format(path=result.output_path),
            wording.DONE_MATTER.format(path=session.matter_path),
            wording.DONE_COUNTS.format(
                replaced=wording.plural(result.replaced, wording.REPLACEMENTS),
                added=wording.plural(result.added, wording.NEW_ITEMS),
                declined=result.declined,
            ),
        ]
        if not result.reviewed and result.added:
            lines.append(wording.DONE_NOT_REVIEWED)
        self.summary.setText("\n".join(lines))
        self.residue.clear()
        self.residue.addItems([wording.RESIDUE_ROW.format(value=v, times=wording.times(n)) for v, n in result.residue])
        self.check_label.setVisible(bool(result.residue))
        self.residue.setVisible(bool(result.residue))

    def forget(self) -> None:
        self.summary.setText("")
        self.residue.clear()

    def open_folder(self) -> None:
        folder = os.path.dirname(os.path.abspath(self.session.result.output_path))
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))  # a local folder, in the file manager

    def make_key(self) -> None:
        self.session.document_path = self.session.result.output_path
        self.window_.go("key")

    def another(self) -> None:
        self.window_.new_task()
        self.window_.go("choose")
