"""Choosing where files are saved, the key's file type, and the first-run walkthrough."""

import json
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import sanitizer_service as service  # noqa: E402
from gui import intro, settings, wording  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402
from test_gui_screens import (  # noqa: E402,F401  (fixtures and helpers shared with the screen tests)
    LEFT,
    PASSPHRASE,
    case,
    model,
    sanitized_case,
    to_done,
    to_review,
    window,
)


def pick(monkeypatch, path, chosen_filter=""):
    """Make the Save dialog return ``path``; the list collects what it was asked."""
    asked = []

    def fake(parent, caption, start, filters, initial=""):
        asked.append((start, filters))
        return path, chosen_filter

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake)
    return asked


# ---- Review

def reviewed_done(qtbot, window):
    """Look at one row, so Sanitize does not ask about an unreviewed list, then sanitize."""
    window.screens["review"].table.selectRow(0)
    return to_done(qtbot, window)


def test_review_shows_and_uses_the_default_output_path(qtbot, window, case):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    expected = service.default_output_path(doc, "sanitized")
    assert review.output.path_label.text() == expected
    result = reviewed_done(qtbot, window)
    assert result.output_path == expected and os.path.exists(expected)


def test_review_custom_output_path(qtbot, window, case, monkeypatch):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    custom = os.path.join(os.path.dirname(doc), "for-analysis.txt")
    asked = pick(monkeypatch, custom)
    qtbot.mouseClick(review.output.button, LEFT)
    assert asked[0][0] == service.default_output_path(doc, "sanitized")
    assert asked[0][1] == wording.OUTPUT_FILTERS[".txt"]
    assert review.output.path_label.text() == custom
    result = reviewed_done(qtbot, window)
    assert result.output_path == custom and os.path.exists(custom)
    assert not os.path.exists(service.default_output_path(doc, "sanitized"))
    assert custom in window.screens["done"].summary.text()


def test_review_name_without_extension_gets_the_default_one(qtbot, window, case, monkeypatch):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    pick(monkeypatch, os.path.join(os.path.dirname(doc), "bare"), wording.OUTPUT_FILTERS[".txt"])
    qtbot.mouseClick(review.output.button, LEFT)
    assert review.output.path() == os.path.join(os.path.dirname(doc), "bare.txt")


def test_review_refuses_the_original_document_and_writes_nothing(qtbot, window, case, monkeypatch):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    before = review.output.path()
    pick(monkeypatch, doc)
    qtbot.mouseClick(review.output.button, LEFT)
    assert review.output.path() == before  # the old path is kept
    shown = review.output.problem.text()
    assert shown and "vault" not in shown.lower()
    assert "original document" in shown
    assert os.listdir(os.path.dirname(doc)) == ["case.txt"] and not window.backend.busy


def test_review_refuses_the_matter_file_in_staff_words(qtbot, window, case, monkeypatch):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    pick(monkeypatch, matter)
    qtbot.mouseClick(review.output.button, LEFT)
    assert "matter file" in review.output.problem.text() and "vault" not in review.output.problem.text().lower()
    assert review.output.path() == service.default_output_path(doc, "sanitized")


def test_review_output_resets_each_time_the_screen_is_entered(qtbot, window, case, monkeypatch):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    pick(monkeypatch, os.path.join(os.path.dirname(doc), "other.txt"))
    qtbot.mouseClick(review.output.button, LEFT)
    window.go("review")
    assert review.output.path_label.text() == service.default_output_path(doc, "sanitized")


# ---- Restore

def test_restore_custom_output(qtbot, window, tmp_path, monkeypatch):
    safe_path, matter = sanitized_case(tmp_path)
    came_back = tmp_path / "analysis.txt"
    came_back.write_text(open(safe_path, encoding="utf-8").read(), encoding="utf-8")
    qtbot.mouseClick(window.screens["start"].restore_button, LEFT)
    restore = window.screens["restore"]
    assert not restore.output.isVisible()  # nothing chosen yet
    restore.document.set_path(str(came_back))
    assert restore.output.isVisible()
    assert restore.output.path_label.text() == service.default_output_path(str(came_back), "rehydrated")

    custom = str(tmp_path / "restored.txt")
    pick(monkeypatch, custom)
    qtbot.mouseClick(restore.output.button, LEFT)
    restore.document.set_path(str(came_back) + "")  # same document: the choice stays
    other = tmp_path / "second.txt"
    other.write_text("x", encoding="utf-8")
    restore.document.set_path(str(other))
    assert restore.output.path() == custom  # picked once, kept when the document changes
    restore.document.set_path(str(came_back))

    restore.form.picker.set_path(matter)
    restore.form.passphrase.setText(PASSPHRASE)
    qtbot.mouseClick(restore.go_button, LEFT)
    qtbot.waitUntil(lambda: "restored" in restore.message.text(), timeout=10000)
    assert os.path.exists(custom) and custom in restore.message.text()
    assert not os.path.exists(tmp_path / "analysis.rehydrated.txt")
    assert "John A. Smith" in open(custom, encoding="utf-8").read()


