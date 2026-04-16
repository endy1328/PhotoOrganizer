from __future__ import annotations

import sys
from pathlib import Path

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
    window.show()
    return app.exec()
