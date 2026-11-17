"""Make a key: the confidential one, the safe one, or both."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QMessageBox

from gui import wording
from gui.screens.common import FilePicker, MatterScreen, heading, page, tab_chain


class KeyScreen(MatterScreen):
    name, step = "key", None

    def __init__(self, window):
        super().__init__(window, must_exist=True)
        self.document = FilePicker(wording.DOCUMENT_FILES, name=wording.KEY_DOCUMENT)
        self.document.submitted.connect(self.start)
        self.confidential = QCheckBox(wording.KEY_CONFIDENTIAL)
        self.safe = QCheckBox(wording.KEY_SAFE)
        self.go_button.setText(wording.KEY_MAKE)
        form = QFormLayout()
        form.addRow(wording.KEY_DOCUMENT, self.document)
        form.addRow("", QLabel(wording.KEY_DOCUMENT_HINT))
        layout = page(self)
        layout.addWidget(heading(wording.KEY_HEADING))
        layout.addLayout(form)
        layout.addWidget(self.form)
        layout.addWidget(self.confidential)
        layout.addWidget(self.safe)
        layout.addWidget(self.message)
        layout.addStretch(1)
        layout.addLayout(self.buttons())
        tab_chain(self.document.edit, self.document.button, *self.form.tab_widgets(), self.confidential, self.safe,
                  self.back_button, self.go_button)  # fmt: skip

    def enter(self) -> None:
        super().enter()
        self.document.set_path(self.session.document_path)
        self.confidential.setChecked(True)
        self.safe.setChecked(False)
        self.message.setText("")

    def check(self) -> str | None:
        path = self.document.path()
        if path and not os.path.isfile(path):
            return wording.DOCUMENT_MISSING
        if not (self.confidential.isChecked() or self.safe.isChecked()):
            return wording.KEY_NEED_ONE
        return None

    def proceed(self) -> None:
        if self.confidential.isChecked():
            answer = QMessageBox.question(self, wording.KEY_CONFIDENTIAL_TITLE, wording.CONFIDENTIAL_KEY_WARNING)
            if answer != QMessageBox.StandardButton.Yes:
                self.set_busy(False)
                self.message.setText("")
                return
        self.set_busy(True)
        self.backend.write_keys(
            self.session.vault,
            self.document.path() or None,
            self.session.matter_path,
            confidential=self.confidential.isChecked(),
            safe=self.safe.isChecked(),
        )

    def on_finished(self, job: str, result) -> None:
        super().on_finished(job, result)
        if job != "keys":
            return
        self.set_busy(False)
        lines = [wording.KEY_DONE.format(standins=wording.plural(result.count, "stand-in"))]
        if result.confidential_path:
            lines.append(wording.KEY_WROTE_CONFIDENTIAL.format(path=result.confidential_path))
        if result.safe_path:
            lines.append(wording.KEY_WROTE_SAFE.format(path=result.safe_path))
        self.message.setText("\n".join(lines))
