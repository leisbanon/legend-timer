"""根据可用宽度自动换行，保持控件的原生尺寸。"""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QWidgetItem


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, widget, alignment=Qt.AlignmentFlag(0)):
        self.addChildWidget(widget)
        item = QWidgetItem(widget)
        item.setAlignment(alignment)
        self.addItem(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < self.count() else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < self.count() else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), False)

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def sizeHint(self):
        return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, True)

    def _arrange(self, rect, apply):
        rows = []
        row, row_width = [], 0
        for item in self._items:
            size = item.sizeHint()
            spacing = self.spacing() if row else 0
            if (row and item.alignment() & Qt.AlignmentFlag.AlignRight
                    and row[-1][0].alignment() & Qt.AlignmentFlag.AlignRight):
                spacing = 3
            if row and row_width + spacing + size.width() > rect.width():
                rows.append((row, row_width))
                row, row_width, spacing = [], 0, 0
            row.append((item, size, spacing))
            row_width += spacing + size.width()
        if row:
            rows.append((row, row_width))

        y = rect.y()
        for row, row_width in rows:
            x = rect.x()
            remaining = max(0, rect.width() - row_width)
            row_height = max(size.height() for _, size, _ in row)
            for item, size, spacing in row:
                x += spacing
                # 同行的提示保持靠左，按钮前的剩余空间将整组推向右侧。
                if item.alignment() & Qt.AlignmentFlag.AlignRight:
                    x += remaining
                    remaining = 0
                if apply:
                    item.setGeometry(QRect(
                        x, y + (row_height - size.height()) // 2,
                        size.width(), size.height(),
                    ))
                x += size.width()
            y += row_height + self.spacing()
        return y - rect.y() - (self.spacing() if rows else 0)
