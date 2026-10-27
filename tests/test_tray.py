from pathlib import Path

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon

from boss_timer.app import resource_path
from boss_timer.repositories.boss_repository import BossRepository
from boss_timer.repositories.json_store import JsonStore, StorageError
from boss_timer.repositories.profile_repository import ProfileRepository
from boss_timer.services.profile_service import ProfileService
from boss_timer.services.timer_service import TimerService
from boss_timer.ui.main_window import MainWindow
from boss_timer.ui.tray import enable_tray


@pytest.fixture
def tray_window(app, tmp_path, clock, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    window = MainWindow(
        BossRepository(tmp_path / "catalog.json", resource_path()),
        ProfileService(ProfileRepository(tmp_path / "profiles.json"), clock),
        TimerService(clock), JsonStore(tmp_path / "settings.json"),
    )
    original_quit = app.quitOnLastWindowClosed()
    icon = QIcon(str(Path(__file__).parents[1] /
                     "src/boss_timer/resources/icons/app.ico"))
    controller = enable_tray(window, icon)
    window.show()
    app.processEvents()
    yield window, controller
    controller.exiting = True
    window.close()
    controller.icon.hide()
    if controller.owner is not None:
        controller.owner.close()
    window.deleteLater()
    app.setQuitOnLastWindowClosed(original_quit)
    app.processEvents()


def test_close_and_minimize_hide_window_but_keep_timing(tray_window, app, clock):
    window, controller = tray_window
    window._start_boss(window.bosses[0])
    entry = next(iter(window.timers.entries.values()))
    assert not window.close()
    assert not window.isVisible()
    assert window.tick_timer.isActive()
    assert window.settings_store.read()["cleanup_seconds"] == 120
    clock.advance(5)
    window._tick()
    assert entry.id in window.timers.entries
    controller._activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    app.processEvents()
    assert window.isVisible()
    assert not window.isMinimized()
    window.showMinimized()
    app.processEvents()
    app.processEvents()
    assert not window.isVisible()
    assert window.tick_timer.isActive()
    controller.show_window()
    app.processEvents()
    assert window.isVisible()
    assert not window.isMinimized()
    window._set_topmost(False)
    app.processEvents()
    if controller.owner is not None:
        assert window.windowHandle().transientParent() is controller.owner.windowHandle()


def test_tray_exit_saves_settings_and_stops_timers(tray_window, app, monkeypatch):
    window, controller = tray_window
    quit_calls = []
    monkeypatch.setattr(app, "quit", lambda: quit_calls.append(True))
    window.cleanup_seconds_input.setValue(45)
    window.close()
    assert not window.isVisible()
    controller.exit_application()
    assert quit_calls == [True]
    assert not controller.icon.isVisible()
    assert not window.tick_timer.isActive()
    assert window.settings_store.read()["cleanup_seconds"] == 45


def test_failed_save_cancels_tray_exit(tray_window, app, monkeypatch):
    window, controller = tray_window
    quit_calls = []
    monkeypatch.setattr(app, "quit", lambda: quit_calls.append(True))
    errors = []
    monkeypatch.setattr(window, "_error", errors.append)
    original_write = window.settings_store.write

    def fail(_):
        raise StorageError("保存失败")

    monkeypatch.setattr(window.settings_store, "write", fail)
    controller.exit_application()
    assert not quit_calls
    assert errors == ["保存失败"]
    assert not controller.exiting
    assert window.isVisible()
    assert window.tick_timer.isActive()
    assert controller.icon.isVisible()
    monkeypatch.setattr(window.settings_store, "write", original_write)
