from dataclasses import replace

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QShowEvent
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
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = ok_button
        self.cancel_button = cancel_button
        ok_button.setText("确认")
        cancel_button.setText("取消")
        # QDialogButtonBox 默认会把“确定”设为默认按钮并绘制强调色边框。
        for button in (ok_button, cancel_button):
            button.setAutoDefault(False)
            button.setDefault(False)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # 焦点停留在弹窗本身；用户点击具体控件后再显示其焦点状态。
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        # exec() 建立模态事件循环时可能重新分配默认焦点，显示后再清除一次。
        QTimer.singleShot(0, self._focus_dialog)

    def _focus_dialog(self):
        self.ok_button.setDefault(False)
        self.cancel_button.setDefault(False)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

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
