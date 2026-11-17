"""Restore an analysis: put the real names back into a file that came back."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QFormLayout

from gui import wording
from gui.screens.common import FilePicker, MatterScreen, OutputRow, confirm_outputs, heading, page, tab_chain


class RestoreScreen(MatterScreen):
    name, step = "restore", None

    def __init__(self, window):
        super().__init__(window, must_exist=True)
        self.document = FilePicker(wording.RESTORE_FILES, name=wording.RESTORE_FILE, browse_name="Browse for the file that came back")
        self.document.submitted.connect(self.start)
        self.output = OutputRow(wording.OUTPUT_RESTORED, "rehydrated")
        self.output.setVisible(False)
        self.document.changed.connect(self._document_changed)
        self.go_button.setText(wording.RESTORE)
        form = QFormLayout()
        form.addRow(wording.RESTORE_FILE, self.document)
        layout = page(self)
        layout.addWidget(heading(wording.RESTORE_HEADING))
        layout.addLayout(form)
        layout.addWidget(self.output)
        layout.addWidget(self.form)
        layout.addWidget(self.message)
        layout.addStretch(1)
        layout.addLayout(self.buttons())
        tab_chain(self.document.edit, self.document.button, self.output.button, *self.form.tab_widgets(), self.back_button, self.go_button)

    def enter(self) -> None:
        super().enter()
        self.document.set_path("")
        self.output.set_source("")  # forget any name picked earlier
        self._document_changed("")
        self.message.setText("")

    def _document_changed(self, path: str) -> None:
        path = path.strip()
        self.output.setVisible(bool(path))
        if path:
            self.output.set_source(path, keep_choice=True)

    def check(self) -> str | None:
        path = self.document.path()
        if not path:
            return wording.NEED_DOCUMENT
        if not os.path.isfile(path):
            return wording.DOCUMENT_MISSING
        self.output.matter_path = self.form.path()  # never write over the matter file
        return self.output.check()

    def proceed(self) -> None:
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
        if job != "restore":
            return
        self.set_busy(False)
        lines = [wording.RESTORE_DONE.format(standins=wording.plural(result.restored, "stand-in"), path=result.output_path)]
        if result.altered:
            lines.append(wording.RESTORE_ALTERED.format(items=", ".join(result.altered)))
        if result.unknown:
            lines.append(wording.RESTORE_UNKNOWN.format(items=", ".join(result.unknown)))
        self.message.setText("\n".join(lines))
