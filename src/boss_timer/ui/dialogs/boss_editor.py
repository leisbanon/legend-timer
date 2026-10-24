from dataclasses import replace

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
)

from boss_timer.domain.models import BossDefinition


class BossEditorDialog(QDialog):
    def __init__(self, boss: BossDefinition, parent=None):
        super().__init__(parent)
        self.boss = boss
        self.setWindowTitle("编辑 BOSS 信息")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        location = QLabel(" / ".join(filter(None, [boss.group, boss.map])))
        location.setWordWrap(True)
        layout.addWidget(location)
        form = QFormLayout()
        form.setVerticalSpacing(14)
        self.name_edit = QLineEdit(boss.name)
        self.name_edit.setMaxLength(100)
        self.seconds_edit = QSpinBox()
        self.seconds_edit.setRange(1, 2_147_483_647)
        self.seconds_edit.setValue(max(1, boss.sec))
        self.seconds_edit.setKeyboardTracking(False)
        self.tip_edit = QLineEdit(boss.tip)
        self.tip_edit.setMaxLength(300)
        form.addRow("BOSS 名称：", self.name_edit)
        form.addRow("刷新时间（秒）：", self.seconds_edit)
        form.addRow("显示提示文本：", self.tip_edit)
        layout.addLayout(form)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name_edit.selectAll()

    def _accept(self):
        if not self.name_edit.text().strip():
            self.error_label.setText("请输入 BOSS 名称。")
            self.name_edit.setFocus()
            return
        self.accept()

    def definition(self) -> BossDefinition:
        name = self.name_edit.text().strip()
        return replace(self.boss, name=name, sec=self.seconds_edit.value(),
                       tip=self.tip_edit.text().strip() or name)
