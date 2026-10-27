"""支持再次点击取消整行选中的计时表格。"""

from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtWidgets import QTableView


class TimerTableView(QTableView):
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
