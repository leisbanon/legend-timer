from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QAbstractItemView,
)

from boss_timer.domain.models import Profile
from boss_timer.ui.theme import configure_checkbox_appearance, configure_table_appearance


def dialog_buttons(parent, accept_text: str) -> QDialogButtonBox:
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(accept_text)
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
    buttons.rejected.connect(parent.reject)
    return buttons


class SaveProfileDialog(QDialog):
    def __init__(self, current: Profile | None, count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("保存配置")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(QLabel(f"将保存右侧已勾选的 {count} 条计时。"))
        form = QFormLayout()
        self.name_edit = QLineEdit(current.name if current else "")
        self.name_edit.setMaxLength(80)
        self.name_edit.setPlaceholderText("请输入配置名称")
        form.addRow("配置名称：", self.name_edit)
        layout.addLayout(form)
        self.save_as_new = QCheckBox("另存为新配置（生成新的 ID）")
        configure_checkbox_appearance(self.save_as_new)
        self.save_as_new.setVisible(current is not None)
        layout.addWidget(self.save_as_new)
        mode = QLabel("当前为修改操作，默认更新原配置。" if current else "当前为新增操作。")
        layout.addWidget(mode)
        self.save_as_new.toggled.connect(
            lambda checked: mode.setText("当前为新增操作，请使用新的配置名称。" if checked else "当前为修改操作，默认更新原配置。")
        )
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = dialog_buttons(self, "保存")
        buttons.accepted.connect(self._accept)
        layout.addWidget(buttons)
        self.name_edit.selectAll()

    def _accept(self):
        if not self.name_edit.text().strip():
            self.error_label.setText("请输入配置名称。")
            return
        self.accept()


class LoadProfileDialog(QDialog):
    def __init__(self, profiles: list[Profile], parent=None):
        super().__init__(parent)
        self.setWindowTitle("加载配置")
        self.resize(800, 430)
        self.profiles = sorted(profiles, key=lambda p: p.updated_at, reverse=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("选择配置后加载，右侧列表将替换为所选配置。"))
        self.table = QTableWidget(len(profiles), 3)
        self.table.setHorizontalHeaderLabels(["配置名称", "计时数量", "修改时间"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        configure_table_appearance(self.table)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for row, profile in enumerate(self.profiles):
            cells = [profile.name, str(len(profile.timers)),
                     datetime.fromtimestamp(profile.updated_at).strftime("%Y-%m-%d %H:%M:%S")]
            for column, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setToolTip(f"配置 ID：{profile.id}")
                if column == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
        layout.addWidget(self.table)
        buttons = dialog_buttons(self, "加载")
        buttons.accepted.connect(self._accept)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(profiles))
        layout.addWidget(buttons)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._accept())
        if profiles:
            self.table.selectRow(0)

    def _accept(self):
        if self.table.currentRow() >= 0:
            self.accept()

    def selected_profile(self) -> Profile:
        return self.profiles[self.table.currentRow()]
