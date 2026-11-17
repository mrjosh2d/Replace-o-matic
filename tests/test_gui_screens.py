"""The screens, driven through their real widgets without a display.

Set ``SCREENSHOT_DIR`` to save a PNG of each screen as the tests pass through it.
"""

import os
import re
import threading
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import sanitizer_core as sc  # noqa: E402
import sanitizer_service as service  # noqa: E402
from gui import settings, wording  # noqa: E402
from gui.app import MainWindow  # noqa: E402
from gui.review_model import TEXT as TEXT_COLUMN  # noqa: E402
from gui.review_model import TICK, TYPE  # noqa: E402
from gui.screens import install  # noqa: E402
from gui.screens.review import AddDialog  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QComboBox, QDialog, QMessageBox  # noqa: E402

TEXT = (
    "John A. Smith sued Acme Corporation. Smith's SSN is 123-45-6789. "
    "The American Arbitration Association heard it. Gerry testified for Acme. "
    + "Filler words go here again and again. " * 30
    + "ACME CORPORATION lost and Smith won. See the smith file."
)
NAMES = {"John A. Smith": "person", "Acme Corporation": "company", "American Arbitration Association": "company"}
PASSPHRASE = "correct horse battery staple"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
LEFT = Qt.MouseButton.LeftButton


class SlowModel:
    """A stand-in model that can be paused between windows."""

    def __init__(self):
        self.gate = threading.Event()
        self.gate.set()

    def predict_entities(self, text, labels, threshold=0.5):
        self.gate.wait(10)
        return [
            {"start": m.start(), "end": m.end(), "label": label}
            for name, label in NAMES.items()
            for m in re.finditer(re.escape(name), text)
        ]


@pytest.fixture
def model(monkeypatch):
    fake = SlowModel()
    monkeypatch.setattr(sc, "_default_detector", sc.GlinerDetector(model=fake, window_words=20, overlap_words=4))
    return fake


@pytest.fixture
def window(qtbot, model, tmp_path, monkeypatch):
    monkeypatch.setenv("REPLACE_O_MATIC_HOME", str(tmp_path / "home"))
    # No test may block on a real dialog: an unexpected one fails at once.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("unexpected question"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail("unexpected warning"))
    window = MainWindow()
    qtbot.addWidget(window)
    install(window)
    window.go("start")
    window.show()
    yield window
    window.backend.shutdown()


@pytest.fixture
def case(tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    doc = folder / "case.txt"
    doc.write_text(TEXT, encoding="utf-8")
    return str(doc), str(folder / "matter.vault")


def snap(window, name):
    folder = os.environ.get("SCREENSHOT_DIR")
    if folder:
        os.makedirs(folder, exist_ok=True)
        window.grab().save(os.path.join(folder, name + ".png"))


def answer(monkeypatch, button):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda parent, title, text, *a, **k: asked.append(text) or button)
    return asked


def choose(qtbot, window, doc, matter, passphrase=PASSPHRASE, again=None):
    """Fill in the Choose screen and press Continue."""
    screen = window.screens["choose"]
    if window.current() is not screen:
        qtbot.mouseClick(window.screens["start"].sanitize_button, LEFT)
    assert window.current() is screen
    screen.document.set_path(doc)
    screen.form.picker.set_path(matter)
    if not screen.form.is_open():
        screen.form.passphrase.setText(passphrase)
        if screen.form.is_new():
            screen.form.again.setText(passphrase if again is None else again)
    qtbot.mouseClick(screen.go_button, LEFT)
    return screen


def to_review(qtbot, window, doc, matter):
    choose(qtbot, window, doc, matter)
    review = window.screens["review"]
    qtbot.waitUntil(lambda: window.current() is review, timeout=10000)
    return review


def proxy_row(review, value):
    for row in range(review.proxy.rowCount()):
        if review.proxy.index(row, TEXT_COLUMN).data(Qt.ItemDataRole.EditRole) == value:
            return row
    raise AssertionError(f"{value!r} is not in the table")


def to_done(qtbot, window):
    qtbot.mouseClick(window.screens["review"].sanitize_button, LEFT)
    qtbot.waitUntil(lambda: window.current() is window.screens["done"], timeout=10000)
    return window.session.result


# --------------------------------------------------------------------------


