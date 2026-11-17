"""Check a PyInstaller build for things that must not ship, and report its size.

    python scripts/check_dist.py [dist/Replace-o-matic]

Fails (exit 1) if the folder contains PyTorch, transformers, gliner,
huggingface_hub, or any Qt networking or web library, either as files or as
Python modules packed inside the executable. Run it after every build, on each
system. Needs PyInstaller (requirements-build.txt) to read the executable.
"""

from __future__ import annotations

import os
import re
import sys

DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist", "Replace-o-matic")

# Python packages that must not be bundled (PyTorch and the reference GLiNER stack).
PACKAGES = ("torch", "transformers", "gliner", "huggingface_hub", "tensorflow")
PACKAGE_DIR = re.compile(r"^(%s)(-[^/]*\.dist-info)?$" % "|".join(PACKAGES), re.I)
# Native libraries and Python modules for Qt networking and web content.
QT_NETWORK = re.compile(r"qt6?(network|webengine|websockets|webchannel|webview)|qtuiotouch|\btorch|c10\.dll", re.I)


def bad_files(root: str) -> list[str]:
    found = []
    for folder, dirs, files in os.walk(root):
        rel_folder = os.path.relpath(folder, root).replace("\\", "/")
        in_models = "/models/" in f"/{rel_folder}/"  # models/gliner is the bundled model, not the package
        for name in dirs + files:
            rel = name if rel_folder == "." else f"{rel_folder}/{name}"
            if (PACKAGE_DIR.match(name) and not in_models) or QT_NETWORK.search(name):
                found.append(rel)
    return found


def bad_modules(root: str) -> list[str]:
    """Modules inside the executable's packed archive (pure-Python packages
    such as transformers live there, not as files)."""
    from PyInstaller.archive.readers import CArchiveReader

    exe = next(
        (os.path.join(root, n) for n in ("Replace-o-matic.exe", "Replace-o-matic")
         if os.path.isfile(os.path.join(root, n))),
        None,
    )
    if exe is None:
        return ["(no Replace-o-matic executable found to inspect)"]
    archive = CArchiveReader(exe)
    names = []
    for entry in archive.toc:
        if entry.endswith(".pyz"):
            names += list(archive.open_embedded_archive(entry).toc)
    return [n for n in names
            if n.split(".")[0] in PACKAGES or re.search(r"QtNetwork|QtWebEngine|QtWebSockets|QtWebChannel", n)]


def size_mb(path: str) -> float:
    if os.path.isfile(path):
        return os.path.getsize(path) / 1e6
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs) / 1e6


def report_sizes(root: str) -> None:
    internal = os.path.join(root, "_internal")
    base = internal if os.path.isdir(internal) else root
    parts = sorted(((size_mb(os.path.join(base, n)), n) for n in os.listdir(base)), reverse=True)
    print(f"total: {size_mb(root):.0f} MB")
    for size, name in parts[:8]:
        print(f"  {size:6.0f} MB  {name}")


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not os.path.isdir(root):
        print(f"no build at {root}")
        return 1
    problems = bad_files(root) + bad_modules(root)
    report_sizes(root)
    if problems:
        print("FAILED: the build contains:")
        for item in problems:
            print("  " + item)
        return 1
    print("ok: no torch, transformers, gliner, huggingface_hub, QtNetwork or Qt web modules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
