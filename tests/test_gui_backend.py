"""The window's background thread, driven without a display."""

import os
import re
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import sanitizer_core as sc  # noqa: E402
import sanitizer_service as service  # noqa: E402
from gui import wording  # noqa: E402
from gui.app import MainWindow, Screen  # noqa: E402
from gui.workers import NO_MODEL, UNEXPECTED, Backend  # noqa: E402
from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

TEXT = "John A. Smith sued Acme Corporation. " + "Filler words go here again and again. " * 40 + "Smith won."
PASSPHRASE = "correct horse battery"


class SlowModel:
    """A stand-in model that can be paused between windows."""

    def __init__(self):
        self.calls = 0
        self.gate = threading.Event()
        self.gate.set()
        self.threads = set()

    def predict_entities(self, text, labels, threshold=0.5):
        self.gate.wait(10)
        self.calls += 1
        self.threads.add(threading.get_ident())
        return [
            {"start": m.start(), "end": m.end(), "label": label}
            for name, label in {"John A. Smith": "person", "Acme Corporation": "company"}.items()
            for m in re.finditer(re.escape(name), text)
        ]


@pytest.fixture
def model(monkeypatch):
    fake = SlowModel()
    monkeypatch.setattr(sc, "_default_detector", sc.GlinerDetector(model=fake, window_words=20, overlap_words=4))
    return fake


@pytest.fixture
def backend(qtbot):
    backend = Backend()
    yield backend
    assert backend.shutdown()


@pytest.fixture
def case(tmp_path):
    doc = tmp_path / "case.txt"
    doc.write_text(TEXT)
    return str(doc), str(tmp_path / "matter.vault")


def test_scan_runs_off_the_window_thread_and_reports_progress(qtbot, backend, model, case):
    doc, _ = case
    seen = []
    backend.progress.connect(lambda done, total: seen.append((done, total)))
    with qtbot.waitSignal(backend.finished, timeout=10000) as signal:
        backend.scan(doc, sc.new_vault())
        assert backend.busy
    job, scan = signal.args
    assert job == "scan" and {i.value for i in scan.items} >= {"John A. Smith", "Acme Corporation", "Smith"}
    assert threading.get_ident() not in model.threads and len(model.threads) == 1
    assert seen[0][0] == 0 and seen[-1][0] == seen[-1][1] > 3
    qtbot.waitUntil(lambda: not backend.busy)


def test_cancel_stops_between_windows_and_the_next_scan_still_works(qtbot, backend, model, case):
    doc, _ = case
    model.gate.clear()  # hold the first window
    with qtbot.waitSignal(backend.cancelled, timeout=10000) as signal:
        backend.scan(doc, sc.new_vault())
        backend.cancel()
        model.gate.set()
    assert signal.args == ["scan"] and model.calls <= 2
    assert os.listdir(os.path.dirname(doc)) == ["case.txt"]

    with qtbot.waitSignal(backend.finished, timeout=10000) as signal:
        backend.scan(doc, sc.new_vault())  # the old cancel must not leak into this scan
    assert signal.args[0] == "scan"


def test_full_task_through_the_backend(qtbot, backend, model, case):
    doc, vault_path = case
    with qtbot.waitSignal(backend.finished, timeout=10000) as signal:
        backend.open_matter(vault_path, PASSPHRASE)
    vault = signal.args[1]
    with qtbot.waitSignal(backend.finished, timeout=10000) as signal:
        backend.scan(doc, vault)
    scan = signal.args[1]
    with qtbot.waitSignal(backend.finished, timeout=10000) as signal:
        backend.commit(scan, scan.items, [], True, vault_path, PASSPHRASE)
    result = signal.args[1]
    assert "Smith" not in open(result.output_path).read()
    with qtbot.waitSignal(backend.finished, timeout=10000) as signal:
        backend.write_keys(result.vault, result.output_path, vault_path, fmt="txt")
    assert os.path.exists(signal.args[1].confidential_path)
    with qtbot.waitSignal(backend.finished, timeout=10000) as signal:
        backend.restore(result.output_path, result.vault)
    assert open(signal.args[1].output_path).read() == TEXT


def test_failures_become_messages_and_the_thread_survives(qtbot, backend, model, case, monkeypatch, caplog):
    doc, vault_path = case
    with qtbot.waitSignal(backend.failed, timeout=10000) as signal:
        backend.scan(doc + ".missing.txt", sc.new_vault())
    assert signal.args == ["scan", UNEXPECTED]

    sc.save_vault(sc.new_vault(), vault_path)  # a plaintext vault
    with qtbot.waitSignal(backend.failed, timeout=10000) as signal:
        backend.open_matter(vault_path, PASSPHRASE)
    assert "not an encrypted vault" in signal.args[1]

    def no_model():
        raise sc.ModelNotFoundError("missing")

    monkeypatch.setattr(sc, "default_detector", no_model)
    with qtbot.waitSignal(backend.failed, timeout=10000) as signal:
        backend.preload_model()
    assert signal.args == ["preload", NO_MODEL]

    monkeypatch.undo()
    monkeypatch.setattr(sc, "_default_detector", sc.GlinerDetector(model=model, window_words=20, overlap_words=4))
    with qtbot.waitSignal(backend.finished, timeout=10000):
        backend.scan(doc, sc.new_vault())  # still alive after three failures
    assert "John" not in caplog.text and "Smith" not in caplog.text  # the log never holds document text


