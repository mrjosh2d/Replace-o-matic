"""Review: a table of what was found, the places it appears, and Sanitize.

The decisions live in ``ReviewState`` (via ``ReviewTableModel``); this screen
presents them. The table sits behind a proxy model for sorting, the type
filter and the search box, so every row number from the view is mapped back
to the source model before it is used.
"""

from __future__ import annotations

import html

import sanitizer_service as service
from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
)

from gui import wording
from gui.app import Screen
from gui.review_model import TEXT, TICK, TYPE, TYPE_LABELS, ReviewTableModel

import sanitizer_core as sc

CONTEXT_WIDTH = 45


def type_combo(parent=None) -> QComboBox:
    combo = QComboBox(parent)
    for etype in sc.ENTITY_TYPES:
        combo.addItem(TYPE_LABELS[etype], etype)
    return combo


class TypeDelegate(QStyledItemDelegate):
    """A drop-down of the types for the Type column."""

    def createEditor(self, parent, option, index):  # noqa: N802 (Qt name)
        return type_combo(parent)

    def setEditorData(self, editor, index):  # noqa: N802
        editor.setCurrentIndex(max(0, editor.findData(index.data(Qt.ItemDataRole.EditRole))))

    def setModelData(self, editor, model, index):  # noqa: N802
        model.setData(index, editor.currentData(), Qt.ItemDataRole.EditRole)


class ReviewProxy(QSortFilterProxyModel):
    """Sorting, type filter and search over the review table."""

    def __init__(self):
        super().__init__()
        self.type_filter = ""
        self.search = ""

    def set_filters(self, etype: str | None = None, search: str | None = None) -> None:
        if etype is not None:
            self.type_filter = etype
        if search is not None:
            self.search = search.strip().lower()
        self.invalidate()

    def filterAcceptsRow(self, row, parent):  # noqa: N802
        item = self.sourceModel().state.rows[row].item
        if self.type_filter and item.type != self.type_filter:
            return False
        return not self.search or self.search in item.value.lower()

    def lessThan(self, left, right):  # noqa: N802
        if left.column() == TICK:
            rows = self.sourceModel().state.rows
            return rows[left.row()].accepted < rows[right.row()].accepted
        return super().lessThan(left, right)


