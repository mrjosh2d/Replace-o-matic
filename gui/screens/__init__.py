"""The screens. ``install(window)`` adds them all; the window then shows "start"."""

from __future__ import annotations

from gui.screens.choose import ChooseScreen
from gui.screens.done import DoneScreen
from gui.screens.key import KeyScreen
from gui.screens.restore import RestoreScreen
from gui.screens.review import ReviewScreen
from gui.screens.scanning import ScanningScreen
from gui.screens.start import StartScreen

SCREENS = (StartScreen, ChooseScreen, ScanningScreen, ReviewScreen, DoneScreen, RestoreScreen, KeyScreen)


def install(window) -> None:
    for screen in SCREENS:
        window.add_screen(screen(window))
