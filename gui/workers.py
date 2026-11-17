"""Background work for the window: one thread that owns the model.

Loading the model and scanning a long document take seconds to minutes, so
they never run on the window's thread. ``Backend`` is the only object screens
talk to. Every job is a call into ``sanitizer_service``; results come back as
Qt signals, delivered on the window's thread.

    backend = Backend()
    backend.finished.connect(on_finished)      # (job name, result object)
    backend.failed.connect(on_failed)          # (job name, message for the user)
    backend.cancelled.connect(on_cancelled)    # (job name)
    backend.progress.connect(on_progress)      # (done, total), during "scan"
    backend.scan(path, vault)
    backend.cancel()                           # safe from the window's thread
    backend.shutdown()                         # on close: cancel and wait

Jobs run one at a time, in the order submitted.
"""

from __future__ import annotations

import logging

import sanitizer_core as sc  # first project import: it sets the offline switches

import sanitizer_service as service
from gui import wording
from PySide6.QtCore import QObject, QThread, Signal, Slot

log = logging.getLogger("replace_o_matic")

UNEXPECTED = "Something went wrong and the step was not completed. Nothing was changed. Details are in the log file."
NO_MODEL = "The language model is missing from this installation. Please reinstall Replace-o-matic."


class _Engine(QObject):
    """Lives on the worker thread. Runs one job per ``run`` call."""

    finished = Signal(str, object)
    failed = Signal(str, str)
    cancelled = Signal(str)
    progress = Signal(int, int)

    def __init__(self):
        super().__init__()
        # Scans are numbered. A cancel covers every scan submitted so far, including
        # one that is queued but has not started, and none submitted afterwards.
        self.cancel_up_to = 0

    @Slot(str, object)
    def run(self, name: str, job) -> None:
        try:
            result = job()
        except sc.ScanCancelled:
            self.cancelled.emit(name)
        except (service.ServiceError, sc.VaultError) as error:
            # The one place service and core wording is put into staff words.
            self.failed.emit(name, wording.for_staff(str(error)))
        except sc.ModelNotFoundError:
            log.error("model not found")
            self.failed.emit(name, NO_MODEL)
        except Exception as error:  # never let the worker thread die
            # The exception text can contain document content, so only its type is logged.
            log.error("job %s failed: %s", name, type(error).__name__)
            self.failed.emit(name, UNEXPECTED)
        else:
            self.finished.emit(name, result)


class Backend(QObject):
    """The window's handle on the worker thread."""

    finished = Signal(str, object)
    failed = Signal(str, str)
    cancelled = Signal(str)
    progress = Signal(int, int)
    _submit = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = QThread()
        self._engine = _Engine()
        self._engine.moveToThread(self._thread)
        self._submit.connect(self._engine.run)  # queued: runs on the worker thread
        for name in ("finished", "failed", "cancelled", "progress"):
            getattr(self._engine, name).connect(getattr(self, name))
        self._pending = 0
        self._scan_number = 0
        self.finished.connect(self._done)
        self.failed.connect(self._done)
        self.cancelled.connect(self._done)
        self._thread.start()

    # ---- state

    @property
    def busy(self) -> bool:
        """True while any job is queued or running."""
        return self._pending > 0

    def _done(self, *_):
        self._pending -= 1

    def submit(self, name: str, job) -> None:
        """Run ``job()`` on the worker thread; its result arrives via ``finished``."""
        self._pending += 1
        self._submit.emit(name, job)

    # ---- jobs

    def preload_model(self) -> None:
        """Load the model in the background so the first scan starts at once."""
        self.submit("preload", lambda: sc.default_detector() and None)

    def open_matter(self, path: str, passphrase: str) -> None:
        self.submit("open_matter", lambda: service.open_matter(path, passphrase))

    def scan(self, path: str, vault: dict, regex_only: bool = False) -> None:
        engine = self._engine
        self._scan_number += 1
        number = self._scan_number

        def job():
            return service.scan_document(
                path,
                vault,
                regex_only,
                progress=engine.progress.emit,
                cancelled=lambda: number <= engine.cancel_up_to,
            )

        self.submit("scan", job)

    def commit(self, scan, accepted, declined, reviewed, vault_path, passphrase, output_path=None) -> None:
        self.submit(
            "commit",
            lambda: service.commit(scan, accepted, declined, reviewed, vault_path, passphrase, output_path),
        )

    def restore(self, path: str, vault: dict, output_path=None, tolerant: bool = True) -> None:
        self.submit("restore", lambda: service.restore(path, vault, output_path, tolerant))

    def write_keys(self, vault: dict, document_path, vault_path: str, **options) -> None:
        self.submit("keys", lambda: service.write_keys(vault, document_path, vault_path, **options))

    # ---- control

    def cancel(self) -> None:
        """Ask the running or queued scan to stop at the next window. Returns at once."""
        self._engine.cancel_up_to = self._scan_number

    def shutdown(self, wait_ms: int = 15000) -> bool:
        """Cancel, stop the thread and wait for it. False if it did not stop in time."""
        self.cancel()
        self._thread.quit()
        return self._thread.wait(wait_ms)