class AddDialog(QDialog):
    """Type or paste the exact text, choose a type, see the count before confirming."""

    def __init__(self, model: ReviewTableModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle(wording.ADD_TITLE)
        self.text = QLineEdit()
        self.type = type_combo()
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        layout = QVBoxLayout(self)
        for widget in (QLabel(wording.ADD_TEXT_LABEL), self.text, QLabel(wording.ADD_TYPE_LABEL), self.type, self.info, self.buttons):
            layout.addWidget(widget)
        self.text.textChanged.connect(self.update_info)
        self.type.currentIndexChanged.connect(self.update_info)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.update_info()

    def update_info(self) -> None:
        text = self.text.text().strip()
        problem = self.model.state.check_add(self.type.currentData(), text)
        self.ok.setEnabled(problem is None)
        if not text:
            self.info.setText("")
        elif problem:
            self.info.setText(problem)
        else:
            scan_text = self.model.state.scan.text
            n = len(service.occurrences(scan_text, text))
            self.info.setText(f"{wording.ADD_COUNT.format(n=n)}\n{service.first_context(scan_text, text)}")


class ReviewScreen(Screen):
    name, step = "review", 3

    def __init__(self, window):
        super().__init__(window)
        self.model: ReviewTableModel | None = None
        self.proxy = ReviewProxy()
        self._occurrences: list[tuple[int, int]] = []
        self._position = 0
        self._source_row: int | None = None
        self._committing = False

        self.heading = QLabel("")
        self.heading.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.accept_all_button = QPushButton(wording.ACCEPT_ALL)
        self.decline_button = QPushButton(wording.DECLINE_SELECTED)
        self.filter = QComboBox()
        self.filter.addItem(wording.FILTER_ALL, "")
        for etype in sc.ENTITY_TYPES:
            self.filter.addItem(TYPE_LABELS[etype], etype)
        self.search = QLineEdit()
        self.search.setPlaceholderText(wording.SEARCH_PLACEHOLDER)
        self.search.setClearButtonEnabled(True)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setItemDelegateForColumn(TYPE, TypeDelegate(self.table))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()

        self.where = QLabel(wording.WHERE_NOTHING)
        self.where.setStyleSheet("font-weight: bold;")
        self.previous = QPushButton("<")
        self.previous.setToolTip(wording.PREVIOUS)
        self.next = QPushButton(">")
        self.next.setToolTip(wording.NEXT)
        self.context = QLabel("")
        self.context.setWordWrap(True)
        self.context.setTextFormat(Qt.TextFormat.RichText)
        self.context.setMinimumHeight(60)
        self.context.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.add_button = QPushButton(wording.ADD_MISSED)
        self.back_button = QPushButton(wording.BACK)
        self.sanitize_button = QPushButton(wording.SANITIZE_COUNT.format(n=0))
        self.sanitize_button.setDefault(True)

        top = QHBoxLayout()
        for widget in (self.heading, self.accept_all_button, self.decline_button):
            top.addWidget(widget)
        top.addStretch(1)
        for widget in (QLabel(wording.FILTER_LABEL), self.filter, self.search):
            top.addWidget(widget)
        where_row = QHBoxLayout()
        where_row.addWidget(self.where, 1)
        where_row.addWidget(self.previous)
        where_row.addWidget(self.next)
        bottom = QHBoxLayout()
        bottom.addWidget(self.add_button)
        bottom.addStretch(1)
        bottom.addWidget(self.back_button)
        bottom.addWidget(self.sanitize_button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(where_row)
        layout.addWidget(self.context)
        layout.addWidget(self.message)
        layout.addLayout(bottom)

        self.accept_all_button.clicked.connect(lambda: self.model and self.model.accept_all())
        self.decline_button.clicked.connect(self.decline_selected)
        self.filter.currentIndexChanged.connect(lambda: self.proxy.set_filters(etype=self.filter.currentData()))
        self.search.textChanged.connect(lambda text: self.proxy.set_filters(search=text))
        self.previous.clicked.connect(lambda: self.step_context(-1))
        self.next.clicked.connect(lambda: self.step_context(1))
        self.add_button.clicked.connect(self.add_missed)
        self.back_button.clicked.connect(self.back)
        self.sanitize_button.clicked.connect(self.sanitize)

    # ---- showing the scan

    def enter(self) -> None:
        scan = self.session.scan
        self._committing = False
        self.message.setText("")
        self.filter.setCurrentIndex(0)
        self.search.clear()
        self.model = ReviewTableModel(service.ReviewState(scan), self)
        self.model.refused.connect(self.message.setText)
        self.model.counts_changed.connect(self._counts_changed)
        self.model.dataChanged.connect(self._data_changed)
        self.proxy.setSourceModel(self.model)
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(TEXT, 280)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.heading.setText(wording.REVIEW_COUNT.format(count=len(self.model.state.rows)))
        self._counts_changed(self.model.state.accepted_count, len(self.model.state.rows))
        self._show_row(None)
        self._set_busy(False)

    def forget(self) -> None:
        self.proxy.setSourceModel(None)
        self.model = None
        self.context.setText("")
        self.message.setText("")
        self._occurrences = []

    def _counts_changed(self, accepted: int, total: int) -> None:
        self.sanitize_button.setText(wording.SANITIZE_COUNT.format(n=accepted))
        self.heading.setText(wording.REVIEW_COUNT.format(count=total))

    def _set_busy(self, busy: bool) -> None:
        self._committing = busy
        for button in (self.accept_all_button, self.decline_button, self.add_button, self.back_button, self.sanitize_button):
            button.setEnabled(not busy)
        self.table.setEnabled(not busy)

    # ---- context pane

    def _selected_source_rows(self) -> list[int]:
        rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        return sorted(rows)

    def _selection_changed(self, *_) -> None:
        self.message.setText("")
        current = self.table.selectionModel().currentIndex()
        selected = self.table.selectionModel().selectedRows()
        if len(selected) == 1:
            self._show_row(self.proxy.mapToSource(selected[0]).row())
        elif not selected and not current.isValid():
            self._show_row(None)

    def _data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, *_) -> None:
        if self._source_row is not None and top_left.row() <= self._source_row <= bottom_right.row():
            self._show_row(self._source_row, keep_position=True)

    def _show_row(self, source_row: int | None, keep_position: bool = False) -> None:
        self._source_row = source_row
        if source_row is None:
            self._occurrences = []
            self.where.setText(wording.WHERE_NOTHING)
            self.context.setText("")
            self._update_arrows()
            return
        self.model.mark_seen(source_row)
        self._occurrences = self.model.state.occurrences(source_row)
        self._position = min(self._position, max(len(self._occurrences) - 1, 0)) if keep_position else 0
        self._render_context()

    def step_context(self, direction: int) -> None:
        if self._occurrences:
            self._position = (self._position + direction) % len(self._occurrences)
            self._render_context()

    def _render_context(self) -> None:
        if not self._occurrences:
            self.where.setText(wording.WHERE_NOT_FOUND)
            self.context.setText("")
        else:
            text = self.session.scan.text
            start, end = self._occurrences[self._position]
            before, after = text[max(0, start - CONTEXT_WIDTH) : start], text[end : end + CONTEXT_WIDTH]
            self.where.setText(wording.WHERE_IT_APPEARS.format(n=self._position + 1, m=len(self._occurrences)))
            self.context.setText(
                f"…{html.escape(before)}<b>«{html.escape(text[start:end])}»</b>{html.escape(after)}…"
            )
        self._update_arrows()

    def _update_arrows(self) -> None:
        many = len(self._occurrences) > 1
        self.previous.setEnabled(many)
        self.next.setEnabled(many)

    # ---- buttons

    def decline_selected(self) -> None:
        if self.model:
            self.model.set_selected(self._selected_source_rows(), False)

    def add_missed(self) -> None:
        dialog = AddDialog(self.model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.message.setText("")
            self.model.add(dialog.type.currentData(), dialog.text.text())

    def back(self) -> None:
        if self.model.state.touched or self.model.state.accepted_count != len(self.model.state.rows):
            answer = QMessageBox.question(self, wording.LEAVE_REVIEW_TITLE, wording.LEAVE_REVIEW)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.window_.go("choose")

    def sanitize(self) -> None:
        accepted, declined, reviewed = self.model.state.result()
        if not reviewed:
            box = QMessageBox(QMessageBox.Icon.Warning, wording.UNREVIEWED_TITLE, wording.UNREVIEWED, parent=self)
            yes = box.addButton(wording.UNREVIEWED_BUTTON_YES, QMessageBox.ButtonRole.AcceptRole)
            box.addButton(wording.UNREVIEWED_BUTTON_NO, QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                return
        s = self.session
        self.message.setText(wording.SANITIZING)
        self._set_busy(True)
        self.backend.commit(s.scan, accepted, declined, reviewed, s.matter_path, s.passphrase)

    # ---- background results

    def on_finished(self, job: str, result) -> None:
        if job != "commit":
            return
        self.session.result = result
        if "done" in self.window_.screens:
            self.window_.go("done")
        else:
            self.message.setText(wording.SANITIZED_NO_DONE.format(path=result.output_path))

    def on_failed(self, job: str, message: str) -> None:
        if job == "commit":
            self.message.setText(wording.plain(message))
            self._set_busy(False)
