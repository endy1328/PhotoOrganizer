from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from .config import ConfigManager
from .engine import OrganizerEngine
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parents[2]
    config_manager = ConfigManager(base_dir)
    engine = OrganizerEngine(base_dir)
    window = MainWindow(engine=engine, config_manager=config_manager)
    _position_window_on_primary_screen(window)
    window.show()
    window.showNormal()
    window.raise_()
    window.activateWindow()
    return app.exec()


def _position_window_on_primary_screen(window: MainWindow) -> None:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    geometry = window.frameGeometry()
    geometry.moveCenter(screen.availableGeometry().center())
    window.move(geometry.topLeft())


if __name__ == "__main__":
    raise SystemExit(main())
