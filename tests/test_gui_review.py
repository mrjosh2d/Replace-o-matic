"""The Review screen, driven headless with a stub model and invented data."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import sanitizer_core as sc  # noqa: E402
import sanitizer_service as service  # noqa: E402
from gui import wording  # noqa: E402
from gui.review_model import TEXT, TICK, TYPE  # noqa: E402
from gui.screens.review import AddDialog  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

# Reuse the fixtures of the screen tests (model stub, window, settings isolation, case).
from tests.test_gui_screens import (  # noqa: E402,F401
    PASSPHRASE,
    case,
    collect_garbage,
    fill,
    model,
    settings_file,
    window,
)


def open_review(qtbot, window, case):
    doc, matter = case
    window.go("choose")
    choose = fill(window, doc, matter)
    choose.new.setChecked(True)
    choose.submit()
    qtbot.waitUntil(lambda: window.current().name == "review", timeout=10000)
    return window.screens["review"]


def row_of(review, value):
    """Proxy row showing ``value``, or None if it is filtered out."""
    for row in range(review.proxy.rowCount()):
        if review.proxy.index(row, TEXT).data(Qt.ItemDataRole.EditRole) == value:
            return row
    return None


def source_row(review, value):
    return [r.item.value for r in review.model.state.rows].index(value)


def finish(qtbot, review, window):
    review.sanitize_button.click()
    qtbot.waitUntil(lambda: window.session.result is not None or "Internal" in review.message.text() or review.sanitize_button.isEnabled(), timeout=10000)


def test_main_path_writes_output_and_matter_without_the_names(qtbot, window, model, case):
    doc, matter = case
    review = open_review(qtbot, window, case)
    assert review.model.rowCount() >= 2
    review.table.selectRow(row_of(review, "John A. Smith"))  # open one row: counts as reviewed
    review.sanitize_button.click()
    qtbot.waitUntil(lambda: window.session.result is not None, timeout=10000)
    result = window.session.result
    assert "Sanitized" in os.path.basename(result.output_path) or result.output_path != doc
    out = open(result.output_path).read()
    assert "John A. Smith" not in out and "Acme Corporation" not in out
    assert os.path.exists(matter)
    vault = sc.load_vault(matter, PASSPHRASE)
    assert {e["value"] for e in vault["mappings"].values()} >= {"John A. Smith", "Acme Corporation"}
    assert review.message.text().endswith(result.output_path)  # no Done screen yet


def test_unticked_rows_become_declines_in_the_matter(qtbot, window, model, case):
    doc, matter = case
    review = open_review(qtbot, window, case)
    review.model.setData(review.model.index(source_row(review, "Acme Corporation"), TICK), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    review.sanitize_button.click()
    qtbot.waitUntil(lambda: window.session.result is not None, timeout=10000)
    vault = sc.load_vault(matter, PASSPHRASE)
    assert "Acme Corporation" in vault["declined"]
    assert "Acme Corporation" in open(window.session.result.output_path).read()


def test_editing_to_text_not_in_the_document_is_refused_and_shown(qtbot, window, model, case):
    review = open_review(qtbot, window, case)
    row = row_of(review, "Acme Corporation")
    assert review.proxy.setData(review.proxy.index(row, TEXT), "Nowhere Ltd", Qt.ItemDataRole.EditRole) is False
    assert "does not appear" in review.message.text()
    assert review.model.state.rows[source_row(review, "Acme Corporation")].item.value == "Acme Corporation"


def test_add_missed_flow(qtbot, window, model, case):
    review = open_review(qtbot, window, case)
    before = review.model.rowCount()
    dialog = AddDialog(review.model)
    qtbot.addWidget(dialog)
    assert not dialog.ok.isEnabled()
    dialog.text.setText("Nowhere Ltd")
    assert not dialog.ok.isEnabled() and "does not appear" in dialog.info.text()
    dialog.text.setText("Filler")
    assert dialog.ok.isEnabled() and "Appears 40 times" in dialog.info.text() and "«Filler»" in dialog.info.text()
    dialog.type.setCurrentIndex(dialog.type.findData("company"))
    assert review.model.add(dialog.type.currentData(), dialog.text.text())
    assert review.model.rowCount() == before + 1
    assert review.model.state.rows[-1].item.type == "company"
    dialog.update_info()  # "Filler" is now already in the list
    assert not dialog.ok.isEnabled()


def test_filter_and_search_map_proxy_rows_to_the_right_item(qtbot, window, model, case):
    review = open_review(qtbot, window, case)
    review.model.add("person", "Filler")
    review.filter.setCurrentIndex(review.filter.findData("company"))
    assert review.proxy.rowCount() == 1 and row_of(review, "Acme Corporation") == 0
    index = review.proxy.index(0, TICK)
    assert review.proxy.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    ticked = {r.item.value: r.accepted for r in review.model.state.rows}
    assert ticked["Acme Corporation"] is False and ticked["John A. Smith"] is True and ticked["Filler"] is True
    review.filter.setCurrentIndex(0)
    review.search.setText("john")
    assert review.proxy.rowCount() == 1 and row_of(review, "John A. Smith") == 0
    review.table.selectRow(0)
    review.decline_button.click()
    assert review.model.state.rows[source_row(review, "John A. Smith")].accepted is False
    assert review.model.state.rows[source_row(review, "Filler")].accepted is True


def test_context_pane_steps_through_every_occurrence_and_marks_seen(qtbot, window, model, case):
    review = open_review(qtbot, window, case)
    assert review.model.state.touched is False  # entering opens nothing
    review.table.selectRow(row_of(review, "John A. Smith"))
    assert review.model.state.touched is True
    assert "1 of 1" in review.where.text() and not review.next.isEnabled()
    review.model.add("person", "Filler")
    review.table.selectRow(row_of(review, "Filler"))
    assert "1 of 40" in review.where.text() and review.next.isEnabled()
    review.next.click()
    assert "2 of 40" in review.where.text()
    review.previous.click()
    review.previous.click()
    assert "40 of 40" in review.where.text()
    assert "<b>«Filler»</b>" in review.context.text()


def test_context_text_is_escaped(qtbot, window, model, case, tmp_path):
    review = open_review(qtbot, window, case)
    review.session.scan.text = review.session.scan.text.replace("Smith won", "<b>x</b> Smith won")
    review.table.selectRow(row_of(review, "Smith"))  # the short form the scan proposes
    assert "2" in review.where.text().split("of")[1]
    review.next.click()
    assert "&lt;b&gt;x&lt;/b&gt;" in review.context.text()


def test_accept_all_then_sanitize_asks_and_no_writes_nothing(qtbot, window, model, case, monkeypatch):
    doc, matter = case
    review = open_review(qtbot, window, case)
    review.accept_all_button.click()
    asked = []

    def exec_no(box):
        asked.append(box.text())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_no)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: None)
    review.sanitize_button.click()
    assert asked == [wording.UNREVIEWED]
    assert window.session.result is None and not os.path.exists(matter)
    assert sorted(os.listdir(os.path.dirname(doc))) == ["case.txt"]

    # "Continue anyway" writes, and marks the entries as not reviewed.
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box.buttons()[0])
    review.sanitize_button.click()
    qtbot.waitUntil(lambda: window.session.result is not None, timeout=10000)
    assert window.session.result.reviewed is False
    assert all(e["reviewed"] is False for e in sc.load_vault(matter, PASSPHRASE)["mappings"].values())


def test_commit_failure_shows_a_message_and_writes_nothing(qtbot, window, model, case, monkeypatch):
    doc, matter = case

    def fail(*args, **kwargs):
        raise service.ServiceError("Could not save the vault file. Check the folder.")

    monkeypatch.setattr(service, "commit", fail)
    review = open_review(qtbot, window, case)
    review.table.selectRow(0)
    review.sanitize_button.click()
    qtbot.waitUntil(lambda: "matter file" in review.message.text(), timeout=10000)
    assert "vault" not in review.message.text().lower()
    assert review.sanitize_button.isEnabled() and window.session.result is None
    assert not os.path.exists(matter) and sorted(os.listdir(os.path.dirname(doc))) == ["case.txt"]


def test_back_confirms_when_something_changed(qtbot, window, model, case, monkeypatch):
    review = open_review(qtbot, window, case)
    review.back_button.click()  # nothing changed: no question
    assert window.current().name == "choose"
    review = open_review(qtbot, window, case)
    review.table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    review.back_button.click()
    assert window.current().name == "review"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    review.back_button.click()
    assert window.current().name == "choose"
