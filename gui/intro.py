"""The first-run walkthrough: four short pages. Shown once, and from Help any time."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui import settings, wording


class IntroDialog(QDialog):
    """Back / Next / Finish over the pages in ``wording.INTRO_PAGES``. Enter is Next (or
    Finish on the last page); Esc or closing the window ends it. However it ends, the
    walkthrough counts as seen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(wording.INTRO_TITLE)
        self.setModal(True)
        self.resize(520, 340)
        self.pages = QStackedWidget()
        for title, body in wording.INTRO_PAGES:
            page = QWidget()
            heading = QLabel(title)
            font = heading.font()
            font.setPointSize(font.pointSize() + 4)
            font.setBold(True)
            heading.setFont(font)
            text = QLabel(body)
            text.setWordWrap(True)
            text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            column = QVBoxLayout(page)
            column.addWidget(heading)
            column.addWidget(text, 1)
            self.pages.addWidget(page)

        self.indicator = QLabel("")
        self.back_button = QPushButton(wording.BACK)
        self.next_button = QPushButton(wording.INTRO_NEXT)
        self.finish_button = QPushButton(wording.INTRO_FINISH)
        row = QHBoxLayout()
        row.addWidget(self.indicator, 1)
        row.addWidget(self.back_button)
        row.addWidget(self.next_button)
        row.addWidget(self.finish_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.pages, 1)
        layout.addLayout(row)

        self.back_button.clicked.connect(lambda: self.show_page(self.page() - 1))
        self.next_button.clicked.connect(lambda: self.show_page(self.page() + 1))
        self.finish_button.clicked.connect(self.accept)
        self.show_page(0)

    def page(self) -> int:
        return self.pages.currentIndex()

    def show_page(self, index: int) -> None:
        last = self.pages.count() - 1
        index = max(0, min(index, last))
        self.pages.setCurrentIndex(index)
        self.indicator.setText(wording.INTRO_PAGE.format(n=index + 1, total=last + 1))
        self.back_button.setEnabled(index > 0)
        self.next_button.setVisible(index < last)
        self.finish_button.setVisible(index == last)
        # Enter presses whichever of the two is showing.
        (self.finish_button if index == last else self.next_button).setDefault(True)

    def done(self, result: int) -> None:  # accept, reject (Esc) and the close button all end here
        settings.set_intro_seen(True)
        super().done(result)


def open_intro(window) -> IntroDialog:
    """Show the walkthrough over ``window`` without blocking (the window keeps the reference)."""
    dialog = IntroDialog(window)
    window._intro = dialog
    dialog.open()
    return dialog


def show_if_first_run(window) -> IntroDialog | None:
    """Called once the window is showing: the walkthrough opens only if it was never seen."""
    return None if settings.intro_seen() else open_intro(window)
