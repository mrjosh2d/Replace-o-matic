"""The review table: a Qt table model over ``sanitizer_service.ReviewState``.

All decisions live in the ReviewState; this class only presents them. A change
the service refuses (text not in the document, a duplicate) leaves the cell as
it was and emits ``refused`` with a sentence to show the reviewer.
"""

from __future__ import annotations

import sanitizer_core as sc  # first project import: it sets the offline switches

import sanitizer_service as service
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

from gui import wording

COLUMNS = wording.REVIEW_COLUMNS
TICK, TYPE, TEXT, TIMES, FOUND_BY, SAME_AS = range(6)
TYPE_LABELS = {t: t.replace("_", " ").capitalize() for t in sc.ENTITY_TYPES}  # "Financial id"
TYPE_LABELS.update({"financial_id": "ID number", "url": "Web address"})


class ReviewTableModel(QAbstractTableModel):
    refused = Signal(str)
    counts_changed = Signal(int, int)  # accepted, total

    def __init__(self, state: service.ReviewState, parent=None):
        super().__init__(parent)
        self.state = state

    # ---- shape

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 (Qt name)
        return 0 if parent.isValid() else len(self.state.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == TICK:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        if index.column() in (TYPE, TEXT):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    # ---- cells

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.state.rows[index.row()]
        item, column = row.item, index.column()
        if role == Qt.ItemDataRole.CheckStateRole and column == TICK:
            return Qt.CheckState.Checked if row.accepted else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.EditRole:
            return {TYPE: item.type, TEXT: item.value}.get(column)
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                TYPE: TYPE_LABELS[item.type],
                TEXT: " ".join(item.value.split()),
                TIMES: item.times,
                FOUND_BY: service.SOURCE_LABELS.get(item.source, item.source),
                SAME_AS: " ".join(item.entity_hint.split()),
            }.get(column)
        if role == Qt.ItemDataRole.TextAlignmentRole and column == TIMES:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not index.isValid():
            return False
        row, column = index.row(), index.column()
        problem = None
        if role == Qt.ItemDataRole.CheckStateRole and column == TICK:
            self.state.set_accepted(row, Qt.CheckState(value) == Qt.CheckState.Checked)
        elif role == Qt.ItemDataRole.EditRole and column == TYPE:
            problem = self.state.set_type(row, value)
        elif role == Qt.ItemDataRole.EditRole and column == TEXT:
            problem = self.state.edit_text(row, value)
        else:
            return False
        if problem:
            self.refused.emit(problem)
            return False
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))
        self._count()
        return True

    # ---- actions for the buttons

    def add(self, etype: str, text: str) -> bool:
        problem = self.state.check_add(etype, text)
        if problem:
            self.refused.emit(problem)
            return False
        position = len(self.state.rows)
        self.beginInsertRows(QModelIndex(), position, position)
        self.state.add(etype, text)
        self.endInsertRows()
        self._count()
        return True

    def accept_all(self) -> None:
        self.state.accept_all()
        self._refresh_ticks()

    def set_selected(self, rows: list[int], accepted: bool) -> None:
        for row in rows:
            self.state.set_accepted(row, accepted)
        self._refresh_ticks()

    def mark_seen(self, row: int) -> None:
        self.state.mark_seen(row)

    def _refresh_ticks(self) -> None:
        if self.state.rows:
            self.dataChanged.emit(self.index(0, TICK), self.index(len(self.state.rows) - 1, TICK))
        self._count()

    def _count(self) -> None:
        self.counts_changed.emit(self.state.accepted_count, len(self.state.rows))
