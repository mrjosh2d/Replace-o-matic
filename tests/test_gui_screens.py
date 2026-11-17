"""Start, Choose and Scanning screens, driven headless with a stub model."""

import gc
import os
import re
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import sanitizer_core as sc  # noqa: E402
from gui import wording  # noqa: E402
from gui.app import MainWindow, Screen  # noqa: E402
from gui.screens import install, recent  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QSettings  # noqa: E402

TEXT = "John A. Smith sued Acme Corporation. " + "Filler words go here again and again. " * 40 + "Smith won."
PASSPHRASE = "correct horse battery staple"


class StubModel:
    def __init__(self):
        self.gate = threading.Event()
        self.gate.set()

    def predict_entities(self, text, labels, threshold=0.5):
        self.gate.wait(10)
        return [
            {"start": m.start(), "end": m.end(), "label": label}
            for name, label in {"John A. Smith": "person", "Acme Corporation": "company"}.items()
            for m in re.finditer(re.escape(name), text)
        ]


@pytest.fixture
def model(monkeypatch):
    fake = StubModel()
    monkeypatch.setattr(sc, "_default_detector", sc.GlinerDetector(model=fake, window_words=20, overlap_words=4))
    return fake


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    folder = tmp_path.parent / (tmp_path.name + "-settings")
    folder.mkdir()
    path = str(folder / "test.ini")
    store = QSettings(path, QSettings.Format.IniFormat)
    monkeypatch.setattr(recent, "settings", lambda: store)
    yield path
    store.sync()


@pytest.fixture(autouse=True)
def collect_garbage():
    yield
    gc.collect()  # free Qt wrappers while the application still exists


@pytest.fixture
def window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    install(window)
    window.go("start")
    yield window
    window.close()  # joins the worker thread
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def case(tmp_path):
    doc = tmp_path / "case.txt"
    doc.write_text(TEXT)
    return str(doc), str(tmp_path / "matter.vault")


def fill(window, doc, matter, passphrase=PASSPHRASE, again=None):
    choose = window.screens["choose"]
    assert choose.set_document(doc)
    choose.set_matter(matter)
    choose.passphrase.setText(passphrase)
    choose.again.setText(passphrase if again is None else again)
    return choose


def files_in(path):
    return sorted(os.listdir(os.path.dirname(path)))


def current_name(window):
    return window.current().name


def test_main_path_start_choose_scanning_stores_the_scan(qtbot, window, model, case):
    doc, matter = case
    start = window.screens["start"]
    assert not start.restore.isEnabled() and not start.key_link.isEnabled()  # later phases
    start.sanitize.click()
    assert current_name(window) == "choose"

    choose = fill(window, doc, matter)
    assert choose.is_new is False
    choose.new.setChecked(True)
    choose.submit()
    qtbot.waitUntil(lambda: window.session.scan is not None, timeout=10000)

    assert window.session.vault == sc.new_vault()
    assert {i.value for i in window.session.scan.items} >= {"John A. Smith", "Acme Corporation"}
    assert window.session.passphrase == PASSPHRASE
    assert current_name(window) == "review"
    assert files_in(doc) == ["case.txt"]  # nothing is written before the last step


def test_review_screen_is_entered_when_it_exists(qtbot, window, model, case):
    class Review(Screen):
        name, step = "review", 3

    window.add_screen(Review(window))
    doc, matter = case
    window.go("choose")
    choose = fill(window, doc, matter)
    choose.new.setChecked(True)
    choose.submit()
    qtbot.waitUntil(lambda: current_name(window) == "review", timeout=10000)
    assert window.session.scan is not None


def test_wrong_passphrase_shows_a_message_in_plain_words(qtbot, window, model, case):
    doc, matter = case
    sc.save_vault(sc.new_vault(), matter, passphrase="another passphrase entirely")
    window.go("choose")
    choose = fill(window, doc, matter, passphrase="wrong guess here")
    choose.existing.setChecked(True)
    choose.submit()
    qtbot.waitUntil(lambda: choose.go_button.isEnabled(), timeout=10000)
    assert "Wrong passphrase" in choose.error.text()
    assert "vault" not in choose.error.text().lower()
    assert current_name(window) == "choose" and window.session.passphrase == ""
    assert window.session.vault is None


def test_new_matter_with_different_passphrases_is_refused(qtbot, window, model, case):
    doc, matter = case
    window.go("choose")
    choose = fill(window, doc, matter, again="something else")
    choose.new.setChecked(True)
    choose.submit()
    assert choose.error.text() == wording.ERR_MISMATCH
    assert current_name(window) == "choose" and not window.backend.busy
    assert window.session.passphrase == ""


