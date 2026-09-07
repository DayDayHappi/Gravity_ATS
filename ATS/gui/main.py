"""Desktop entry point for source and PyInstaller onedir execution."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ATS.application.service import TestService
from ATS.gui.main_window import MainWindow
from ATS.platform.resources import ResourceLocator
from ATS.platform.services import create_platform_services


def main(argv=None) -> int:
    app = QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("Gravity ATS")
    app.setOrganizationName("Gravity")
    locator = ResourceLocator()
    services = create_platform_services(locator)
    service = TestService(resource_locator=locator, platform_services=services)
    window = MainWindow(service)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
