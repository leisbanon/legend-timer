from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from boss_timer.repositories.boss_repository import BossRepository
from boss_timer.repositories.json_store import JsonStore, StorageError
from boss_timer.repositories.profile_repository import ProfileRepository
from boss_timer.services.profile_service import ProfileService
from boss_timer.services.timer_service import TimerService
from boss_timer.ui.fonts import configure_application_font
from boss_timer.ui.main_window import MainWindow


def resource_path() -> Path:
    if getattr(sys, "frozen", False):
        # 单文件发布仍使用包内配置，dist 只需保留 BossTimer.exe。
        return Path(sys._MEIPASS) / "boss_config.json"
    return Path(__file__).resolve().parents[2] / "boss_config.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="传奇 BOSS 计时工具")
    parser.add_argument("--data-dir", type=Path, help="指定独立的数据目录")
    parser.add_argument("--smoke-test", type=Path, metavar="PNG", help="以隔离数据启动、截图并自动退出")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setOrganizationName("LegendBossTimer")
    app.setApplicationName("LegendBossTimer")
    app.setApplicationDisplayName("传奇 BOSS 计时工具")
    configure_application_font(app)
    temporary = tempfile.TemporaryDirectory(prefix="boss-timer-smoke-") if args.smoke_test else None
    data_dir = args.data_dir or (Path(temporary.name) if temporary else
                                Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(data_dir / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler],
                            format="%(asctime)s %(levelname)s %(message)s", force=True)
        # 同一数据目录只允许一个实例，防止两个窗口互相覆盖配置。
        lock = QLockFile(str(data_dir / "app.lock"))
        if not lock.tryLock(100):
            QMessageBox.information(None, "传奇 BOSS 计时工具", "程序已在运行，请切换到已有窗口。")
            return 0
        profiles = ProfileService(ProfileRepository(data_dir / "profiles.json"))
        window = MainWindow(BossRepository(data_dir / "boss_catalog.json", resource_path()),
                            profiles, TimerService(), JsonStore(data_dir / "settings.json"))
    except (OSError, StorageError) as exc:
        QMessageBox.critical(None, "启动失败", str(exc))
        return 1

    def exception_hook(exc_type, value, traceback):
        logging.error("未处理的异常", exc_info=(exc_type, value, traceback))
        QMessageBox.critical(window, "操作失败", f"{value}\n\n详细信息已记录到：{data_dir / 'app.log'}")

    sys.excepthook = exception_hook
    window.show()
    smoke_result = [0]
    if args.smoke_test:
        # 只写临时目录；用于发布前验证 Qt 插件、内置配置和实际窗口渲染。
        for boss in window.bosses[:3]:
            window.timers.start(boss)
        entries = list(window.timers.entries.values())
        window.timers.pause(entries[1].id)
        entries[2].deadline = window.timers.clock() - 5
        window._refresh_table()
        window.tree.setCurrentIndex(window.tree_model.boss_items[window.bosses[0].id].index())
        window._select_entry(entries[0].id)
        window.table.setFocus()

        def capture():
            try:
                args.smoke_test.parent.mkdir(parents=True, exist_ok=True)
                if not window.grab().save(str(args.smoke_test)):
                    raise OSError("截图保存失败")
            except OSError:
                logging.exception("发布验证失败")
                smoke_result[0] = 1
            finally:
                window.dirty = False
                window.close()
                app.quit()

        QTimer.singleShot(1000, capture)
    result = app.exec()
    lock.unlock()
    logging.shutdown()
    if temporary:
        temporary.cleanup()
    return smoke_result[0] or result


if __name__ == "__main__":
    raise SystemExit(main())
