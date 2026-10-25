import base64
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMenu, QMessageBox, QPushButton

from boss_timer.app import resource_path
from boss_timer.domain.models import BossDefinition
from boss_timer.repositories.boss_repository import BossRepository
from boss_timer.repositories.json_store import JsonStore
from boss_timer.repositories.profile_repository import ProfileRepository
from boss_timer.services.profile_service import ProfileService
from boss_timer.services.timer_service import TimerService
from boss_timer.ui.dialogs.boss_editor import BossEditorDialog
from boss_timer.ui.dialogs.profile_dialogs import LoadProfileDialog, SaveProfileDialog
from boss_timer.ui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MINIMUM_WINDOW_HEIGHT,
    MINIMUM_WINDOW_WIDTH,
    MainWindow,
)
from boss_timer.ui.models.boss_tree import BossTreeModel


@pytest.fixture
def window(app, tmp_path, clock):
    instance = MainWindow(BossRepository(tmp_path / "boss_catalog.json", resource_path()),
                          ProfileService(ProfileRepository(tmp_path / "profiles.json"), clock),
                          TimerService(clock), JsonStore(tmp_path / "settings.json"))
    instance.show()
    app.processEvents()
    yield instance
    instance.dirty = False
    instance.close()
    app.processEvents()


def button(window, text):
    return next(b for b in window.findChildren(QPushButton) if b.text() == text)


def test_delete_profile_by_id_preserves_same_name_and_current_timers(window):
    window._start_boss(window.bosses[0])
    payload = window.timers.snapshot()
    first = window.profile_service.save("同名配置", payload)
    second = window.profile_service.save("同名配置", payload)
    window.active_profile_id = first.id
    dialog = LoadProfileDialog(window.profile_service.profiles, window,
                               delete_profile=window._delete_profile)
    dialog._delete_profile(first.id)
    assert [p.id for p in dialog.profiles] == [second.id]
    assert [p.id for p in window.profile_service.repository.load()] == [second.id]
    assert window.active_profile_id is None
    assert window.timers.snapshot() == payload
    dialog._delete_profile(second.id)
    assert dialog.table.rowCount() == 0
    assert not dialog.load_button.isEnabled()
    assert window.profile_service.repository.load() == []
    dialog.close()


def test_startup_uses_compact_normal_window_even_after_maximized_session(
        window, app, tmp_path, clock):
    window.showMaximized()
    app.processEvents()
    window.settings_store.write({
        "geometry": base64.b64encode(bytes(window.saveGeometry())).decode("ascii"),
        "splitter": [300, 600],
        "expanded": [],
    })

    restored = MainWindow(
        BossRepository(tmp_path / "other_catalog.json", resource_path()),
        ProfileService(ProfileRepository(tmp_path / "other_profiles.json"), clock),
        TimerService(clock),
        window.settings_store,
    )
    restored.show()
    app.processEvents()
    try:
        assert not restored.isMaximized()
        assert not restored.isFullScreen()
        assert restored.width() == DEFAULT_WINDOW_WIDTH
        assert restored.height() == DEFAULT_WINDOW_HEIGHT
        assert restored.minimumWidth() == MINIMUM_WINDOW_WIDTH
        assert restored.minimumHeight() == MINIMUM_WINDOW_HEIGHT
    finally:
        restored.dirty = False
        restored.close()
        app.processEvents()


