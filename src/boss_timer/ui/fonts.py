"""统一应用字号，保留操作系统提供的界面字体。"""

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication


def configure_application_font(app: QApplication) -> None:
    # 只修改字号；字体家族、字重等设置继续使用系统默认值。
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPointSize(10)
    app.setFont(font)