def test_missing_pieces_are_refused(window, case):
    doc, matter = case
    window.go("choose")
    choose = window.screens["choose"]
    choose.submit()
    assert choose.error.text() == wording.ERR_NO_DOCUMENT
    assert not choose.set_document(doc + ".missing")
    assert not choose.set_document(os.path.join(os.path.dirname(doc), "x.exe")) and choose.error.text()
    choose.set_document(doc)
    choose.submit()
    assert choose.error.text() == wording.ERR_NO_MATTER


def test_cancel_mid_scan_returns_to_choose_and_writes_nothing(qtbot, window, model, case):
    doc, matter = case
    model.gate.clear()
    window.go("choose")
    choose = fill(window, doc, matter)
    choose.new.setChecked(True)
    choose.submit()
    qtbot.waitUntil(lambda: current_name(window) == "scanning", timeout=10000)
    scanning = window.screens["scanning"]
    scanning.cancel_button.click()
    model.gate.set()
    qtbot.waitUntil(lambda: current_name(window) == "choose", timeout=10000)
    assert window.session.scan is None
    assert choose.error.text() == wording.SCAN_CANCELLED
    assert files_in(doc) == ["case.txt"]
    qtbot.waitUntil(lambda: not window.backend.busy)


def test_scanning_shows_progress_and_the_model_note(qtbot, window, monkeypatch, case):
    monkeypatch.setattr(sc, "_default_detector", None)
    scanning = window.screens["scanning"]
    window.session.vault = sc.new_vault()
    window.session.document_path = case[0]
    monkeypatch.setattr(window.backend, "scan", lambda *a, **k: None)
    window.go("scanning")
    assert scanning.note.text() == wording.LOADING_MODEL_NOTE
    scanning.on_progress(2, 5)
    assert scanning.count.text() == "Part 2 of 5" and scanning.bar.value() == 2 and scanning.note.text() == ""


def test_lock_forgets_the_passphrase_everywhere(qtbot, window, model, case):
    doc, matter = case
    window.go("choose")
    choose = fill(window, doc, matter)
    choose.new.setChecked(True)
    choose.submit()
    qtbot.waitUntil(lambda: window.session.scan is not None, timeout=10000)
    assert window.session.passphrase
    window.lock()
    assert window.session.passphrase == "" and window.session.scan is None and window.session.vault is None
    assert choose.passphrase.text() == "" and choose.again.text() == ""
    assert current_name(window) == "start"
    window.screens["start"].sanitize.click()
    assert choose.passphrase.text() == "" and choose.document_label.text() == wording.DROP_HERE


def test_recent_list_keeps_paths_only(qtbot, window, model, case, settings_file):
    doc, matter = case
    sc.save_vault(sc.new_vault(), matter, passphrase=PASSPHRASE)
    window.go("choose")
    choose = fill(window, doc, matter)
    choose.existing.setChecked(True)
    choose.submit()
    qtbot.waitUntil(lambda: window.session.scan is not None, timeout=10000)
    assert recent.load() == [os.path.abspath(matter)]
    raw = open(settings_file).read()
    assert PASSPHRASE not in raw and "Smith" not in raw and "case.txt" not in raw

    window.lock()
    start = window.screens["start"]
    assert [start.recent.item(i).text() for i in range(start.recent.count())] == [os.path.abspath(matter)]
    start._open_recent(start.recent.item(0))
    assert current_name(window) == "choose" and window.session.matter_path == os.path.abspath(matter)


def test_recent_list_is_capped_and_hides_missing_files(tmp_path):
    paths = []
    for n in range(recent.MAX_RECENT + 3):
        p = tmp_path / f"m{n}.vault"
        p.write_text("x")
        paths.append(str(p))
        recent.add(str(p))
    assert len(recent.load()) == recent.MAX_RECENT and recent.load()[0] == paths[-1]
    os.remove(paths[-1])
    assert paths[-1] not in recent.existing()


def test_titles_and_wording_stay_plain(window):
    assert window.windowTitle() == wording.APP_NAME
    banned = ("vault", "ner", "rehydrate", "regex", "placeholder")
    for name in dir(wording):
        value = getattr(wording, name)
        if name.isupper() and isinstance(value, str) and name not in ("APP_NAME", "MATTER_FILTER"):  # the filter shows the .vault extension
            assert not any(re.search(rf"\b{b}\b", value.lower()) for b in banned), name
