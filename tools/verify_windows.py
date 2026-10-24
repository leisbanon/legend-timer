"""生成实际 Windows Qt 窗口截图；所有交互和保存均使用临时数据。"""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtWidgets import QApplication

from boss_timer.app import resource_path
from boss_timer.repositories.boss_repository import BossRepository
from boss_timer.repositories.json_store import JsonStore
from boss_timer.repositories.profile_repository import ProfileRepository
from boss_timer.services.profile_service import ProfileService
from boss_timer.services.timer_service import TimerService
from boss_timer.ui.dialogs.boss_editor import BossEditorDialog
from boss_timer.ui.dialogs.profile_dialogs import LoadProfileDialog, SaveProfileDialog
from boss_timer.ui.fonts import configure_application_font
from boss_timer.ui.main_window import MainWindow
from boss_timer.ui.theme import BLUE, TABLE_ROW_HEIGHT


def verify_selection_fill(window):
    """检查真实渲染像素，覆盖树缩进区域和表格各列的拼接位置。"""
    tree = window.tree
    rect = tree.visualRect(tree.currentIndex())
    tree_image = tree.viewport().grab().toImage()
    scale = tree_image.devicePixelRatio()
    for x in (1, tree.viewport().width() - 2):
        assert tree_image.pixelColor(int(x * scale), int((rect.bottom() - 1) * scale)).name() == BLUE
    table = window.table
    selected_row = table.selectionModel().selectedRows()[0].row()
    assert table.rowHeight(selected_row) == TABLE_ROW_HEIGHT
    image = table.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    for column in range(table.model().columnCount() - 1):
        left = table.visualRect(table.model().index(selected_row, column))
        right = table.visualRect(table.model().index(selected_row, column + 1))
        for x in (left.right(), right.left()):
            assert image.pixelColor(int(x * scale), int(left.center().y() * scale)).name() == BLUE


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts")
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    configure_application_font(app)
    with TemporaryDirectory(prefix="boss-timer-ui-") as directory:
        data = Path(directory)
        window = MainWindow(BossRepository(data / "bosses.json", resource_path()),
                            ProfileService(ProfileRepository(data / "profiles.json")),
                            TimerService(), JsonStore(data / "settings.json"))
        for boss in window.bosses[:3]:
            window.timers.start(boss)
        entries = list(window.timers.entries.values())
        window.timers.pause(entries[1].id)
        entries[2].deadline = window.timers.clock() - 5
        window._refresh_table()
        window.tree.setCurrentIndex(window.tree_model.boss_items[window.bosses[0].id].index())
        window._select_entry(entries[0].id)
        window.show()
        window.table.setFocus()
        app.processEvents()
        verify_selection_fill(window)
        window.grab().save(str(output / "main-window.png"))
        window.resize(980, 580)
        app.processEvents()
        verify_selection_fill(window)
        window.grab().save(str(output / "minimum-window.png"))
        profile = window.profile_service.save("藏剑山庄路线", window.timers.snapshot())
        dialogs = [
            (BossEditorDialog(window.bosses[0], window), "boss-editor.png"),
            (SaveProfileDialog(profile, 3, window), "save-profile.png"),
            (LoadProfileDialog(window.profile_service.profiles, window), "load-profile.png"),
        ]
        for dialog, filename in dialogs:
            dialog.show()
            app.processEvents()
            assert dialog.grab().save(str(output / filename))
            dialog.close()
        window.dirty = False
        window.close()
        app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
