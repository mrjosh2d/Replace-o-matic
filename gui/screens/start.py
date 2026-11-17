"""Start: two big buttons, an "Open a key" link, recent matters."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from gui import wording
from gui.app import Screen
from gui.screens import recent


class StartScreen(Screen):
    name, step = "start", 0

    def __init__(self, window):
        super().__init__(window)
        title = QLabel(wording.START_TITLE)
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.sanitize = QPushButton(wording.BTN_SANITIZE)
        self.restore = QPushButton(wording.BTN_RESTORE)
        for button in (self.sanitize, self.restore):
            button.setMinimumHeight(90)
            button.setStyleSheet("font-size: 16px;")
        self.key_link = QPushButton(wording.LINK_KEY)
        self.key_link.setFlat(True)
        self.key_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.key_link.setStyleSheet("text-decoration: underline; border: none;")
        self.note = QLabel("")
        self.recent = QListWidget()
        self.recent_title = QLabel(wording.RECENT_TITLE)

        buttons = QHBoxLayout()
        buttons.addWidget(self.sanitize)
        buttons.addWidget(self.restore)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(buttons)
        layout.addWidget(self.key_link, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.note)
        layout.addWidget(self.recent_title)
        layout.addWidget(self.recent, 1)

        self.sanitize.clicked.connect(lambda: self._go("choose"))
        self.restore.clicked.connect(lambda: self._go("restore"))
        self.key_link.clicked.connect(lambda: self._go("key"))
        self.recent.itemActivated.connect(self._open_recent)

    def enter(self) -> None:
        self.note.setText("")
        # Screens for later phases: disabled until they exist.
        self.restore.setEnabled("restore" in self.window_.screens)
        self.key_link.setEnabled("key" in self.window_.screens)
        self.recent.clear()
        paths = recent.existing()
        for path in paths:
            self.recent.addItem(QListWidgetItem(path))
        if not paths:
            self.recent.addItem(QListWidgetItem(wording.RECENT_EMPTY))
            self.recent.item(0).setFlags(Qt.ItemFlag.NoItemFlags)

    def _go(self, name: str) -> None:
        if name in self.window_.screens:
            self.window_.go(name)
        else:
            self.note.setText(wording.NOT_AVAILABLE_YET)

    def _open_recent(self, item: QListWidgetItem) -> None:
        self.session.matter_path = item.text()
        self._go("choose")

    def on_failed(self, job: str, message: str) -> None:
        pass  # a failed model preload is reported again when a scan needs it
