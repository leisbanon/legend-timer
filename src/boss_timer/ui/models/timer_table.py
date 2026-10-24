from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont

from boss_timer.domain.models import TimerEntry, TimerState
from boss_timer.services.timer_service import TimerService


def format_remaining(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


class TimerTableModel(QAbstractTableModel):
    selectionChanged = Signal()
    HEADERS = ("所在地图", "怪物名称", "下次刷新时间", "剩余时间 ↑")

    def __init__(self, service: TimerService, parent=None):
        super().__init__(parent)
        self.service = service
        self.rows: list[TimerEntry] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        entry = self.rows[index.row()]
        now = self.service.clock()
        state = entry.state(now)
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return entry.map or entry.group or "—"
            if index.column() == 1:
                return entry.name
            if index.column() == 2:
                if state == TimerState.PAUSED:
                    return "已暂停"
                deadline = datetime.fromtimestamp(entry.deadline)
                return deadline.strftime("%H:%M:%S" if deadline.date() == datetime.fromtimestamp(now).date()
                                         else "%m-%d %H:%M:%S")
            return format_remaining(entry.display_seconds(now))
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return Qt.CheckState.Checked if entry.selected else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ForegroundRole:
            if state == TimerState.EXPIRED:
                return QColor("#c00000")
            if state == TimerState.PAUSED:
                return QColor("#777777")
        if role == Qt.ItemDataRole.FontRole and state == TimerState.EXPIRED:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() >= 2:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ToolTipRole:
            suffix = {
                TimerState.RUNNING: "正在计时；右键可以暂停或删除。",
                TimerState.PAUSED: "剩余时间已冻结；右键选择开启计时。",
                TimerState.EXPIRED: "已刷新；到期 120 秒后自动删除。",
            }[state]
            return (f"{entry.group} / {entry.map}\n{entry.tip}\n{suffix}\n"
                    "行首勾选仅决定是否保存到配置，不影响计时。")
        return None

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            self.rows[index.row()].selected = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
            self.dataChanged.emit(index, index, [role])
            self.selectionChanged.emit()
            return True
        return False

    def refresh(self) -> bool:
        rows = self.service.sorted_entries()
        order_changed = [e.id for e in rows] != [e.id for e in self.rows]
        if order_changed:
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()
        elif rows:
            self.rows = rows
            self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, 3))
        return order_changed
