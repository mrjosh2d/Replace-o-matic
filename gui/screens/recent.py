"""Recent matters: file paths only, kept in the user's settings.

Never store document text, client names or passphrases here. A matter's path
may contain a client name, so only the path of the matter file is kept, and
only that (never the document being sanitized).
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings

MAX_RECENT = 8
KEY = "recent_matters"


def settings() -> QSettings:
    return QSettings("Replace-o-matic", "Replace-o-matic")


def load() -> list[str]:
    value = settings().value(KEY, [])
    if isinstance(value, str):  # QSettings returns a bare string for a one-item list
        value = [value]
    return [p for p in value or [] if isinstance(p, str)]


def existing() -> list[str]:
    return [p for p in load() if os.path.isfile(p)]


def add(path: str) -> None:
    path = os.path.abspath(path)
    paths = [path] + [p for p in load() if p != path]
    store = settings()
    store.setValue(KEY, paths[:MAX_RECENT])
    store.sync()