def test_restore_refuses_the_file_that_came_back_as_output(qtbot, window, tmp_path, monkeypatch):
    safe_path, matter = sanitized_case(tmp_path)
    qtbot.mouseClick(window.screens["start"].restore_button, LEFT)
    restore = window.screens["restore"]
    restore.document.set_path(safe_path)
    before = open(safe_path, encoding="utf-8").read()
    pick(monkeypatch, safe_path)
    qtbot.mouseClick(restore.output.button, LEFT)
    assert "original document" in restore.output.problem.text()
    assert restore.output.path() == service.default_output_path(safe_path, "rehydrated")
    assert open(safe_path, encoding="utf-8").read() == before



def test_restore_refuses_the_matter_file_as_output(qtbot, window, tmp_path, monkeypatch):
    safe_path, matter = sanitized_case(tmp_path)
    qtbot.mouseClick(window.screens["start"].restore_button, LEFT)
    restore = window.screens["restore"]
    restore.document.set_path(safe_path)
    restore.form.picker.set_path(matter)
    restore.form.passphrase.setText(PASSPHRASE)
    pick(monkeypatch, matter)
    qtbot.mouseClick(restore.output.button, LEFT)
    before = open(matter, "rb").read()
    qtbot.mouseClick(restore.go_button, LEFT)
    assert "matter file" in restore.output.problem.text() and not window.backend.busy
    assert open(matter, "rb").read() == before

# ---- Key