def test_full_task_txt_through_the_widgets(qtbot, window, case, monkeypatch):
    doc, matter = case
    start = window.screens["start"]
    assert window.current() is start and not start.recent.isVisible()
    snap(window, "1-start")

    # Choose: a new matter asks twice and shows the no-recovery warning.
    qtbot.mouseClick(start.sanitize_button, LEFT)
    screen = window.screens["choose"]
    qtbot.mouseClick(screen.go_button, LEFT)
    assert screen.message.text() == wording.NEED_DOCUMENT
    screen.form.picker.set_path(matter)
    assert screen.form.again.isVisible() and screen.form.warning.isVisible()
    assert screen.form.warning.text() == wording.NEW_MATTER_WARNING
    assert screen.form.passphrase.echoMode() == screen.form.passphrase.EchoMode.Password
    choose(qtbot, window, doc, matter, again="something else")
    assert screen.message.text() == wording.PASSPHRASES_DIFFER and window.current() is screen
    screen.form.passphrase.setText(PASSPHRASE)
    screen.form.again.setText(PASSPHRASE)
    snap(window, "2-choose")

    qtbot.mouseClick(screen.go_button, LEFT)
    review = window.screens["review"]
    qtbot.waitUntil(lambda: window.current() is review, timeout=10000)
    assert screen.form.passphrase.text() == ""  # not kept in the widget once the matter is open
    values = [r.item.value for r in review.model.state.rows]
    assert {"John A. Smith", "Acme Corporation", "Smith", "123-45-6789"} <= set(values)
    assert review.sanitize_button.text() == wording.SANITIZE_N.format(count=len(values))
    assert review.where.text() == wording.WHERE_NONE

    # Context pane: selecting a row shows the first occurrence; the arrows step through all of them.
    review.table.selectRow(proxy_row(review, "Smith"))
    assert review.where.text() == wording.WHERE.format(index=1, total=3)  # every occurrence, not only the first
    assert "John A. «Smith» sued" in review.context.text()
    qtbot.mouseClick(review.next_button, LEFT)
    assert review.where.text() == wording.WHERE.format(index=2, total=3) and "«Smith»'s SSN" in review.context.text()
    qtbot.mouseClick(review.next_button, LEFT)
    assert "«Smith» won" in review.context.text()
    qtbot.mouseClick(review.next_button, LEFT)  # wraps round
    qtbot.mouseClick(review.previous_button, LEFT)
    assert review.where.text() == wording.WHERE.format(index=3, total=3)
    snap(window, "4-review")

    # Type is a drop-down; filter and search narrow the table; sorting works.
    index = review.proxy.index(proxy_row(review, "Acme"), TYPE)
    delegate = review.table.itemDelegateForColumn(TYPE)
    editor = delegate.createEditor(review.table, None, index)
    assert isinstance(editor, QComboBox)
    delegate.setEditorData(editor, index)
    editor.setCurrentIndex(editor.findData("company"))
    delegate.setModelData(editor, review.proxy, index)
    review.filter.setCurrentIndex(review.filter.findData("person"))
    assert review.proxy.rowCount() == sum(r.item.type == "person" for r in review.model.state.rows)
    review.filter.setCurrentIndex(0)
    review.search.setText("acme")
    assert review.proxy.rowCount() == 3  # Acme Corporation, Acme, ACME CORPORATION
    review.search.clear()
    review.table.sortByColumn(TEXT_COLUMN, Qt.SortOrder.AscendingOrder)
    shown = [review.proxy.index(r, TEXT_COLUMN).data() for r in range(review.proxy.rowCount())]
    assert shown == sorted(shown, key=str.lower)

    # Untick one row, add one the scan missed.
    untick = review.proxy.index(proxy_row(review, "American Arbitration Association"), TICK)
    assert review.proxy.setData(untick, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)

    def fill(dialog):
        assert not dialog.ok.isEnabled()
        dialog.text.setText("Nobody Here")
        assert not dialog.ok.isEnabled() and "does not appear" in dialog.preview.text()
        dialog.text.setText("Gerry")
        assert dialog.ok.isEnabled() and "«Gerry» testified" in dialog.preview.text()
        snap(dialog, "4-review-add")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AddDialog, "exec", fill)
    qtbot.mouseClick(review.add_button, LEFT)
    assert review.model.state.rows[-1].item.value == "Gerry"
    assert review.sanitize_button.text() == wording.SANITIZE_N.format(count=len(values))

    result = to_done(qtbot, window)
    done = window.screens["done"]
    snap(window, "5-done")
    safe = open(result.output_path, encoding="utf-8").read()
    assert result.output_path.endswith("case.sanitized.txt") and result.reviewed
    assert "Smith" not in safe and "Gerry" not in safe and "American Arbitration Association" in safe
    vault = sc.load_vault(matter, passphrase=PASSPHRASE)
    assert vault["declined"] == ["American Arbitration Association"]
    assert all(e["reviewed"] for e in vault["mappings"].values())
    assert sc.rehydrate_text(safe, vault) == TEXT
    assert result.output_path in done.summary.text() and matter in done.summary.text()
    assert done.residue.isVisible() and done.residue.item(0).text().startswith("Smith ")  # "the smith file"
    assert window.windowTitle() == wording.APP_NAME
    assert settings.recent_matters() == [matter]

    # Make key, from the Done screen: the matter is open, so no passphrase is asked.
    qtbot.mouseClick(done.key_button, LEFT)
    key = window.screens["key"]
    assert window.current() is key and key.document.path() == result.output_path
    assert key.form.is_open() and not key.form.passphrase.isVisible()
    key.safe.setChecked(True)
    asked = answer(monkeypatch, QMessageBox.StandardButton.No)
    qtbot.mouseClick(key.go_button, LEFT)
    assert asked == [wording.CONFIDENTIAL_KEY_WARNING] and not window.backend.busy
    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    qtbot.mouseClick(key.go_button, LEFT)
    qtbot.waitUntil(lambda: wording.KEY_WROTE_SAFE.split("{")[0] in key.message.text(), timeout=10000)
    snap(window, "7-key")
    stem = os.path.splitext(result.output_path)[0]
    assert "John A. Smith" in service.read_document(stem + ".key.docx")
    assert "John A. Smith" not in service.read_document(stem + ".key-safe.docx")

    # Sanitize another: the document is forgotten, the matter stays open.
    window.go("done")
    qtbot.mouseClick(done.another_button, LEFT)
    screen = window.screens["choose"]
    assert window.current() is screen and screen.document.path() == "" and screen.form.is_open()
    window.go("start")
    assert start.recent.count() == 1 and start.recent.item(0).text() == matter
    snap(window, "1-start-recent")


