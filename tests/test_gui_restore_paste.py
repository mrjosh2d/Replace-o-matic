"""The Restore screen's paste box and drag and drop."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from gui import wording  # noqa: E402
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402
from test_gui_screens import (  # noqa: E402,F401  (fixtures and helpers shared with the screen tests)
    LEFT,
    PASSPHRASE,
    TEXT,
    model,
    sanitized_case,
    snap,
    window,
)
from gui.screens.restore import FILE_TAB, PASTE_TAB  # noqa: E402


def open_restore(qtbot, window, matter):
    qtbot.mouseClick(window.screens["start"].restore_button, LEFT)
    restore = window.screens["restore"]
    restore.form.picker.set_path(matter)
    restore.form.passphrase.setText(PASSPHRASE)
    return restore


def paste_and_restore(qtbot, restore, text):
    restore.tabs.setCurrentIndex(PASTE_TAB)
    restore.paste.setPlainText(text)
    qtbot.mouseClick(restore.go_button, LEFT)
    qtbot.waitUntil(restore.showing_result, timeout=10000)


def drop(screen, mime):
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)  # fmt: skip
    screen.dropEvent(event)
    return event


def test_paste_restores_in_the_window_and_writes_nothing(qtbot, window, tmp_path):
    safe_path, matter = sanitized_case(tmp_path)
    safe = open(safe_path, encoding="utf-8").read()
    before = sorted(os.listdir(tmp_path))
    restore = open_restore(qtbot, window, matter)

    paste_and_restore(qtbot, restore, safe.replace("[PERSON_1]", "[Person 1]", 1) + " See [COMPANY_99].")
    snap(window, "6b-restore-pasted")
    assert restore.result.toPlainText() == TEXT + " See [COMPANY_99]."
    assert restore.result.isReadOnly() and restore.paste.toPlainText() == ""
    message = restore.message.text()
    assert "restored" in message and "[Person 1]" in message and "[COMPANY_99]" in message
    assert not restore.go_button.isEnabled()  # nothing left to restore until Paste another
    assert sorted(os.listdir(tmp_path)) == before

    qtbot.mouseClick(restore.copy_button, LEFT)
    assert QApplication.clipboard().text() == restore.result.toPlainText()
    assert restore.message.text().startswith(wording.RESTORE_COPIED)

    qtbot.mouseClick(restore.again_button, LEFT)
    assert not restore.showing_result() and restore.result.toPlainText() == ""
    assert restore.go_button.isEnabled() and restore.message.text() == ""


def test_paste_round_trip_is_exact(qtbot, window, tmp_path):
    safe_path, matter = sanitized_case(tmp_path)
    restore = open_restore(qtbot, window, matter)
    paste_and_restore(qtbot, restore, open(safe_path, encoding="utf-8").read())
    assert restore.result.toPlainText() == TEXT


def test_empty_paste_asks_for_text(qtbot, window, tmp_path):
    _, matter = sanitized_case(tmp_path)
    restore = open_restore(qtbot, window, matter)
    restore.tabs.setCurrentIndex(PASTE_TAB)
    restore.paste.setPlainText("   ")
    qtbot.mouseClick(restore.go_button, LEFT)
    assert restore.message.text() == wording.NEED_PASTE and not window.backend.busy


def test_save_as_writes_the_restored_text(qtbot, window, tmp_path, monkeypatch):
    safe_path, matter = sanitized_case(tmp_path)
    restore = open_restore(qtbot, window, matter)
    paste_and_restore(qtbot, restore, open(safe_path, encoding="utf-8").read())

    asked = []
    chosen = str(tmp_path / "answer")  # no extension: .txt is added

    def fake(parent, caption, start, filters, initial=""):
        asked.append(start)
        return chosen, filters

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake)
    qtbot.mouseClick(restore.save_button, LEFT)
    qtbot.waitUntil(lambda: restore.message.text().startswith("Saved as"), timeout=10000)
    assert asked == [os.path.join(str(tmp_path), "pasted.rehydrated.txt")]
    assert open(chosen + ".txt", encoding="utf-8").read() == TEXT
    assert restore.showing_result() and not restore.go_button.isEnabled()


def test_save_as_refuses_the_matter_file(qtbot, window, tmp_path, monkeypatch):
    safe_path, matter = sanitized_case(tmp_path)
    restore = open_restore(qtbot, window, matter)
    paste_and_restore(qtbot, restore, open(safe_path, encoding="utf-8").read())
    before = open(matter, "rb").read()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (matter, ""))
    qtbot.mouseClick(restore.save_button, LEFT)
    qtbot.waitUntil(lambda: "matter file" in restore.message.text(), timeout=10000)
    assert open(matter, "rb").read() == before and "Nothing was written" in restore.message.text()


def test_lock_and_leaving_forget_the_restored_text(qtbot, window, tmp_path):
    safe_path, matter = sanitized_case(tmp_path)
    restore = open_restore(qtbot, window, matter)
    paste_and_restore(qtbot, restore, open(safe_path, encoding="utf-8").read())
    window.go("start")
    window.go("restore")
    assert restore.result.toPlainText() == "" and not restore.showing_result()
    assert restore.tabs.currentIndex() == FILE_TAB

    paste_and_restore(qtbot, restore, open(safe_path, encoding="utf-8").read())
    window.lock()
    assert restore.result.toPlainText() == "" and restore.paste.toPlainText() == ""


def test_dropping_a_file_or_text(qtbot, window, tmp_path):
    safe_path, matter = sanitized_case(tmp_path)
    restore = open_restore(qtbot, window, matter)

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(safe_path)])
    restore.tabs.setCurrentIndex(PASTE_TAB)
    assert drop(restore, mime).isAccepted()
    assert restore.tabs.currentIndex() == FILE_TAB
    assert os.path.normcase(restore.document.path()) == os.path.normcase(safe_path)

    pdf = QMimeData()
    pdf.setUrls([QUrl.fromLocalFile(str(tmp_path / "answer.pdf"))])
    drop(restore, pdf)
    assert os.path.normcase(restore.document.path()) == os.path.normcase(safe_path)  # unchanged

    text = QMimeData()
    text.setText("[PERSON_1] won.")
    drop(restore, text)
    assert restore.tabs.currentIndex() == PASTE_TAB and restore.paste.toPlainText() == "[PERSON_1] won."
    qtbot.mouseClick(restore.go_button, LEFT)
    qtbot.waitUntil(restore.showing_result, timeout=10000)
    assert restore.result.toPlainText() == "John A. Smith won."
