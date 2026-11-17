"""The screens. ``install(window)`` adds the ones that are built.

Built: start, choose, scanning. Still to come (GUI_PLAN.md phases 3 and 4):
review, done, restore, key. Code that leads to those checks ``name in
window.screens`` first, so a missing screen is never a crash.

Shared state lives on ``window.session`` (see ``gui.app.Session``):
document_path, matter_path, passphrase (memory only), vault, scan, result.
"""

from gui.screens.choose import ChooseScreen
from gui.screens.scanning import ScanningScreen
from gui.screens.start import StartScreen


def install(window) -> None:
    for screen in (StartScreen, ChooseScreen, ScanningScreen):
        window.add_screen(screen(window))
