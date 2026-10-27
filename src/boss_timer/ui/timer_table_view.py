"""支持再次点击取消整行选中的计时表格。"""

from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QTableView


class TimerTableView(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hovered_row = -1
        self.setMouseTracking(True)

    def _set_hovered_row(self, row):
        if self.hovered_row != row:
            self.hovered_row = row
            self.viewport().update()

    def mouseMoveEvent(self, event):
        self._set_hovered_row(self.indexAt(event.position().toPoint()).row())
        super().mouseMoveEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.Leave:
            self._set_hovered_row(-1)
        return super().viewportEvent(event)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        position = self.viewport().mapFromGlobal(QCursor.pos())
        self._set_hovered_row(self.indexAt(position).row()
                              if self.viewport().rect().contains(position) else -1)

    def selectionCommand(self, index, event=None):
        if event is not None and event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            if event.button() == Qt.MouseButton.LeftButton:
                flags = QItemSelectionModel.SelectionFlag
                if event.type() == QEvent.Type.MouseButtonRelease:
                    return flags.NoUpdate
                if index.isValid() and self.selectionModel().isRowSelected(
                        index.row(), index.parent()):
                    return flags.Deselect | flags.Rows
                return flags.ClearAndSelect | flags.Rows
        return super().selectionCommand(index, event)