def test_double_click_timer_confirms_restart_without_duplicates(window, app, clock, monkeypatch):
    window._start_boss(replace(window.bosses[0], sec=60))
    entry = window.table_model.rows[0]
    clock.advance(10)
    window._pause_entry(entry.id)
    original_remaining = entry.paused_remaining
    index = window.table_model.index(0, 0)
    position = window.table.visualRect(index).center()
    monkeypatch.setattr(QMessageBox, "exec", lambda _: QMessageBox.StandardButton.Cancel)
    QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QTest.mouseDClick(window.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert entry.paused_remaining == original_remaining

    def confirm(_):
        clock.advance(3)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", confirm)
    QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QTest.mouseDClick(window.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    app.processEvents()
    assert entry.deadline == clock() + 60
    assert entry.paused_remaining is None
    assert len(window.timers.entries) == 1
    assert window.dirty


def test_reset_defaults_requires_confirmation_and_restores_disk_and_ui(window, app, tmp_path, monkeypatch):
    defaults_bytes = resource_path().read_bytes()
    default_boss = window.bosses[0]
    window.bosses[0] = replace(default_boss, sec=17, name="本地改名")
    window.boss_repository.save(window.bosses)
    window.boss_repository.save(window.bosses)  # 同时产生旧备份。
    window._start_boss(window.bosses[0])
    window.profile_service.save("旧方案", window.timers.snapshot())
    window.settings_store.write({"expanded": [], "splitter": [500, 500]})
    legacy = tmp_path / "LegendBossTimer"
    JsonStore(legacy / "boss_catalog.json").write({"timers": []})
    window.legacy_data_dir = legacy
    window._toggle_remaining_sort(3)
    window.tree_model.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert window.catalog_save_timer.isActive()

    monkeypatch.setattr(QMessageBox, "exec", lambda _: QMessageBox.StandardButton.Cancel)
    QTest.mouseClick(button(window, "恢复默认配置"), Qt.MouseButton.LeftButton)
    assert window.timers.entries
    assert window.profile_service.profiles

    monkeypatch.setattr(QMessageBox, "exec", lambda _: QMessageBox.StandardButton.Ok)
    QTest.mouseClick(button(window, "恢复默认配置"), Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.bosses[0] == default_boss
    assert not window.catalog_save_timer.isActive()
    assert not window.catalog_dirty
    assert not window.dirty
    assert window.active_profile_id is None
    assert window.table_model.rowCount() == 0
    assert not window.timers.entries
    assert not window.profile_service.profiles
    assert window.profile_service.repository.load() == []
    assert window.boss_repository.load()[0] == default_boss
    assert window.table_model.remaining_sort_order == Qt.SortOrder.AscendingOrder
    assert all(not window.tree.isExpanded(item.index())
               for item in window.tree_model.nodes.values())
    assert not (legacy / "boss_catalog.json").exists()
    assert not list(tmp_path.rglob("*.json.bak"))
    assert resource_path().read_bytes() == defaults_bytes
    # 恢复后仍可以勾选、保存到本地，根目录默认文件不被改变。
    window.tree_model.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert window._persist_catalog()
    assert resource_path().read_bytes() == defaults_bytes


def test_tree_hierarchy_checkbox_propagation_and_absent_levels(app):
    model = BossTreeModel([
        BossDefinition("a", "分类", "地图", "甲", 10, "甲"),
        BossDefinition("b", "分类", "地图", "乙", 10, "乙"),
        BossDefinition("c", "", "", "直接挂载", 10, "直接挂载"),
    ])
    assert model.rowCount() == 2
    changed_indexes = []
    model.dataChanged.connect(
        lambda top_left, _bottom_right, _roles: changed_indexes.append(top_left)
    )
    group = model.item(0)
    group.setCheckState(Qt.CheckState.Unchecked)
    assert model.checked_ids() == {"c"}
    assert model.boss_items["a"].index() in changed_indexes
    assert model.boss_items["b"].index() in changed_indexes
    assert all(group.child(row).checkState() == Qt.CheckState.Unchecked
               for row in range(group.rowCount()))
    changed_indexes.clear()
    group.setCheckState(Qt.CheckState.Checked)
    assert model.checked_ids() == {"a", "b", "c"}
    assert model.boss_items["a"].index() in changed_indexes
    assert model.boss_items["b"].index() in changed_indexes
    map_item = group.child(0)
    map_item.setCheckState(Qt.CheckState.Unchecked)
    assert model.checked_ids() == {"c"}
    map_item.setCheckState(Qt.CheckState.Checked)
    assert model.checked_ids() == {"a", "b", "c"}
    model.boss_items["a"].setCheckState(Qt.CheckState.Unchecked)
    assert map_item.checkState() == Qt.CheckState.PartiallyChecked
    assert group.checkState() == Qt.CheckState.PartiallyChecked
    assert model.checked_ids() == {"b", "c"}


def test_starting_map_node_adds_checked_bosses_without_restarting_duplicates(window):
    first = window.bosses[0]
    map_item = window.tree_model.nodes[f"map:{first.group}/{first.map}"]
    descendants = window._bosses_below(map_item.index())
    assert len(descendants) > 1
    unchecked = descendants[-1]
    window.tree_model.boss_items[unchecked.id].setCheckState(Qt.CheckState.Unchecked)
    window._start_boss(descendants[0])
    existing = next(iter(window.timers.entries.values()))
    original_deadline = existing.deadline

    window._start_map_bosses(map_item.index())

    assert existing.deadline == original_deadline
    assert {entry.boss_id for entry in window.timers.entries.values()} == {
        boss.id for boss in descendants if boss.sec > 0 and boss.id != unchecked.id
    }
    assert window.dirty


def test_native_editor_validation_and_only_requested_fields(app):
    boss = BossDefinition("one", "野外地图", "藏剑山庄", "雷炎蛛王", 1800, "雷炎蛛王")
    dialog = BossEditorDialog(boss)
    dialog.show()
    app.processEvents()
    assert dialog.name_edit.selectedText() == ""
    assert dialog.focusWidget() is dialog
    buttons = dialog.findChild(QDialogButtonBox)
    assert not buttons.button(QDialogButtonBox.StandardButton.Ok).isDefault()
    assert not buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault()
    dialog.name_edit.setText(" ")
    dialog._accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.name_edit.setText("新怪物")
    dialog.seconds_edit.setValue(90)
    dialog.tip_edit.setText("刷新提示")
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.definition() == replace(boss, name="新怪物", sec=90, tip="刷新提示")


def test_tree_double_click_edits_only_boss_text(window, app, monkeypatch):
    item = window.tree_model.boss_items[window.bosses[0].id]
    parent = item.parent()
    while parent is not None:
        window.tree.expand(parent.index())
        parent = parent.parent()
    app.processEvents()

    opened = []

    def reject_editor(_dialog):
        opened.append(True)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(BossEditorDialog, "exec", reject_editor)
    index = item.index()
    QTest.mouseDClick(window.tree.viewport(), Qt.MouseButton.LeftButton,
                       pos=window._tree_check_rect(index).center())
    app.processEvents()
    assert opened == []

    QTest.mouseDClick(window.tree.viewport(), Qt.MouseButton.LeftButton,
                       pos=window._tree_text_rect(index).center())
    app.processEvents()
    assert opened == [True]

    blank_position = window.tree.visualRect(index).center()
    if window._tree_text_rect(index).contains(blank_position):
        blank_position.setX(window.tree.visualRect(index).right() - 8)
    QTest.mouseDClick(window.tree.viewport(), Qt.MouseButton.LeftButton,
                       pos=blank_position)
    app.processEvents()
    assert opened == [True, True]


def test_collapsing_tree_parent_clears_descendant_expansion(window, app):
    group = next(item for key, item in window.tree_model.nodes.items()
                 if key.startswith("group:"))
    child = next(group.child(row) for row in range(group.rowCount())
                 if group.child(row).rowCount())
    window.tree.expand(group.index())
    window.tree.expand(child.index())
    app.processEvents()
    assert window.tree.isExpanded(group.index())
    assert window.tree.isExpanded(child.index())

    window.tree.collapse(group.index())
    app.processEvents()
    assert not window.tree.isExpanded(group.index())
    assert not window.tree.isExpanded(child.index())

    window.tree.expand(group.index())
    app.processEvents()
    assert not window.tree.isExpanded(child.index())


def test_double_clicking_category_row_toggles_expansion(window, app):
    group = next(item for key, item in window.tree_model.nodes.items()
                 if key.startswith("group:"))
    index = group.index()
    window.tree.collapse(index)
    app.processEvents()
    position = window._tree_text_rect(index).center()

    QTest.mouseDClick(window.tree.viewport(), Qt.MouseButton.LeftButton, pos=position)
    app.processEvents()
    assert window.tree.isExpanded(index)

    QTest.mouseDClick(window.tree.viewport(), Qt.MouseButton.LeftButton, pos=position)
    app.processEvents()
    assert not window.tree.isExpanded(index)


def test_start_pause_resume_expire_and_save_all(window, app, clock):
    # 使用固定间隔，避免用户修改默认秒数后影响暂停/恢复测试。
    window._start_boss(replace(window.bosses[0], sec=1800))
    window._start_boss(replace(window.bosses[1], sec=1800))
    assert window.table_model.rowCount() == 2
    entry = window.table_model.rows[0]
    window._pause_entry(entry.id)
    remaining = entry.remaining(clock())
    clock.advance(300)
    window._tick()
    assert entry.remaining(clock()) == remaining
    assert any(window.table_model.data(window.table_model.index(row, 2)) == "已暂停" for row in range(2))
    window._resume_entry(entry.id)
    assert len(window.timers.snapshot()) == 2
    entry.deadline = clock() - 5
    window._tick()
    row = next(i for i, e in enumerate(window.table_model.rows) if e.id == entry.id)
    assert row == 0
    assert window.table_model.data(window.table_model.index(row, 3)) == "00:00"
    assert window.table_model.data(window.table_model.index(row, 3), Qt.ItemDataRole.ForegroundRole).name() == "#c00000"
    clock.advance(115)
    window._tick()
    assert entry.id not in window.timers.entries


def test_remaining_header_toggles_sort_direction(window, app):
    window._start_boss(window.bosses[0])
    window._start_boss(window.bosses[1])
    window.table_model.refresh()
    ascending = [entry.id for entry in window.table_model.rows]

    header = window.table.horizontalHeader()
    x = header.sectionViewportPosition(3) + header.sectionSize(3) // 2
    QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(x, 5))
    app.processEvents()
    assert window.table_model.remaining_sort_order == Qt.SortOrder.DescendingOrder
    assert [entry.id for entry in window.table_model.rows] == list(reversed(ascending))

    QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(x, 5))
    app.processEvents()
    assert window.table_model.remaining_sort_order == Qt.SortOrder.AscendingOrder
    assert [entry.id for entry in window.table_model.rows] == ascending


def test_save_always_creates_new_profile_and_load_dialog_flow(window, monkeypatch):
    window._start_boss(window.bosses[0])

    def first_save(dialog):
        dialog.name_edit.setText("测试方案")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SaveProfileDialog, "exec", first_save)
    QTest.mouseClick(button(window, "保存配置"), Qt.MouseButton.LeftButton)
    first_id = window.active_profile_id
    assert first_id and not window.dirty
    window._start_boss(window.bosses[1])
    assert window._save_profile()
    assert window.active_profile_id != first_id
    assert len(window.profile_service.profiles) == 2
    assert len(window.profile_service.find(first_id).timers) == 1

    def save_as(dialog):
        dialog.name_edit.setText("另存方案")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SaveProfileDialog, "exec", save_as)
    assert window._save_profile()
    assert window.active_profile_id != first_id
    assert len(window.profile_service.profiles) == 3
    def load_latest(dialog):
        dialog.table.selectRow(next(
            row for row, profile in enumerate(dialog.profiles)
            if profile.id == window.active_profile_id
        ))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LoadProfileDialog, "exec", load_latest)
    window._load_profile()
    assert len(window.timers.entries) == 2
    assert not window.dirty


