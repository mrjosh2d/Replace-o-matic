"""Review: the table of proposed items, their context, and the Sanitize button.

Every decision is held by ``sanitizer_service.ReviewState`` through
``ReviewTableModel``; this screen only shows it and passes clicks on.
"""

from __future__ import annotations

import sanitizer_core as sc  # first project import: it sets the offline switches

import sanitizer_service as service
from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
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
from gui.screens.common import message_label


def type_combo(parent=None) -> QComboBox:
    combo = QComboBox(parent)
    for etype in sc.ENTITY_TYPES:
        combo.addItem(TYPE_LABELS[etype], etype)
    return combo


class TypeDelegate(QStyledItemDelegate):
    """The Type cell is a drop-down of the known types."""

    def createEditor(self, parent, option, index):  # noqa: N802 (Qt name)
        return type_combo(parent)

    def setEditorData(self, editor, index) -> None:  # noqa: N802
        editor.setCurrentIndex(max(0, editor.findData(index.data(Qt.ItemDataRole.EditRole))))

    def setModelData(self, editor, model, index) -> None:  # noqa: N802
        model.setData(index, editor.currentData(), Qt.ItemDataRole.EditRole)


class ReviewFilter(QSortFilterProxyModel):
    """Sorting, the type filter and the search box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.etype = ""
        self.needle = ""
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_type(self, etype: str) -> None:
        self.etype = etype or ""
        self.invalidate()

    def set_search(self, text: str) -> None:
        self.needle = text.strip().lower()
        self.invalidate()

    def filterAcceptsRow(self, row, parent) -> bool:  # noqa: N802
        item = self.sourceModel().state.rows[row].item
        if self.etype and item.type != self.etype:
            return False
        return self.needle in item.value.lower()

    def lessThan(self, left, right) -> bool:  # noqa: N802
        if left.column() == TICK:
            rows = self.sourceModel().state.rows
            return rows[left.row()].accepted < rows[right.row()].accepted
        return super().lessThan(left, right)


class AddDialog(QDialog):
    """Add something the scan missed: shows the count and first context before confirming."""

    def __init__(self, state: service.ReviewState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle(wording.ADD_TITLE)
        self.text = QLineEdit()
        self.type = type_combo()
        self.preview = message_label()
        self.box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.box.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(wording.ADD)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(wording.ADD_PROMPT))
        layout.addWidget(self.text)
        layout.addWidget(QLabel(wording.ADD_TYPE))
        layout.addWidget(self.type)
        layout.addWidget(self.preview)
        layout.addWidget(self.box)
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        self.text.textChanged.connect(self._check)
        self.type.currentIndexChanged.connect(self._check)
        self.resize(520, 220)
        self._check()

    def value(self) -> tuple[str, str]:
        return self.type.currentData(), self.text.text()

    def _check(self, *_) -> None:
        etype, text = self.value()
        problem = self.state.check_add(etype, text) if text.strip() else ""
        self.ok.setEnabled(problem is None)
        if problem is None:
            found = service.occurrences(self.state.scan.text, text.strip())
            first = service.context(self.state.scan.text, *found[0])
            self.preview.setText(wording.ADD_FOUND.format(count=len(found), context=first))
        else:
            self.preview.setText(problem)


class ReviewScreen(Screen):
    name, step = "review", 3

    def __init__(self, window):
        super().__init__(window)
        self.model: ReviewTableModel | None = None
        self.proxy = ReviewFilter(self)
        self._row = -1  # source row whose context is showing
        self._spans: list[tuple[int, int]] = []
        self._at = 0

        self.count = QLabel("")
        self.accept_all_button = QPushButton(wording.ACCEPT_ALL)
        self.decline_button = QPushButton(wording.DECLINE_SELECTED)
        self.filter = QComboBox()
        self.filter.addItem(wording.ALL_TYPES, "")
        for etype in sc.ENTITY_TYPES:
            self.filter.addItem(TYPE_LABELS[etype], etype)
        self.search = QLineEdit()
        self.search.setPlaceholderText(wording.SEARCH)
        self.search.setClearButtonEnabled(True)
        top = QHBoxLayout()
        top.addWidget(self.count, 1)
        top.addWidget(self.accept_all_button)
        top.addWidget(self.decline_button)
        top.addWidget(QLabel(wording.FILTER))
        top.addWidget(self.filter)
        top.addWidget(self.search)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setItemDelegateForColumn(TYPE, TypeDelegate(self.table))
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)

        self.where = QLabel(wording.WHERE_NONE)
        self.previous_button = QPushButton(wording.PREVIOUS)
        self.next_button = QPushButton(wording.NEXT)
        for button in (self.previous_button, self.next_button):
            button.setFixedWidth(40)
        where_row = QHBoxLayout()
        where_row.addWidget(self.where, 1)
        where_row.addWidget(self.previous_button)
        where_row.addWidget(self.next_button)
        self.context = message_label()
        self.context.setMinimumHeight(48)
        self.notes = message_label()  # scan warnings and what is already known
        self.message = message_label()

        self.add_button = QPushButton(wording.ADD_MISSED)
        self.back_button = QPushButton(wording.BACK)
        self.sanitize_button = QPushButton("")
        self.sanitize_button.setDefault(True)
        self.sanitize_button.setMinimumWidth(150)
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
        layout.addWidget(self.notes)
        layout.addWidget(self.message)
        layout.addLayout(bottom)

        self.table.selectionModel().currentRowChanged.connect(self._current_changed)
        self.accept_all_button.clicked.connect(self.accept_all)
        self.decline_button.clicked.connect(self.decline_selected)
        self.filter.currentIndexChanged.connect(lambda _: self.proxy.set_type(self.filter.currentData()))
        self.search.textChanged.connect(self.proxy.set_search)
        self.previous_button.clicked.connect(lambda: self.step_context(-1))
        self.next_button.clicked.connect(lambda: self.step_context(1))
        self.add_button.clicked.connect(self.add_item)
        self.back_button.clicked.connect(lambda: self.window_.go("choose"))
        self.sanitize_button.clicked.connect(self.sanitize)

    # ---- set-up

    def enter(self) -> None:
        scan = self.session.scan
        if self.model is None or self.model.state.scan is not scan:
            self.model = ReviewTableModel(service.ReviewState(scan), self)
            self.model.refused.connect(self.message.setText)
            self.model.counts_changed.connect(self._show_counts)
            self.model.dataChanged.connect(self._row_changed)
            self.proxy.setSourceModel(self.model)
            self.proxy.sort(-1)
            self.table.resizeColumnsToContents()
            self.table.horizontalHeader().setSectionResizeMode(TEXT, QHeaderView.ResizeMode.Stretch)
            self.filter.setCurrentIndex(0)
            self.search.clear()
            notes = list(scan.warnings)
            if scan.already_known:
                notes.append(wording.REVIEW_KNOWN.format(count=scan.already_known))
            self.notes.setText("\n".join(notes))
            self.notes.setVisible(bool(notes))
            self._show_context(-1)
        self.message.setText("")
        self._set_busy(False)
        self._show_counts(self.model.state.accepted_count, len(self.model.state.rows))

    def forget(self) -> None:
        self.proxy.setSourceModel(None)
        self.model = None
        self._row, self._spans = -1, []
        for label in (self.context, self.notes, self.message):
            label.setText("")

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.sanitize_button, self.back_button, self.add_button, self.table,
                       self.accept_all_button, self.decline_button):  # fmt: skip
            widget.setEnabled(not busy)

    def _show_counts(self, accepted: int, total: int) -> None:
        self.count.setText(wording.REVIEW_COUNT.format(total=total, accepted=accepted))
        self.sanitize_button.setText(wording.SANITIZE_N.format(count=accepted))

    # ---- context pane

    def _current_changed(self, current, _previous) -> None:
        if current.isValid():
            self.message.setText("")
            self._show_context(self.proxy.mapToSource(current).row())

    def _row_changed(self, first, last, *_) -> None:
        if first.row() <= self._row <= last.row() and first.column() <= TEXT <= last.column():
            self._show_context(self._row, seen=False)  # its text may have been edited

    def _show_context(self, row: int, seen: bool = True) -> None:
        self._row, self._at = row, 0
        self._spans = self.model.state.occurrences(row) if row >= 0 else []
        if row >= 0 and seen:
            self.model.mark_seen(row)
        self._paint_context()

    def step_context(self, by: int) -> None:
        if self._spans:
            self._at = (self._at + by) % len(self._spans)
            self._paint_context()

    def _paint_context(self) -> None:
        many = len(self._spans) > 1
        self.previous_button.setEnabled(many)
        self.next_button.setEnabled(many)
        if self._row < 0:
            self.where.setText(wording.WHERE_NONE)
            self.context.setText("")
        elif not self._spans:
            self.where.setText(wording.WHERE_NOT_FOUND)
            self.context.setText("")
        else:
            self.where.setText(wording.WHERE.format(index=self._at + 1, total=len(self._spans)))
            self.context.setText(service.context(self.model.state.scan.text, *self._spans[self._at], 90))

    # ---- buttons

    def selected_rows(self) -> list[int]:
        return sorted({self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()})

    def accept_all(self) -> None:
        self.model.accept_all()

    def decline_selected(self) -> None:
        self.model.set_selected(self.selected_rows(), False)

    def add_item(self) -> None:
        dialog = AddDialog(self.model.state, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.model.add(*dialog.value())

    def sanitize(self) -> None:
        accepted, declined, reviewed = self.model.state.result()
        if not reviewed:
            answer = QMessageBox.question(self, wording.UNREVIEWED_TITLE, wording.UNREVIEWED)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._set_busy(True)
        self.message.setText(wording.WORKING)
        session = self.session
        self.backend.commit(session.scan, accepted, declined, reviewed, session.matter_path, session.passphrase)

    def on_finished(self, job: str, result) -> None:
        if job == "commit":
            self.session.result = result
            self.session.vault = result.vault
            self.window_.go("done")

    def on_failed(self, job: str, message: str) -> None:
        if job == "commit":
            self._set_busy(False)
            self.message.setText(message)
