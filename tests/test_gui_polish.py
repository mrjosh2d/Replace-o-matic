"""Wording, keyboard access and empty states of the window (GUI_PLAN phase 5)."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import sanitizer_core as sc  # noqa: E402
from gui import settings, wording  # noqa: E402
from gui.review_model import TICK  # noqa: E402
from gui.workers import Backend  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from test_gui_screens import (  # noqa: E402,F401  (fixtures and helpers shared with the screen tests)
    LEFT,
    PASSPHRASE,
    case,
    choose,
    model,
    to_review,
    window,
)

FILE_FILTERS = {"MATTER_FILES", "DOCUMENT_FILES", "RESTORE_FILES"}


# ---- wording


def wording_strings():
    for name, value in vars(wording).items():
        if name.isupper() and isinstance(value, str) and name not in FILE_FILTERS:
            yield name, value
        elif name.isupper() and isinstance(value, list):
            for item in value:
                if isinstance(item, str):  # (the pattern table holds tuples: its patterns must say vault)
                    yield name, item


def test_no_jargon_in_any_wording_string():
    for name, text in wording_strings():
        assert "vault" not in text.lower(), name
        assert "(s)" not in text, name
        assert "rehydrate" not in text.lower() and "placeholder" not in text.lower(), name


def test_plurals():
    assert wording.times(1) == "1 time" and wording.times(0) == "0 times" and wording.times(3) == "3 times"
    assert wording.plural(1, "stand-in") == "1 stand-in"


@pytest.mark.parametrize(
    "raised, expected",
    [
        ("Wrong passphrase, or the vault file is damaged.", "Wrong passphrase, or the matter file is damaged. Check"),
        ("/x/a.vault is not an encrypted vault. Refusing to use it.", "not a matter file"),
        ("This vault is encrypted: a passphrase is required.", "needs its passphrase"),
        ("No text found in /x/a.pdf. If it is a scanned PDF, it needs OCR first.", "No text could be read"),
        ("Internal error: round-trip check failed. No output written.", "nothing was written"),
        ("Writing a redacted PDF needs PyMuPDF (pip install pymupdf). Use -o file.txt for text.", "cannot write a PDF"),
        ("Something about the vault we did not foresee", "Something about the matter file we did not foresee"),
    ],
)
def test_for_staff_mapping(raised, expected):
    text = wording.for_staff(raised)
    assert expected in text
    assert "vault" not in text.lower() and "/x/" not in text and "pymupdf" not in text.lower()


def test_wrong_passphrase_reaches_the_screen_in_staff_words(qtbot, window, case):
    doc, matter = case
    sc.save_vault(sc.new_vault(), matter, passphrase=PASSPHRASE)
    screen = choose(qtbot, window, doc, matter, passphrase="not the passphrase")
    qtbot.waitUntil(lambda: "Wrong passphrase" in screen.message.text(), timeout=10000)
    assert "matter file is damaged" in screen.message.text() and "vault" not in screen.message.text()
    assert screen.form.passphrase.hasFocus() or not screen.isActiveWindow()


def test_vault_error_from_the_core_is_routed_too(qtbot, monkeypatch):
    backend = Backend()
    try:

        def boom():
            raise sc.VaultError("Wrong passphrase, or the vault file is damaged.")

        with qtbot.waitSignal(backend.failed, timeout=10000) as signal:
            backend.submit("open_matter", boom)
        assert "matter file" in signal.args[1] and "vault" not in signal.args[1]
    finally:
        assert backend.shutdown()


# ---- keyboard


def test_enter_submits_choose(qtbot, window, case):
    doc, matter = case
    qtbot.mouseClick(window.screens["start"].sanitize_button, LEFT)
    screen = window.screens["choose"]
    screen.document.set_path(doc)
    screen.form.picker.set_path(matter)
    screen.form.passphrase.setText(PASSPHRASE)
    screen.form.again.setText(PASSPHRASE)
    qtbot.keyClick(screen.form.again, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: window.current() is window.screens["review"], timeout=10000)


def test_enter_on_a_start_button_presses_it(qtbot, window):
    start = window.screens["start"]
    start.sanitize_button.setFocus()
    qtbot.keyClick(start.sanitize_button, Qt.Key.Key_Return)
    assert window.current() is window.screens["choose"]


def test_space_ticks_and_unticks_the_selected_rows(qtbot, window, case):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    review.table.selectRow(0)
    review.table.setFocus()
    rows = review.model.state.rows
    source = review.proxy.mapToSource(review.proxy.index(0, 0)).row()
    assert rows[source].accepted
    qtbot.keyClick(review.table, Qt.Key.Key_Space)
    assert not rows[source].accepted
    assert review.proxy.index(0, TICK).data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    qtbot.keyClick(review.table, Qt.Key.Key_Space)
    assert rows[source].accepted


def test_review_shortcuts_and_accessible_names(qtbot, window, case):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    review.table.setFocus()
    review.focus_search()
    assert review.search.hasFocus() or not review.isActiveWindow()
    for widget in (review.table, review.search, review.filter, review.previous_button, review.next_button):
        assert widget.accessibleName()
    assert window.lock_action.shortcut().toString() == "Ctrl+L"
    window.lock_action.trigger()
    assert window.current() is window.screens["start"] and window.session.vault is None


def test_step_context_with_alt_arrows(qtbot, window, case):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    review.table.selectRow(0)
    seen = review.where.text()
    review.step_context(1)
    assert review.where.text() != seen or len(review._spans) < 2


# ---- firm setting


def test_allow_accept_all_false_hides_the_button(qtbot, window, case):
    doc, matter = case
    assert settings.allow_accept_all() is True
    review = to_review(qtbot, window, doc, matter)
    assert review.accept_all_button.isVisible()
    with open(os.path.join(settings.app_folder(), "settings.json"), "w", encoding="utf-8") as fh:
        json.dump({"allow_accept_all": False}, fh)
    assert settings.allow_accept_all() is False
    review.enter()
    assert not review.accept_all_button.isVisible()
    settings.remember_matter(matter)  # saving the recent list keeps the firm's setting
    assert settings.allow_accept_all() is False


# ---- empty state


def test_review_with_no_items_says_so_and_still_continues(qtbot, window, tmp_path, monkeypatch):
    doc = tmp_path / "plain.txt"
    doc.write_text("Nothing to see here, just a few ordinary words.", encoding="utf-8")
    matter = str(tmp_path / "matter.vault")
    review = to_review(qtbot, window, str(doc), matter)
    assert review.model.state.rows == []
    assert review.empty.isVisible() and not review.table.isVisible()
    assert review.count.text() == "0 items found, 0 ticked"
    assert review.add_button.isEnabled() and review.sanitize_button.isEnabled()
    qtbot.mouseClick(review.sanitize_button, LEFT)  # no "unreviewed" question: nothing to review
    qtbot.waitUntil(lambda: window.current() is window.screens["done"], timeout=10000)


def test_scan_of_a_document_without_text_says_why(qtbot, window, tmp_path):
    doc = tmp_path / "blank.txt"
    doc.write_text("   \n", encoding="utf-8")
    screen = choose(qtbot, window, str(doc), str(tmp_path / "matter.vault"))
    qtbot.waitUntil(lambda: window.current() is window.screens["choose"] and bool(screen.message.text()) and screen.message.text() != wording.WORKING, timeout=10000)
    assert "No text could be read" in screen.message.text() and "OCR" in screen.message.text()


def test_drop_area_highlights_while_dragging(qtbot, window):
    qtbot.mouseClick(window.screens["start"].sanitize_button, LEFT)
    area = window.screens["choose"].drop_area
    assert not area.active
    area.set_active(True)
    assert area.active and "highlight" in area.styleSheet()