def test_context_menu_changes_with_state(window, app):
    window._start_boss(window.bosses[0])
    observed = []

    def run_menu():
        menu = app.activePopupWidget()
        assert isinstance(menu, QMenu)
        observed.extend(a.text() for a in menu.actions() if not a.isSeparator())
        menu.close()

    position = window.table.visualRect(window.table_model.index(0, 0)).center()
    QTimer.singleShot(0, run_menu)
    window._table_context_menu(position)
    assert observed == ["删除计时", "暂停计时"]
    entry = window.table_model.rows[0]
    window._pause_entry(entry.id)
    observed.clear()
    QTimer.singleShot(0, run_menu)
    window._table_context_menu(position)
    assert observed == ["删除计时", "开启计时"]


def test_all_buttons_and_close_without_save_prompt(window, app, monkeypatch):
    # 左侧即使全部勾选，批量开始也不能向空表格添加任何项目。
    for row in range(window.tree_model.rowCount()):
        window.tree_model.item(row).setCheckState(Qt.CheckState.Checked)
    QTest.mouseClick(button(window, "全部开始"), Qt.MouseButton.LeftButton)
    assert len(window.timers.entries) == 0
    window._start_boss(window.bosses[0])
    original_deadline = next(iter(window.timers.entries.values())).deadline
    QTest.mouseClick(button(window, "全部开始"), Qt.MouseButton.LeftButton)
    assert len(window.timers.entries) == 1
    assert next(iter(window.timers.entries.values())).deadline == original_deadline
    QTest.mouseClick(button(window, "全部暂停"), Qt.MouseButton.LeftButton)
    assert next(iter(window.timers.entries.values())).paused_remaining is not None
    QTest.mouseClick(button(window, "全部开始"), Qt.MouseButton.LeftButton)
    assert len(window.timers.entries) == 1
    assert next(iter(window.timers.entries.values())).paused_remaining is None
    def unexpected_confirmation():
        raise AssertionError("关闭窗口不应询问保存计时方案")

    monkeypatch.setattr(window, "_confirm_discard", unexpected_confirmation)
    assert window.dirty
    assert window.close()
    assert not window.isVisible()
    assert not window.tick_timer.isActive()
    assert window.profile_service.profiles == []
    assert bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) is \
        window.boss_repository.window_topmost()
    assert "topmost" not in window.settings_store.read()
    assert not window.catalog_dirty