def test_key_format_csv_is_written_and_remembered(qtbot, window, tmp_path, monkeypatch):
    safe_path, matter = sanitized_case(tmp_path)
    qtbot.mouseClick(window.screens["start"].key_button, LEFT)
    key = window.screens["key"]
    assert key.format.currentData() == "docx"
    key.form.picker.set_path(matter)
    key.form.passphrase.setText(PASSPHRASE)
    key.safe.setChecked(False)
    key.format.setCurrentIndex(key.format.findData("csv"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    qtbot.mouseClick(key.go_button, LEFT)
    qtbot.waitUntil(lambda: "Confidential key:" in key.message.text(), timeout=10000)
    written = re.search(r"Confidential key: (.+)", key.message.text()).group(1).strip()
    assert written.endswith(".csv") and os.path.exists(written)
    assert settings.key_format() == "csv"
    window.go("key")
    assert key.format.currentData() == "csv"


def test_key_format_setting_keeps_other_settings_and_rejects_junk(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLACE_O_MATIC_HOME", str(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({"allow_accept_all": False}), encoding="utf-8")
    assert settings.key_format() == "docx"
    settings.set_key_format("txt")
    settings.set_key_format("exe")  # ignored
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data == {"allow_accept_all": False, "key_format": "txt"}
    assert settings.key_format() == "txt"


# ---- First-run walkthrough

def test_intro_shows_on_first_run_only(qtbot, window):
    assert not settings.intro_seen()
    dialog = intro.show_if_first_run(window)
    assert dialog is not None and dialog.isVisible()
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)  # Esc closes it
    assert not dialog.isVisible() and settings.intro_seen()
    assert intro.show_if_first_run(window) is None


def test_help_menu_reopens_the_walkthrough_and_finishing_sets_the_flag(qtbot, window):
    settings.set_intro_seen(True)
    assert intro.show_if_first_run(window) is None
    assert wording.HELP_MENU in [a.text() for a in window.menuBar().actions()]
    window.help_action.trigger()
    dialog = window._intro
    assert dialog.isVisible() and dialog.indicator.text() == "1 of 4"
    for _ in range(3):
        qtbot.mouseClick(dialog.next_button, LEFT)
    qtbot.mouseClick(dialog.finish_button, LEFT)
    assert not dialog.isVisible()


def test_finish_sets_intro_seen(qtbot, window):
    dialog = intro.show_if_first_run(window)
    for _ in range(3):
        qtbot.keyClick(dialog, Qt.Key.Key_Return)  # Enter is Next
    assert dialog.page() == 3 and dialog.finish_button.isVisible() and not dialog.next_button.isVisible()
    assert not settings.intro_seen()
    qtbot.keyClick(dialog, Qt.Key.Key_Return)  # and Finish on the last page
    assert not dialog.isVisible() and settings.intro_seen()


def test_intro_navigation(qtbot, window):
    dialog = intro.open_intro(window)
    assert dialog.page() == 0 and not dialog.back_button.isEnabled()
    assert dialog.next_button.isVisible() and not dialog.finish_button.isVisible()
    qtbot.mouseClick(dialog.next_button, LEFT)
    assert dialog.page() == 1 and dialog.indicator.text() == "2 of 4" and dialog.back_button.isEnabled()
    qtbot.mouseClick(dialog.back_button, LEFT)
    assert dialog.page() == 0 and dialog.indicator.text() == "1 of 4"
    assert len(wording.INTRO_PAGES) == 4
    dialog.close()
    assert settings.intro_seen()  # closing counts as done


# ---- wording

def test_new_strings_use_staff_words():
    banned = re.compile(r"vault|rehydrat|\bNER\b|regex|threshold|placeholder", re.IGNORECASE)
    names = ("OUTPUT_", "CHANGE", "KEY_FORMAT", "HELP_", "INTRO_")
    for name, value in vars(wording).items():
        if not name.startswith(names):
            continue
        pieces = value.values() if isinstance(value, dict) else value if isinstance(value, list) else [value]
        for piece in pieces:
            for text in piece if isinstance(piece, tuple) else [piece]:
                assert not banned.search(text), name


# ---- a file that is already there

def answer_replace(monkeypatch, answer):
    """Make the "already exists" question return ``answer``; the list collects what it showed."""
    from gui.screens import common

    asked = []

    def fake(parent, existing, successors):
        asked.append((existing, successors))
        return answer

    monkeypatch.setattr(common, "ask_replace", fake)
    return asked


@pytest.mark.parametrize("answer", ["new", "replace", "cancel"])
def test_review_asks_before_replacing_an_existing_output(qtbot, window, case, monkeypatch, answer):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    default = service.default_output_path(doc, "sanitized")
    with open(default, "w", encoding="utf-8") as fh:
        fh.write("earlier result")
    asked = answer_replace(monkeypatch, answer)
    review.table.selectRow(0)
    qtbot.mouseClick(review.sanitize_button, LEFT)
    successor = service.successor_path(default)
    assert asked == [([default], [successor])]
    if answer == "cancel":
        assert window.current().name == "review" and not window.backend.busy
        assert not os.path.exists(matter) and open(default, encoding="utf-8").read() == "earlier result"
        return
    qtbot.waitUntil(lambda: window.current().name == "done", timeout=10000)
    result = window.session.result
    if answer == "new":
        assert result.output_path == successor and open(default, encoding="utf-8").read() == "earlier result"
    else:
        assert result.output_path == default and "John A. Smith" not in open(default, encoding="utf-8").read()


def test_review_does_not_ask_when_the_name_was_picked_in_the_save_dialog(qtbot, window, case, monkeypatch):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    custom = os.path.join(os.path.dirname(doc), "picked.txt")
    with open(custom, "w", encoding="utf-8") as fh:
        fh.write("old")
    pick(monkeypatch, custom)
    qtbot.mouseClick(review.output.button, LEFT)
    asked = answer_replace(monkeypatch, "cancel")
    result = reviewed_done(qtbot, window)
    assert asked == [] and result.output_path == custom  # the Save dialog already asked


def test_key_saves_a_new_file_beside_an_existing_key(qtbot, window, tmp_path, monkeypatch):
    safe_path, matter = sanitized_case(tmp_path)
    qtbot.mouseClick(window.screens["start"].key_button, LEFT)
    key = window.screens["key"]
    key.document.set_path("")
    key.form.picker.set_path(matter)
    key.form.passphrase.setText(PASSPHRASE)
    key.format.setCurrentIndex(key.format.findData("txt"))
    key.safe.setChecked(True)
    confidential, safe = service.key_paths(None, matter, "txt")
    with open(confidential, "w", encoding="utf-8") as fh:
        fh.write("earlier key")
    successor = service.successor_path(confidential)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    asked = answer_replace(monkeypatch, "new")
    qtbot.mouseClick(key.go_button, LEFT)
    qtbot.waitUntil(lambda: "Confidential key:" in key.message.text(), timeout=10000)
    assert asked == [([confidential], [successor])]  # only the one that exists
    assert open(confidential, encoding="utf-8").read() == "earlier key"
    assert os.path.exists(successor) and os.path.exists(safe)


def test_restore_cancel_on_existing_output_writes_nothing(qtbot, window, tmp_path, monkeypatch):
    safe_path, matter = sanitized_case(tmp_path)
    qtbot.mouseClick(window.screens["start"].restore_button, LEFT)
    restore = window.screens["restore"]
    restore.document.set_path(safe_path)
    default = service.default_output_path(safe_path, "rehydrated")
    with open(default, "w", encoding="utf-8") as fh:
        fh.write("earlier")
    restore.form.picker.set_path(matter)
    restore.form.passphrase.setText(PASSPHRASE)
    asked = answer_replace(monkeypatch, "cancel")
    qtbot.mouseClick(restore.go_button, LEFT)
    qtbot.waitUntil(lambda: bool(asked), timeout=10000)
    qtbot.waitUntil(lambda: not window.backend.busy, timeout=10000)
    assert open(default, encoding="utf-8").read() == "earlier" and restore.go_button.isEnabled()
