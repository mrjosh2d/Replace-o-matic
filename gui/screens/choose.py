"""Choose: the document, its matter file and the passphrase."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QFormLayout

from gui import wording
from gui.screens.common import DropArea, FilePicker, MatterScreen, heading, page, tab_chain

EXTENSIONS = (".docx", ".pdf", ".txt")


class ChooseScreen(MatterScreen):
    name, step = "choose", 1

    def __init__(self, window):
        super().__init__(window)
        self.document = FilePicker(wording.DOCUMENT_FILES)
        self.drop_area = DropArea(wording.CHOOSE_DROP)
        self.setAcceptDrops(True)  # a file dropped anywhere on the screen counts
        self.document.submitted.connect(self.start)
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow(wording.DOCUMENT, self.document)
        layout = page(self)
        layout.addWidget(heading(wording.CHOOSE_HEADING))
        layout.addWidget(self.drop_area)
        layout.addLayout(form)
        layout.addWidget(self.form)
        layout.addWidget(self.message)
        layout.addStretch(1)
        layout.addLayout(self.buttons())
        tab_chain(self.document.edit, self.document.button, *self.form.tab_widgets(),
                  self.back_button, self.go_button)  # fmt: skip
        self.pending_message = ""  # set by the Scanning screen when it sends the user back

    def enter(self) -> None:
        super().enter()
        self.document.set_path(self.session.document_path)
        self.message.setText(self.pending_message)
        self.pending_message = ""

    def check(self) -> str | None:
        path = self.document.path()
        if not path:
            return wording.NEED_DOCUMENT
        if not os.path.isfile(path):
            return wording.DOCUMENT_MISSING
        return None

    def proceed(self) -> None:
        self.session.document_path = self.document.path()
        self.window_.go("scanning")

    # ---- drag and drop

    def _dropped(self, event) -> str:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        path = urls[0].toLocalFile() if len(urls) == 1 else ""
        return path if path.lower().endswith(EXTENSIONS) else ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self._dropped(event):
            self.drop_area.set_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.drop_area.set_active(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.drop_area.set_active(False)
        path = self._dropped(event)
        if path:
            self.document.set_path(path)
            event.acceptProposedAction()