def test_edit_is_saved_and_keeps_deadline(window, monkeypatch):
    definition = window.bosses[0]
    window._start_boss(definition)
    entry = next(iter(window.timers.entries.values()))
    original_deadline = entry.deadline

    def edit(dialog):
        dialog.name_edit.setText("编辑测试 BOSS")
        dialog.seconds_edit.setValue(90)
        dialog.tip_edit.setText("刷新提醒")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BossEditorDialog, "exec", edit)
    window._edit_boss(window.tree_model.boss_items[definition.id].index())
    assert entry.name == "编辑测试 BOSS"
    assert entry.deadline == original_deadline
    assert window.boss_repository.load()[0].sec == 90
    assert window.tree_model.boss_items[definition.id].text() == "编辑测试 BOSS"


def test_load_reads_latest_profile_after_save_before_replace(window, monkeypatch):
    window._start_boss(window.bosses[0])
    profile = window.profile_service.save("当前方案", window.timers.snapshot())
    window.active_profile_id = profile.id
    monkeypatch.setattr(LoadProfileDialog, "exec", lambda _: QDialog.DialogCode.Accepted)

    def save_before_load():
        window._start_boss(window.bosses[1])
        window.profile_service.save(profile.name, window.timers.snapshot(), profile.id)
        return True

    monkeypatch.setattr(window, "_confirm_discard", save_before_load)
    window._load_profile()
    assert len(window.timers.entries) == 2