def test_shutdown_during_a_scan_cancels_and_joins(qtbot, model, case):
    doc, _ = case
    backend = Backend()
    model.gate.clear()
    backend.scan(doc, sc.new_vault())
    model.gate.set()
    assert backend.shutdown()
    assert model.calls < 10


class Recorder(Screen):
    name, step = "start", 0

    def __init__(self, window):
        super().__init__(window)
        self.events = []

    def enter(self):
        self.events.append("enter")

    def on_finished(self, job, result):
        self.events.append(("finished", job))

    def on_progress(self, done, total):
        self.events.append("progress")


def test_window_routes_results_to_the_showing_screen_and_locks(qtbot, model, case, monkeypatch):
    doc, _ = case
    window = MainWindow()
    qtbot.addWidget(window)
    screen = Recorder(window)
    window.add_screen(screen)
    window.go("start")
    assert window.windowTitle() == wording.APP_NAME and screen.events == ["enter"]

    window.session.passphrase, window.session.document_path = PASSPHRASE, doc
    with qtbot.waitSignal(window.backend.finished, timeout=10000):
        window.backend.scan(doc, sc.new_vault())
    qtbot.waitUntil(lambda: ("finished", "scan") in screen.events)
    assert "progress" in screen.events

    window.new_task()
    assert window.session.passphrase == PASSPHRASE and window.session.document_path == ""
    window.lock()
    assert window.session.passphrase == "" and window.session.vault is None

    # closing while busy asks first; "No" keeps the window open
    model.gate.clear()
    window.backend.scan(doc, sc.new_vault())
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    assert not window.close()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    model.gate.set()
    assert window.close()
    assert not window.backend._thread.isRunning()


def test_no_qt_network_modules_are_loaded():
    import sys

    assert not [m for m in sys.modules if "QtNetwork" in m or "WebEngine" in m or "WebSockets" in m]
    assert isinstance(QThread.currentThread(), QThread)


@pytest.mark.model
def test_window_scan_opens_no_network_connection_at_os_level(tmp_path):
    """The whole window process, Qt included, traced with strace during a real scan."""
    import shutil
    import subprocess
    import sys

    model_dir = sc.DEFAULT_MODEL_DIR
    if not os.path.isfile(os.path.join(model_dir, "onnx", "model.onnx")):
        pytest.skip("GLiNER model not downloaded")
    if not shutil.which("strace"):
        pytest.skip("strace not installed")
    doc = tmp_path / "case.txt"
    doc.write_text("John Smith of Acme Corporation, 12 Oak Street, Akron, OH 44301. " * 20)
    script = (
        "import sys\n"
        "import sanitizer_core as sc\n"
        "from PySide6.QtCore import QTimer\n"
        "from PySide6.QtWidgets import QApplication\n"
        "from gui.app import MainWindow\n"
        "app = QApplication([])\n"
        "window = MainWindow(); window.show()\n"
        "done = []\n"
        "window.backend.finished.connect(lambda job, result: done.append(result) if job == 'scan' else None)\n"
        "window.backend.preload_model()\n"
        f"window.backend.scan({str(doc)!r}, sc.new_vault())\n"
        "QTimer.singleShot(8000, app.quit)\n"  # telemetry, if any, starts a few seconds in
        "app.exec()\n"
        "assert done and done[0].items, 'scan did not finish'\n"
        "window.close()\n"
    )
    root = os.path.join(os.path.dirname(__file__), "..")
    env = {k: v for k, v in os.environ.items() if k not in sc._OFFLINE_ENV}
    env["QT_QPA_PLATFORM"] = "offscreen"
    log = tmp_path / "trace.log"
    result = subprocess.run(
        ["strace", "-f", "-qq", "-e", "trace=connect", "-o", str(log), sys.executable, "-W", "ignore", "-c", script],
        cwd=root, env=env, capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    if "ptrace" in result.stderr.lower() or "operation not permitted" in result.stderr.lower():
        pytest.skip("strace is not permitted here")
    assert result.returncode == 0, result.stderr[-2000:]
    outbound = [line for line in log.read_text().splitlines() if "AF_INET" in line]
    assert outbound == [], outbound[:5]
