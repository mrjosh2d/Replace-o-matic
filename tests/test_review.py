"""Review decisions (no Qt), and the Qt table model over them."""

import os
import re

import pytest

import sanitizer_core as sc
import sanitizer_service as service
from sanitizer_core import Detection

TEXT = (
    "John A. Smith sued Acme Corporation. Smith's SSN is 123-45-6789. "
    "The American Arbitration Association heard it. Gerry testified for Acme."
)
PASSPHRASE = "correct horse battery"


@pytest.fixture
def state(tmp_path, monkeypatch):
    def detector(text):
        names = {"John A. Smith": "person", "Acme Corporation": "company", "American Arbitration Association": "company"}
        return [Detection(m.start(), m.end(), t) for n, t in names.items() for m in re.finditer(re.escape(n), text)]

    monkeypatch.setattr(sc, "_default_detector", detector)
    doc = tmp_path / "case.txt"
    doc.write_text(TEXT)
    scan = service.scan_document(str(doc), sc.new_vault())
    review = service.ReviewState(scan)
    review.vault_path = str(tmp_path / "matter.vault")
    return review


def index_of(state, value):
    return [r.item.value for r in state.rows].index(value)


def test_accept_all_untouched_is_unreviewed(state):
    state.accept_all()
    accepted, declined, reviewed = state.result()
    assert len(accepted) == len(state.rows) and declined == [] and reviewed is False
    state.mark_seen(0)
    assert state.result()[2] is True


def test_untick_edit_retype_and_add(state):
    state.set_accepted(index_of(state, "American Arbitration Association"), False)
    assert state.set_type(index_of(state, "Acme"), "company") is None
    assert state.set_type(0, "martian") is not None

    row = index_of(state, "John A. Smith")
    assert "does not appear" in state.edit_text(row, "Jon Smith")
    assert "already" in state.edit_text(row, "Acme")
    assert state.edit_text(row, " John A. Smith sued ") is None
    assert state.rows[row].item.source == "manual" and state.rows[row].item.times == 1

    assert "does not appear" in state.add("person", "Nobody Here")
    assert "already" in state.add("person", "Smith")
    assert state.add("person", " Gerry ") is None and state.rows[-1].item.value == "Gerry"

    accepted, declined, reviewed = state.result()
    assert reviewed and declined == ["American Arbitration Association"]
    values = [i.value for i in accepted]
    assert "John A. Smith sued" in values and "Gerry" in values and "John A. Smith" not in values

    result = service.commit(state.scan, accepted, declined, reviewed, state.vault_path, PASSPHRASE)
    safe = open(result.output_path).read()
    assert "Smith" not in safe and "Gerry" not in safe and "American Arbitration Association" in safe
    assert sc.rehydrate_text(safe, result.vault) == TEXT


def test_added_then_unticked_row_is_dropped_not_remembered(state):
    state.add("person", "Gerry")
    state.set_accepted(len(state.rows) - 1, False)
    accepted, declined, _ = state.result()
    assert "Gerry" not in [i.value for i in accepted] and declined == []


def test_edited_then_unticked_row_declines_what_the_scan_proposed(state):
    row = index_of(state, "Acme Corporation")
    state.edit_text(row, "Acme Corporation. Smith's")
    state.set_accepted(row, False)
    assert state.result()[1] == ["Acme Corporation"]


def test_value_already_in_the_matter_cannot_be_added(state):
    accepted, declined, reviewed = state.result()
    result = service.commit(state.scan, accepted, declined, True, state.vault_path, PASSPHRASE)
    again = service.ReviewState(service.scan_document(state.scan.path, result.vault))
    assert again.rows == [] and "already" in again.add("person", "Smith")


# ---------------------------------------------------------------- Qt table model

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def model(state):
    pytest.importorskip("PySide6")
    pytest.importorskip("pytestqt")
    from gui.review_model import ReviewTableModel

    return ReviewTableModel(state)


def test_table_shows_rows_and_edits_go_through_the_state(model, qtbot, qtmodeltester):
    from gui import review_model as rm
    from PySide6.QtCore import Qt

    qtmodeltester.check(model)  # Qt's own consistency checks
    state = model.state
    row = index_of(state, "Smith")
    assert model.data(model.index(row, rm.TEXT)) == "Smith"
    assert model.data(model.index(row, rm.TYPE)) == "Person"
    assert model.data(model.index(row, rm.FOUND_BY)) == "short form"
    assert model.data(model.index(row, rm.SAME_AS)) == "John A. Smith"
    assert model.data(model.index(row, rm.TICK), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert model.data(model.index(index_of(state, "123-45-6789"), rm.TYPE)) == "ID number"

    with qtbot.waitSignal(model.counts_changed) as signal:
        assert model.setData(model.index(row, rm.TICK), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert signal.args == [len(state.rows) - 1, len(state.rows)] and not state.rows[row].accepted

    with qtbot.waitSignal(model.refused) as signal:
        assert not model.setData(model.index(row, rm.TEXT), "Nobody Here", Qt.ItemDataRole.EditRole)
    assert "does not appear" in signal.args[0] and state.rows[row].item.value == "Smith"

    assert model.setData(model.index(row, rm.TYPE), "company", Qt.ItemDataRole.EditRole)
    assert state.rows[row].item.type == "company"


def test_table_add_accept_all_and_bulk_untick(model, qtbot, qtmodeltester):
    state = model.state
    before = model.rowCount()
    with qtbot.waitSignal(model.refused):
        assert not model.add("person", "Nobody Here")
    assert model.rowCount() == before
    with qtbot.waitSignal(model.rowsInserted):
        assert model.add("person", "Gerry")
    assert model.rowCount() == before + 1

    model.set_selected([0, 1], False)
    assert state.accepted_count == before - 1
    model.accept_all()
    assert state.accepted_count == before + 1
    qtmodeltester.check(model)