def docx_with(path, paragraphs):
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>')


def test_full_task_docx_through_the_widgets(qtbot, window, tmp_path):
    doc, matter = str(tmp_path / "letter.docx"), str(tmp_path / "matter.vault")
    docx_with(doc, ["John A. Smith sued Acme Corporation.", "Smith's SSN is 123-45-6789."])
    review = to_review(qtbot, window, doc, matter)
    review.table.selectRow(0)  # looked at one row: that is a review
    result = to_done(qtbot, window)
    assert result.output_path.endswith("letter.sanitized.docx") and result.reviewed
    safe = service.read_document(result.output_path)
    assert "Smith" not in safe and "Acme" not in safe and "123-45-6789" not in safe and "[PERSON_1]" in safe
    assert not window.screens["done"].residue.isVisible()

    # Restore it through the Restore screen: the matter is still open.
    window.go("start")
    qtbot.mouseClick(window.screens["start"].restore_button, LEFT)
    restore = window.screens["restore"]
    restore.document.set_path(result.output_path)
    qtbot.mouseClick(restore.go_button, LEFT)
    qtbot.waitUntil(lambda: "restored" in restore.message.text(), timeout=10000)
    restored = os.path.join(str(tmp_path), "letter.sanitized.rehydrated.docx")
    assert service.read_document(restored) == service.read_document(doc)


def test_cancel_mid_scan_leaves_no_files(qtbot, window, model, case):
    doc, matter = case
    model.gate.clear()  # hold the scan in its first part
    screen = choose(qtbot, window, doc, matter)
    scanning = window.screens["scanning"]
    qtbot.waitUntil(lambda: window.current() is scanning, timeout=10000)
    snap(window, "3-scanning")
    qtbot.mouseClick(scanning.cancel_button, LEFT)
    assert not scanning.cancel_button.isEnabled() and scanning.status.text() == wording.CANCELLING
    model.gate.set()
    qtbot.waitUntil(lambda: window.current() is screen, timeout=10000)
    assert screen.message.text() == wording.SCAN_CANCELLED and window.session.scan is None
    assert os.listdir(os.path.dirname(doc)) == ["case.txt"]
    assert settings.recent_matters() == []  # a matter that was never saved is not listed

    qtbot.mouseClick(screen.go_button, LEFT)  # and the next scan is not affected
    qtbot.waitUntil(lambda: window.current() is window.screens["review"], timeout=10000)
    assert window.screens["scanning"].bar.maximum() > 3


