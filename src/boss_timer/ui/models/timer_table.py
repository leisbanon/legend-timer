from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from boss_timer.domain.models import TimerEntry, TimerState
from boss_timer.services.timer_service import TimerService


def format_remaining(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


class TimerTableModel(QAbstractTableModel):
    HEADERS = ("所在地图", "怪物名称", "下次刷新时间", "剩余时间")

    def __init__(self, service: TimerService, parent=None):
        super().__init__(parent)
        self.service = service
        self.rows: list[TimerEntry] = []
        self.remaining_sort_order = Qt.SortOrder.AscendingOrder

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if section == 3:
                arrow = "↑" if self.remaining_sort_order == Qt.SortOrder.AscendingOrder else "↓"
                return f"剩余时间 {arrow}"
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
        if role == Qt.ItemDataRole.ForegroundRole:
            if state == TimerState.EXPIRED:
                return QColor("#c00000")
            if state == TimerState.PAUSED:
                return QColor("#777777")
        if role == Qt.ItemDataRole.FontRole and state == TimerState.EXPIRED:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ToolTipRole:
            suffix = {
                TimerState.RUNNING: "正在计时；右键可以暂停或删除。",
                TimerState.PAUSED: "剩余时间已冻结；右键选择开启计时。",
                TimerState.EXPIRED: "已刷新；到期 120 秒后自动删除。",
            }[state]
            return f"{entry.group} / {entry.map}\n{entry.tip}\n{suffix}"
        return None

    def refresh(self) -> bool:
        rows = self.service.sorted_entries()
        if self.remaining_sort_order == Qt.SortOrder.DescendingOrder:
            rows.reverse()
        order_changed = [e.id for e in rows] != [e.id for e in self.rows]
        if order_changed:
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()
        elif rows:
            self.rows = rows
            self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, 3))
        return order_changed

    def set_remaining_sort_order(self, order: Qt.SortOrder) -> None:
        if order == self.remaining_sort_order:
            return
        self.remaining_sort_order = order
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 3, 3)
        self.refresh()
