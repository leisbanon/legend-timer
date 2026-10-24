from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel

from boss_timer.domain.models import BossDefinition


class BossTreeModel(QStandardItemModel):
    checkedChanged = Signal()
    BOSS_ROLE = Qt.ItemDataRole.UserRole + 1
    NODE_ROLE = Qt.ItemDataRole.UserRole + 2

    def __init__(self, bosses: list[BossDefinition], parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["地图 / BOSS"])
        self.boss_items: dict[str, QStandardItem] = {}
        self.nodes: dict[str, QStandardItem] = {}
        groups: dict[str, QStandardItem] = {}
        maps: dict[tuple[str, str], QStandardItem] = {}
        root = self.invisibleRootItem()
        for boss in bosses:
            parent_item = root
            if boss.group:
                if boss.group not in groups:
                    groups[boss.group] = self._category(boss.group, f"group:{boss.group}", root)
                parent_item = groups[boss.group]
            if boss.map:
                key = (boss.group, boss.map)
                if key not in maps:
                    maps[key] = self._category(boss.map, f"map:{boss.group}/{boss.map}", parent_item)
                parent_item = maps[key]
            item = QStandardItem(boss.name)
            item.setEditable(False)
            item.setCheckable(True)
            item.setCheckState(Qt.CheckState.Checked if boss.armed else Qt.CheckState.Unchecked)
            item.setData(boss.id, self.BOSS_ROLE)
            parent_item.appendRow(item)
            self.boss_items[boss.id] = item
            self.update_boss(boss)
        self._recompute(root)
        # 只监听复选框角色，文字和提示变化不能触发勾选传播。
        self.dataChanged.connect(self._on_data_changed)

    def _category(self, text: str, key: str, parent: QStandardItem) -> QStandardItem:
        item = QStandardItem(text)
        item.setEditable(False)
        item.setCheckable(True)
        item.setData(key, self.NODE_ROLE)
        parent.appendRow(item)
        self.nodes[key] = item
        return item

    def _recompute(self, parent: QStandardItem) -> None:
        for row in range(parent.rowCount()):
            child = parent.child(row)
            if child.rowCount():
                self._recompute(child)
                self._set_parent_state(child)

    @staticmethod
    def _set_parent_state(item: QStandardItem) -> None:
        states = {item.child(row).checkState() for row in range(item.rowCount())}
        item.setCheckState(states.pop() if len(states) == 1 else Qt.CheckState.PartiallyChecked)

    def _on_data_changed(self, top_left, bottom_right, roles) -> None:
        if roles and Qt.ItemDataRole.CheckStateRole not in roles:
            return
        if top_left != bottom_right:
            return
        item = self.itemFromIndex(top_left)
        if item is None or not item.isCheckable():
            return
        with QSignalBlocker(self):
            if item.rowCount():
                state = (Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Unchecked
                         else Qt.CheckState.Checked)
                self._propagate(item, state)
            parent = item.parent()
            while parent is not None:
                self._set_parent_state(parent)
                parent = parent.parent()
        self.checkedChanged.emit()

    def _propagate(self, item: QStandardItem, state: Qt.CheckState) -> None:
        item.setCheckState(state)
        for row in range(item.rowCount()):
            self._propagate(item.child(row), state)

    def checked_ids(self) -> set[str]:
        return {boss_id for boss_id, item in self.boss_items.items()
                if item.checkState() == Qt.CheckState.Checked}

    def update_boss(self, boss: BossDefinition) -> None:
        item = self.boss_items[boss.id]
        with QSignalBlocker(self):
            item.setText(boss.name)
            item.setToolTip(
                f"{boss.group} / {boss.map}\n刷新：{boss.sec} 秒\n提示：{boss.tip}\n"
                "双击编辑，右键开始计时"
            )