def test_wrong_passphrase_is_refused_on_the_choose_screen(qtbot, window, case):
    doc, matter = case
    sc.save_vault(sc.new_vault(), matter, passphrase=PASSPHRASE)
    screen = choose(qtbot, window, doc, matter, passphrase="not the passphrase")
    assert not screen.form.again.isVisible()  # an existing matter asks once
    qtbot.waitUntil(lambda: "Wrong passphrase" in screen.message.text(), timeout=10000)
    assert window.current() is screen and window.session.vault is None and window.session.passphrase == ""
    assert screen.go_button.isEnabled()
    screen.form.passphrase.setText(PASSPHRASE)
    qtbot.mouseClick(screen.go_button, LEFT)
    qtbot.waitUntil(lambda: window.current() is window.screens["review"], timeout=10000)


def test_edit_to_text_not_in_the_document_is_refused(qtbot, window, case):
    review = to_review(qtbot, window, *case)
    index = review.proxy.index(proxy_row(review, "John A. Smith"), TEXT_COLUMN)
    assert not review.proxy.setData(index, "Jon Smith", Qt.ItemDataRole.EditRole)
    assert "does not appear" in review.message.text() and index.data(Qt.ItemDataRole.EditRole) == "John A. Smith"
    assert review.proxy.setData(index, "John A. Smith sued", Qt.ItemDataRole.EditRole)
    review.table.selectRow(index.row())
    assert "«John A. Smith sued»" in review.context.text()


def test_unticked_rows_become_declines(qtbot, window, case, monkeypatch):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    review.table.selectRow(proxy_row(review, "Acme Corporation"))
    qtbot.mouseClick(review.decline_button, LEFT)  # Decline selected
    tick = review.proxy.index(proxy_row(review, "123-45-6789"), TICK)
    review.proxy.setData(tick, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)  # a click on the box
    total = len(review.model.state.rows)
    assert review.sanitize_button.text() == wording.SANITIZE_N.format(count=total - 2)
    result = to_done(qtbot, window)
    vault = sc.load_vault(matter, passphrase=PASSPHRASE)
    assert sorted(vault["declined"]) == ["123-45-6789", "Acme Corporation"]
    safe = open(result.output_path, encoding="utf-8").read()
    assert "123-45-6789" in safe and "John A. Smith" not in safe

    # The same document again: declined items are not proposed a second time.
    qtbot.mouseClick(window.screens["done"].another_button, LEFT)
    review = to_review(qtbot, window, doc, matter)
    assert "123-45-6789" not in [r.item.value for r in review.model.state.rows]


def test_accept_all_then_sanitize_asks_and_marks_entries_unreviewed(qtbot, window, case, monkeypatch):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    qtbot.mouseClick(review.accept_all_button, LEFT)
    asked = answer(monkeypatch, QMessageBox.StandardButton.No)
    qtbot.mouseClick(review.sanitize_button, LEFT)
    assert asked == [wording.UNREVIEWED] and window.current() is review and not window.backend.busy
    assert not os.path.exists(matter)
    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    result = to_done(qtbot, window)
    assert result.reviewed is False and wording.DONE_NOT_REVIEWED in window.screens["done"].summary.text()
    vault = sc.load_vault(matter, passphrase=PASSPHRASE)
    assert vault["mappings"] and all(e["reviewed"] is False for e in vault["mappings"].values())


def test_commit_failure_is_shown_and_nothing_is_written(qtbot, window, case, monkeypatch):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    review.table.selectRow(0)

    def fail(*args, **kwargs):
        raise OSError("disk full: John A. Smith")

    monkeypatch.setattr(sc, "save_vault", fail)
    qtbot.mouseClick(review.sanitize_button, LEFT)
    qtbot.waitUntil(lambda: review.sanitize_button.isEnabled() and review.message.text() != wording.WORKING, timeout=10000)
    assert window.current() is review and "Smith" not in review.message.text()
    assert os.listdir(os.path.dirname(doc)) == ["case.txt"]


