import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from boss_timer.ui.fonts import configure_application_font


@pytest.fixture(scope="session")
def app():
    instance = QApplication.instance() or QApplication([])
    configure_application_font(instance)
    yield instance


@pytest.fixture
def clock():
    class FakeClock:
        now = 1_793_000_000.0

        def __call__(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    return FakeClock()
