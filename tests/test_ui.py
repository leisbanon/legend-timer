from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMenu, QPushButton

from boss_timer.app import resource_path
from boss_timer.domain.models import BossDefinition
from boss_timer.repositories.boss_repository import BossRepository
from boss_timer.repositories.json_store import JsonStore
from boss_timer.repositories.profile_repository import ProfileRepository
from boss_timer.services.profile_service import ProfileService
from boss_timer.services.timer_service import TimerService
from boss_timer.ui.dialogs.boss_editor import BossEditorDialog
from boss_timer.ui.dialogs.profile_dialogs import LoadProfileDialog, SaveProfileDialog
from boss_timer.ui.main_window import MainWindow
from boss_timer.ui.models.boss_tree import BossTreeModel


@pytest.fixture
def window(app, tmp_path, clock):
    instance = MainWindow(BossRepository(tmp_path / "bosses.json", resource_path()),
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
    window._start_boss(window.bosses[0])
    window._start_boss(window.bosses[1])
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


def test_save_modify_save_as_and_load_dialog_flow(window, monkeypatch):
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
    assert window.active_profile_id == first_id
    assert len(window.profile_service.profiles) == 1
    assert len(window.profile_service.find(first_id).timers) == 2

    def save_as(dialog):
        dialog.name_edit.setText("另存方案")
        dialog.save_as_new.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SaveProfileDialog, "exec", save_as)
    assert window._save_profile()
    assert window.active_profile_id != first_id
    assert len(window.profile_service.profiles) == 2
    monkeypatch.setattr(LoadProfileDialog, "exec", lambda _: QDialog.DialogCode.Accepted)
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
