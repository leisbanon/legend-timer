"""托盘入口及主窗口的后台运行行为。"""

import logging
import sys

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget


logger = logging.getLogger(__name__)


class TrayController(QObject):
    def __init__(self, window, icon: QIcon):
        super().__init__(window)
        self.window = window
        self.exiting = False
        self.owner = None
        if sys.platform == "win32":
            # 隐藏的所有者使主窗口不占用任务栏，同时保留普通窗口标题栏。
            self.owner = QWidget(None, Qt.WindowType.Tool)
            self.owner.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
            self.owner.winId()
            self.bind_owner()
        self.menu = QMenu(window)
        self.menu.addAction("显示窗口", self.show_window)
        self.menu.addAction("隐藏窗口", window.hide)
        self.menu.addSeparator()
        self.menu.addAction("退出程序", self.exit_application)
        self.icon = QSystemTrayIcon(icon, self)
        self.icon.setToolTip("传奇 BOSS 计时工具")
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        window.installEventFilter(self)
        self.icon.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def bind_owner(self):
        if self.owner is not None:
            self.window.winId()
            self.window.windowHandle().setTransientParent(self.owner.windowHandle())

    def eventFilter(self, watched, event):
        if watched is self.window:
            if event.type() == QEvent.Type.Show:
                self.bind_owner()
            elif event.type() == QEvent.Type.WindowStateChange and self.window.isMinimized():
                QTimer.singleShot(0, self._hide_minimized)
        return False

    def _hide_minimized(self):
        if self.window.isMinimized() and not self.exiting:
            self.window.hide()

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()

    def show_window(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def exit_application(self):
        self.exiting = True
        if not self.window.close():
            self.exiting = False
            self.show_window()
            return
        self.icon.hide()
        if self.owner is not None:
            self.owner.close()
        QApplication.instance().quit()


def enable_tray(window, icon: QIcon):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        logger.warning("系统托盘不可用，保留普通窗口模式")
        return None
    controller = TrayController(window, icon)
    window.tray_controller = controller
    return controller
