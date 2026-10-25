from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def show_notice(parent: QWidget | None, title: str, text: str,
                icon: QMessageBox.Icon = QMessageBox.Icon.Information):
    """显示只有中文“确认”按钮的系统消息框。"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(icon)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.button(QMessageBox.StandardButton.Ok).setText("确认")
    return box.exec()


def ask_confirmation(parent: QWidget | None, title: str, text: str,
                     icon: QMessageBox.Icon = QMessageBox.Icon.Question) -> bool:
    """显示统一的中文“确认 / 取消”选择框。"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(icon)
    box.setText(text)
    box.setStandardButtons(
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
    )
    box.button(QMessageBox.StandardButton.Ok).setText("确认")
    box.button(QMessageBox.StandardButton.Cancel).setText("取消")
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    return box.exec() == QMessageBox.StandardButton.Ok
