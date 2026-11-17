"""Where the window keeps its own files, and the recent-matters list.

Only file paths are stored: never a passphrase, a name or document text.
"""

from __future__ import annotations

import json
import os

MAX_RECENT = 8


def app_folder() -> str:
    """The per-user folder for the log and settings. ``REPLACE_O_MATIC_HOME`` overrides it."""
    override = os.environ.get("REPLACE_O_MATIC_HOME")
    local = os.environ.get("LOCALAPPDATA")
    if override:
        folder = override
    elif local:
        folder = os.path.join(local, "Replace-o-matic")
    else:
        folder = os.path.join(os.path.expanduser("~"), ".replace-o-matic")
    os.makedirs(folder, exist_ok=True)
    return folder


def _settings_path() -> str:
    return os.path.join(app_folder(), "settings.json")


def recent_matters() -> list[str]:
    """Matter files used before that still exist, newest first."""
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            paths = json.load(fh).get("recent_matters", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [p for p in paths if isinstance(p, str) and os.path.exists(p)][:MAX_RECENT]


def remember_matter(path: str) -> None:
    path = os.path.abspath(path)
    paths = [path] + [p for p in recent_matters() if p != path]
    try:
        try:
            with open(_settings_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data["recent_matters"] = paths[:MAX_RECENT]  # keep the firm's other settings
        with open(_settings_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass  # a list of recent files is a convenience, never a reason to fail


def allow_accept_all() -> bool:
    """False if the firm has set ``"allow_accept_all": false`` in settings.json: the
    Accept all button is then hidden. There is no control for it in the window."""
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            return json.load(fh).get("allow_accept_all", True) is not False
    except (OSError, ValueError, AttributeError):
        return True
