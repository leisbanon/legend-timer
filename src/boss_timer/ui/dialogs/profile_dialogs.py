from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QAbstractItemView,
)

from boss_timer.domain.models import Profile
from boss_timer.repositories.json_store import StorageError
from boss_timer.ui.messages import show_notice
from boss_timer.ui.theme import configure_table_appearance


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
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(80)
        self.name_edit.setPlaceholderText("请输入配置名称")
        form.addRow("配置名称：", self.name_edit)
        layout.addLayout(form)
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
    def __init__(self, profiles: list[Profile], parent=None, *, delete_profile=None):
        super().__init__(parent)
        self.delete_profile = delete_profile
        self.setWindowTitle("加载配置")
        self.resize(460, 300)
        self.profiles = sorted(profiles, key=lambda p: p.updated_at, reverse=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("选择配置后加载，右侧列表将替换为所选配置。"))
        self.table = QTableWidget(len(profiles), 2)
        self.table.setHorizontalHeaderLabels(["配置名称", "计时数量"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.verticalHeader().hide()
        configure_table_appearance(self.table)
        header = self.table.horizontalHeader()
        header_font = header.font()
        header_font.setBold(False)
        header.setFont(header_font)
        header.setStyleSheet("QHeaderView::section { font-weight: normal; }")
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, profile in enumerate(self.profiles):
            cells = [profile.name, str(len(profile.timers))]
            for column, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setToolTip(f"配置 ID：{profile.id}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
        layout.addWidget(self.table)
        buttons = dialog_buttons(self, "加载")
        self.load_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._accept)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(profiles))
        layout.addWidget(buttons)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._accept())
        if profiles:
            self.table.selectRow(0)

    def _context_menu(self, position):
        index = self.table.indexAt(position)
        if not index.isValid() or self.delete_profile is None:
            return
        self.table.selectRow(index.row())
        profile_id = self.profiles[index.row()].id
        menu = QMenu(self)
        action = menu.addAction("删除配置")
        action.triggered.connect(lambda: self._delete_profile(profile_id))
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _delete_profile(self, profile_id):
        row = next((i for i, p in enumerate(self.profiles) if p.id == profile_id), None)
        if row is None or self.delete_profile is None:
            return
        try:
            self.delete_profile(profile_id)
        except (StorageError, OSError) as exc:
            show_notice(self, "删除失败", str(exc), QMessageBox.Icon.Warning)
            return
        self.profiles.pop(row)
        self.table.removeRow(row)
        self.load_button.setEnabled(bool(self.profiles))
        if self.profiles:
            self.table.selectRow(min(row, len(self.profiles) - 1))

    def _accept(self):
        if self.table.currentRow() >= 0:
            self.accept()

    def selected_profile(self) -> Profile:
        return self.profiles[self.table.currentRow()]
