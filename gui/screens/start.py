"""Start: choose what to do. Recent matter files are listed by path only."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QListWidget, QPushButton

from gui import settings, wording
from gui.app import Screen
from gui.screens.common import big, heading, message_label, page, tab_chain


class StartScreen(Screen):
    name, step = "start", 0

    def __init__(self, window):
        super().__init__(window)
        self.sanitize_button = QPushButton(wording.START_SANITIZE)
        self.restore_button = QPushButton(wording.START_RESTORE)
        self.key_button = QPushButton(wording.START_KEY)
        self.key_button.setFlat(True)
        for button in (self.sanitize_button, self.restore_button):
            big(button, 72)
            font = button.font()
            font.setPointSize(font.pointSize() + 3)
            button.setFont(font)
        big(self.key_button, 28)
        self.recent = QListWidget()
        self.recent.setAccessibleName(wording.A11Y_RECENT)
        self.recent_label = QLabel(wording.RECENT_MATTERS)
        self.message = message_label()

        layout = page(self)
        layout.addWidget(heading(wording.START_HEADING))
        layout.addWidget(self.sanitize_button)
        layout.addWidget(self.restore_button)
        layout.addWidget(self.key_button)
        layout.addWidget(self.recent_label)
        layout.addWidget(self.recent, 1)
        layout.addWidget(self.message)

        tab_chain(self.sanitize_button, self.restore_button, self.key_button, self.recent)
        self.sanitize_button.clicked.connect(lambda: self.window_.go("choose"))
        self.restore_button.clicked.connect(lambda: self.window_.go("restore"))
        self.key_button.clicked.connect(self._key)
        self.recent.itemActivated.connect(self._pick)
        self.recent.itemClicked.connect(self._pick)

    def enter(self) -> None:
        self.recent.clear()
        paths = settings.recent_matters()
        self.recent.addItems(paths)
        self.recent_label.setText(wording.RECENT_MATTERS if paths else wording.NO_RECENT_MATTERS)
        self.recent.setVisible(bool(paths))

    def _key(self) -> None:
        self.session.document_path = ""
        self.window_.go("key")

    def _pick(self, item) -> None:
        """Use this matter for the next step. It still needs its passphrase."""
        session = self.session
        if item.text() != session.matter_path:
            session.matter_path, session.passphrase, session.vault = item.text(), "", None
        self.window_.go("choose")

    def on_failed(self, job: str, message: str) -> None:
        self.message.setText(message)