def sanitized_case(tmp_path):
    """A sanitized .txt and its matter, made with the service."""
    doc, matter = tmp_path / "case.txt", str(tmp_path / "matter.vault")
    doc.write_text(TEXT, encoding="utf-8")
    scan = service.scan_document(str(doc), sc.new_vault())
    result = service.commit(scan, scan.items, [], True, matter, PASSPHRASE)
    return result.output_path, matter


def test_restore_screen(qtbot, window, tmp_path):
    safe_path, matter = sanitized_case(tmp_path)
    came_back = tmp_path / "analysis.txt"
    text = open(safe_path, encoding="utf-8").read()
    came_back.write_text(text.replace("[PERSON_1]", "[Person 1]", 1) + " See [COMPANY_99].", encoding="utf-8")
    qtbot.mouseClick(window.screens["start"].restore_button, LEFT)
    restore = window.screens["restore"]
    assert window.current() is restore and not restore.form.new_button.isVisible()

    restore.document.set_path(str(came_back))
    restore.form.picker.set_path(str(tmp_path / "no-such.vault"))
    restore.form.passphrase.setText(PASSPHRASE)
    qtbot.mouseClick(restore.go_button, LEFT)
    assert restore.message.text() == wording.MATTER_MISSING and not window.backend.busy

    restore.form.picker.set_path(matter)
    restore.form.passphrase.setText("wrong")
    qtbot.mouseClick(restore.go_button, LEFT)
    qtbot.waitUntil(lambda: "Wrong passphrase" in restore.message.text(), timeout=10000)

    restore.form.passphrase.setText(PASSPHRASE)
    qtbot.mouseClick(restore.go_button, LEFT)
    qtbot.waitUntil(lambda: "restored" in restore.message.text(), timeout=10000)
    snap(window, "6-restore")
    assert "[Person 1]" in restore.message.text() and "[COMPANY_99]" in restore.message.text()
    restored = open(tmp_path / "analysis.rehydrated.txt", encoding="utf-8").read()
    assert restored == TEXT + " See [COMPANY_99]."
    assert window.session.passphrase == PASSPHRASE and restore.form.passphrase.text() == ""


def test_key_screen_from_start_and_lock_forgets(qtbot, window, tmp_path, monkeypatch):
    _, matter = sanitized_case(tmp_path)
    qtbot.mouseClick(window.screens["start"].key_button, LEFT)
    key = window.screens["key"]
    assert window.current() is key and key.confidential.isChecked() and not key.safe.isChecked()
    key.form.picker.set_path(matter)
    key.form.passphrase.setText(PASSPHRASE)
    key.confidential.setChecked(False)
    qtbot.mouseClick(key.go_button, LEFT)
    assert key.message.text() == wording.KEY_NEED_ONE
    key.safe.setChecked(True)  # the safe key alone needs no warning
    qtbot.mouseClick(key.go_button, LEFT)
    qtbot.waitUntil(lambda: wording.KEY_WROTE_SAFE.split("{")[0] in key.message.text(), timeout=10000)
    stem = os.path.splitext(matter)[0]
    assert os.path.exists(stem + ".key-safe.docx") and not os.path.exists(stem + ".key.docx")
    assert "Smith" not in service.read_document(stem + ".key-safe.docx")

    # Lock: the passphrase and the open matter are gone, in the session and in every form.
    assert window.session.passphrase == PASSPHRASE
    window.lock()
    assert window.current() is window.screens["start"]
    assert window.session.passphrase == "" and window.session.vault is None
    window.go("key")
    assert not key.form.is_open() and key.form.passphrase.isVisible() and key.form.passphrase.text() == ""


def test_lock_on_the_review_screen_drops_the_document_text(qtbot, window, case):
    review = to_review(qtbot, window, *case)
    review.table.selectRow(0)
    assert review.context.text()
    window.lock()
    assert review.model is None and review.proxy.rowCount() == 0 and review.context.text() == ""


def test_settings_file_holds_paths_only(qtbot, window, case):
    doc, matter = case
    review = to_review(qtbot, window, doc, matter)
    review.table.selectRow(0)
    to_done(qtbot, window)
    home = os.environ["REPLACE_O_MATIC_HOME"]
    for name in os.listdir(home):
        content = open(os.path.join(home, name), encoding="utf-8").read()
        assert PASSPHRASE not in content and "Smith" not in content and "Acme" not in content
    assert matter in open(os.path.join(home, "settings.json"), encoding="utf-8").read()
