from __future__ import annotations

import base64
import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QCloseEvent, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMenu, QMessageBox, QPushButton, QSpinBox, QSplitter, QStyle,
    QStyleOptionViewItem, QTableView, QTreeView, QVBoxLayout, QWidget,
)

from boss_timer.domain.models import BossDefinition, TimerState
from boss_timer.repositories.boss_repository import BossRepository
from boss_timer.repositories.json_store import JsonStore, StorageError
from boss_timer.services.profile_service import ProfileService
from boss_timer.services.timer_service import DuplicateBossError, TimerError, TimerService
from boss_timer.services.local_data import clear_local_config
from boss_timer.ui.dialogs.boss_editor import BossEditorDialog
from boss_timer.ui.dialogs.profile_dialogs import LoadProfileDialog, SaveProfileDialog
from boss_timer.ui.messages import ask_confirmation, show_notice
from boss_timer.ui.models.boss_tree import BossTreeModel
from boss_timer.ui.models.timer_table import TimerTableModel
from boss_timer.ui.theme import (
    configure_checkbox_appearance,
    configure_table_appearance,
    configure_tree_appearance,
)

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_WIDTH = 900
DEFAULT_WINDOW_HEIGHT = 560
MINIMUM_WINDOW_WIDTH = 760
MINIMUM_WINDOW_HEIGHT = 460
DEFAULT_SPLITTER_SIZES = [245, 631]


class MainWindow(QMainWindow):
    """负责视图连接；计时与保存规则交给服务、仓储处理。"""

    def __init__(self, boss_repository: BossRepository, profile_service: ProfileService,
                 timer_service: TimerService, settings_store: JsonStore,
                 *, legacy_data_dir: Path | None = None):
        super().__init__()
        self.boss_repository = boss_repository
        self.profile_service = profile_service
        self.timers = timer_service
        self.settings_store = settings_store
        self.legacy_data_dir = legacy_data_dir
        self.bosses = boss_repository.load()
        self.active_profile_id: str | None = None
        self.dirty = False
        self.catalog_dirty = False
        self.setWindowTitle("传奇 BOSS 计时工具")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.setMinimumSize(MINIMUM_WINDOW_WIDTH, MINIMUM_WINDOW_HEIGHT)
        self._build_ui()
        self._restore_settings()
        # 只使用一个调度器。界面每秒更新，休眠恢复后也按实际时刻计算。
        self.tick_timer = QTimer(self)
        self.tick_timer.setInterval(1000)
        self.tick_timer.timeout.connect(self._tick)
        self.tick_timer.start()
        self.catalog_save_timer = QTimer(self)
        self.catalog_save_timer.setSingleShot(True)
        self.catalog_save_timer.setInterval(400)
        self.catalog_save_timer.timeout.connect(self._persist_catalog)
        self.tree_model.checkedChanged.connect(self._checked_changed)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 12, 6, 8)
        layout.setSpacing(12)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        for text, handler, tip in [
            ("全部开始", self._start_all, "恢复右侧列表中所有暂停的计时"),
            ("全部暂停", self._pause_all, "暂停右侧所有正在运行的计时"),
            ("保存配置", self._save_profile, "保存右侧全部计时项目"),
            ("加载配置", self._load_profile, "从本地保存的配置中选择并加载"),
            ("恢复默认配置", self._reset_defaults, "恢复默认 BOSS 资料，并清空计时、方案及窗口设置"),
        ]:
            button = QPushButton(text)
            button_font = button.font()
            button_font.setPointSize(8)
            button.setFont(button_font)
            button.setFixedHeight(26)
            button.setFixedWidth(button.fontMetrics().horizontalAdvance(text) + 18)
            button.setToolTip(tip)
            button.clicked.connect(handler)
            toolbar.addWidget(button)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        # 两个控件自身各有边框；2 像素分隔条与 6 像素外边距形成相同的可见留白。
        self.splitter.setHandleWidth(2)
        layout.addWidget(self.splitter, 1)
        left = QWidget()
        left.setMinimumWidth(245)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        catalog_title = QLabel("BOSS 地图目录")
        title_font = catalog_title.font()
        title_font.setPointSize(8)
        title_font.setBold(False)
        catalog_title.setFont(title_font)
        title_palette = catalog_title.palette()
        title_palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
        catalog_title.setPalette(title_palette)
        catalog_title.setFixedHeight(26)
        catalog_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        left_header = QHBoxLayout()
        left_header.addWidget(catalog_title)
        self.topmost_checkbox = QCheckBox("置顶")
        self.topmost_checkbox.setFont(title_font)
        self.topmost_checkbox.setChecked(True)
        configure_checkbox_appearance(self.topmost_checkbox)
        self.topmost_checkbox.toggled.connect(self._set_topmost)
        left_header.addWidget(self.topmost_checkbox)
        left_header.addStretch()
        left_layout.addLayout(left_header)
        self.tree = QTreeView()
        self.tree_model = BossTreeModel(self.bosses, self)
        self.tree.setModel(self.tree_model)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(22)
        self.tree.setMouseTracking(False)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        self.tree.collapsed.connect(self._collapse_descendants)
        self.tree.viewport().installEventFilter(self)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        configure_tree_appearance(self.tree)
        left_layout.addWidget(self.tree, 1)
        self.splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        timer_hint = QLabel("按剩余时间自动排序；标红后")
        timer_hint.setFont(title_font)
        timer_hint.setPalette(title_palette)
        timer_hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        right_header = QHBoxLayout()
        right_header.setContentsMargins(0, 0, 0, 0)
        right_header.setSpacing(8)
        cleanup_layout = QHBoxLayout()
        cleanup_layout.setSpacing(3)
        cleanup_layout.addWidget(timer_hint)
        self.cleanup_seconds_input = QSpinBox()
        self.cleanup_seconds_input.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.cleanup_seconds_input.setRange(1, 86400)
        self.cleanup_seconds_input.setValue(TimerService.CLEANUP_SECONDS)
        self.cleanup_seconds_input.setKeyboardTracking(False)
        self.cleanup_seconds_input.setFont(title_font)
        self.cleanup_seconds_input.setFixedWidth(62)
        self.cleanup_seconds_input.setFixedHeight(24)
        self.cleanup_seconds_input.valueChanged.connect(self._set_cleanup_seconds)
        cleanup_layout.addWidget(self.cleanup_seconds_input)
        cleanup_suffix = QLabel("秒消失")
        cleanup_suffix.setFont(title_font)
        cleanup_suffix.setPalette(title_palette)
        cleanup_layout.addWidget(cleanup_suffix)
        right_header.addLayout(cleanup_layout)
        right_header.addStretch()
        right_header.addLayout(toolbar)
        right_layout.addLayout(right_header)
        self.table = QTableView()
        self.table_model = TimerTableModel(self.timers, self)
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        self.table.doubleClicked.connect(self._confirm_restart_timer)
        configure_table_appearance(self.table)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header_font = header.font()
        header_font.setBold(False)
        header.setFont(header_font)
        header.setStyleSheet("QHeaderView::section { font-weight: normal; }")
        header.setMinimumSectionSize(100)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self._toggle_remaining_sort)
        right_layout.addWidget(self.table, 1)
        self.splitter.addWidget(right)
        self.splitter.setSizes(DEFAULT_SPLITTER_SIZES)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

    def _toggle_remaining_sort(self, section: int):
        if section != 3:
            return
        current = self.table_model.remaining_sort_order
        order = (Qt.SortOrder.DescendingOrder
                 if current == Qt.SortOrder.AscendingOrder
                 else Qt.SortOrder.AscendingOrder)
        self.table_model.set_remaining_sort_order(order)

    def _reset_defaults(self):
        confirmed = ask_confirmation(
            self, "恢复默认配置",
            "将恢复默认 BOSS 信息与勾选状态，清空右侧计时和所有已保存方案，"
            "并重置窗口布局、菜单展开历史及排序。\n"
            "本地新旧目录中的配置、缓存和备份将被清除。是否继续？",
            QMessageBox.Icon.Warning,
        )
        if not confirmed:
            return
        try:
            # 先验证默认文件，读取失败时不删除用户的任何配置。
            defaults = BossRepository(self.boss_repository.seed_path, self.boss_repository.seed_path)
            bosses = defaults.load()
            clear_local_config(self.settings_store.path.parent, self.legacy_data_dir)
        except (StorageError, OSError) as exc:
            self._error(str(exc))
            return
        self.catalog_save_timer.stop()
        self.bosses = bosses
        self.boss_repository.metadata = defaults.metadata
        self.catalog_dirty = False
        self.timers.entries.clear()
        self.profile_service.profiles = []
        self.active_profile_id = None
        self.dirty = False
        old_model = self.tree_model
        self.tree_model = BossTreeModel(self.bosses, self)
        self.tree.setModel(self.tree_model)
        self.tree_model.checkedChanged.connect(self._checked_changed)
        old_model.deleteLater()
        self.table_model.set_remaining_sort_order(Qt.SortOrder.AscendingOrder)
        self._refresh_table()
        self.showNormal()
        self.topmost_checkbox.setChecked(True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        screen = self.screen().availableGeometry()
        self.move(screen.center() - self.rect().center())
        self.splitter.setSizes(DEFAULT_SPLITTER_SIZES)
        self._restore_settings()
        self.tree.verticalScrollBar().setValue(0)
        self.table.verticalScrollBar().setValue(0)
        self.show()
        logger.info("已恢复默认配置并清除新旧本地配置及备份")

    def eventFilter(self, watched, event):
        if (watched is self.tree.viewport() and
                event.type() == QEvent.Type.MouseButtonDblClick and
                event.button() == Qt.MouseButton.LeftButton):
            position = event.position().toPoint()
            index = self.tree.indexAt(position)
            # 消费树中的双击事件，防止复选框双击继续触发编辑逻辑。
            if index.isValid():
                check_rect = self._tree_check_rect(index)
                if index.data(BossTreeModel.BOSS_ROLE):
                    if not check_rect.contains(position):
                        self._edit_boss(index)
                elif index.model().rowCount(index) and not check_rect.contains(position):
                    # 加减号在双击的第一次单击中已自行切换；该区域不再反向切换。
                    branch_rect = QRect(check_rect.left() - self.tree.indentation(),
                                        self.tree.visualRect(index).top(),
                                        self.tree.indentation(),
                                        self.tree.visualRect(index).height())
                    if not branch_rect.contains(position):
                        self.tree.setExpanded(index, not self.tree.isExpanded(index))
            return True
        return super().eventFilter(watched, event)

    def _tree_item_option(self, index) -> QStyleOptionViewItem:
        option = QStyleOptionViewItem()
        self.tree.itemDelegateForIndex(index).initStyleOption(option, index)
        option.rect = self.tree.visualRect(index)
        return option

    def _tree_check_rect(self, index) -> QRect:
        option = self._tree_item_option(index)
        return self.tree.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, self.tree
        )

    def _tree_text_rect(self, index) -> QRect:
        """返回名称文字的实际点击区域，不包含复选框和行内空白。"""
        option = self._tree_item_option(index)
        text_rect = self.tree.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, option, self.tree
        )
        text_width = option.fontMetrics.horizontalAdvance(str(index.data()))
        return QRect(text_rect.left(), text_rect.top(),
                     min(text_width, text_rect.width()), text_rect.height())

    def _collapse_descendants(self, index):
        """父节点收起后清除其所有后代的展开状态。"""
        model = index.model()
        for row in range(model.rowCount(index)):
            child = model.index(row, 0, index)
            if model.rowCount(child):
                self._collapse_descendants(child)
                self.tree.collapse(child)

    def _restore_settings(self):
        settings = self.settings_store.read({})
        if not isinstance(settings, dict):
            raise StorageError("窗口设置格式错误，请检查 settings.json。")
        topmost = settings.get("topmost", True)
        self.topmost_checkbox.setChecked(topmost if isinstance(topmost, bool) else True)
        cleanup_seconds = settings.get("cleanup_seconds", TimerService.CLEANUP_SECONDS)
        if type(cleanup_seconds) is not int or not 1 <= cleanup_seconds <= 86400:
            cleanup_seconds = TimerService.CLEANUP_SECONDS
        self.cleanup_seconds_input.setValue(cleanup_seconds)
        self.timers.cleanup_seconds = cleanup_seconds
        geometry = settings.get("geometry")
        restored_geometry = False
        if isinstance(geometry, str):
            try:
                restored_geometry = self.restoreGeometry(
                    QByteArray(base64.b64decode(geometry, validate=True))
                )
            except ValueError:
                pass
        self._apply_compact_startup_geometry(restored_geometry)
        sizes = settings.get("splitter")
        if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(v, int) and v > 0 for v in sizes):
            self.splitter.setSizes(sizes)
        expanded = settings.get("expanded")
        if isinstance(expanded, list):
            for key in expanded:
                if key in self.tree_model.nodes:
                    self.tree.expand(self.tree_model.nodes[key].index())
        else:
            # 没有展开历史时，所有层级默认收起。
            self.tree.collapseAll()

    def _set_cleanup_seconds(self, seconds: int):
        self.timers.cleanup_seconds = seconds

    def _set_topmost(self, enabled: bool):
        visible = self.isVisible()
        geometry = self.geometry()
        state = self.windowState()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.setGeometry(geometry)
        self.setWindowState(state)
        if visible:
            self.show()

    def _apply_compact_startup_geometry(self, restored_geometry: bool):
        """保留上次位置，但每次均以适合桌面常驻的普通小窗口启动。"""
        self.setWindowState(Qt.WindowState.WindowNoState)
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        if not restored_geometry:
            return
        available = self.screen().availableGeometry()
        x = max(available.left(), min(self.x(), available.right() - self.width() + 1))
        y = max(available.top(), min(self.y(), available.bottom() - self.height() + 1))
        self.move(x, y)

    def _find_boss(self, boss_id: str) -> BossDefinition:
        return next(boss for boss in self.bosses if boss.id == boss_id)

    def _tree_context_menu(self, position):
        index = self.tree.indexAt(position)
        boss_id = index.data(BossTreeModel.BOSS_ROLE)
        node_key = index.data(BossTreeModel.NODE_ROLE)
        if not boss_id and not (isinstance(node_key, str) and node_key.startswith("map:")):
            return
        self.tree.setCurrentIndex(index)
        menu = QMenu(self)
        if boss_id:
            boss = self._find_boss(boss_id)
            action = menu.addAction("开始计时" if boss.sec > 0 else "开始计时（请先设置刷新时间）")
            action.setEnabled(boss.sec > 0)
            action.triggered.connect(lambda: self._start_boss(boss))
        else:
            action = menu.addAction("开始该地图全部计时")
            checked_ids = self.tree_model.checked_ids()
            action.setEnabled(any(boss.id in checked_ids and boss.sec > 0
                                  for boss in self._bosses_below(index)))
            action.triggered.connect(lambda: self._start_map_bosses(index))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _bosses_below(self, parent_index) -> list[BossDefinition]:
        boss_ids: list[str] = []

        def collect(index):
            boss_id = index.data(BossTreeModel.BOSS_ROLE)
            if boss_id:
                boss_ids.append(boss_id)
                return
            for row in range(index.model().rowCount(index)):
                collect(index.model().index(row, 0, index))

        collect(parent_index)
        bosses_by_id = {boss.id: boss for boss in self.bosses}
        return [bosses_by_id[boss_id] for boss_id in boss_ids if boss_id in bosses_by_id]

    def _start_map_bosses(self, map_index):
        """将地图节点下已勾选的有效 BOSS 加入右侧，已有计时保持原状态。"""
        self.timers.cleanup()
        added = []
        skipped_duplicates = 0
        skipped_invalid = 0
        checked_ids = self.tree_model.checked_ids()
        for boss in self._bosses_below(map_index):
            if boss.id not in checked_ids:
                continue
            try:
                added.append(self.timers.start(boss))
            except DuplicateBossError:
                skipped_duplicates += 1
            except TimerError:
                skipped_invalid += 1
        if added:
            self._mark_dirty()
        self._refresh_table()
        if added:
            self._select_entry(added[-1].id)
        logger.info("地图批量开始：新增 %s，已存在 %s，无效时间 %s",
                    len(added), skipped_duplicates, skipped_invalid)

    def _start_boss(self, boss: BossDefinition):
        self.timers.cleanup()
        try:
            entry = self.timers.start(boss)
        except DuplicateBossError as exc:
            self._refresh_table()
            self._select_entry(exc.entry_id)
            show_notice(self, "计时已存在", str(exc))
            return
        except TimerError as exc:
            self._error(str(exc))
            return
        self._mark_dirty()
        self._refresh_table()
        self._select_entry(entry.id)
        logger.info("已开始：%s · %s", entry.map, entry.name)

    def _edit_boss(self, index):
        boss_id = index.data(BossTreeModel.BOSS_ROLE)
        if not boss_id:
            return
        boss = self._find_boss(boss_id)
        dialog = BossEditorDialog(boss, self)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.definition()
            try:
                self.timers.validate_edit(updated)
                # 以当前勾选状态保存，避免紧接着编辑时覆盖防抖中的变更。
                ids = self.tree_model.checked_ids()
                staged = [replace(updated if b.id == boss_id else b, armed=b.id in ids)
                          for b in self.bosses]
                self.boss_repository.save(staged)
            except (StorageError, TimerError) as exc:
                self._error(str(exc))
                continue
            self.bosses = staged
            self.catalog_dirty = False
            self.catalog_save_timer.stop()
            self.timers.sync_definition(updated)
            self.tree_model.update_boss(updated)
            if any(e.boss_id == boss_id for e in self.timers.entries.values()):
                self._mark_dirty()
            self._refresh_table()
            logger.info("BOSS 信息已保存：%s", updated.name)
            break

    def _table_context_menu(self, position):
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        self.table.selectRow(index.row())
        entry = self.table_model.rows[index.row()]
        state = entry.state(self.timers.clock())
        menu = QMenu(self)
        menu.addAction("删除计时", lambda: self._remove_entry(entry.id))
        if state != TimerState.EXPIRED:
            menu.addSeparator()
            if state == TimerState.PAUSED:
                menu.addAction("开启计时", lambda: self._resume_entry(entry.id))
            else:
                menu.addAction("暂停计时", lambda: self._pause_entry(entry.id))
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _remove_entry(self, entry_id):
        self.timers.remove(entry_id)
        self._mark_dirty()
        self._refresh_table()

    def _pause_entry(self, entry_id):
        if entry_id in self.timers.entries and self.timers.pause(entry_id):
            self._mark_dirty()
        self._refresh_table()

    def _resume_entry(self, entry_id):
        if entry_id in self.timers.entries and self.timers.resume(entry_id):
            self._mark_dirty()
        self._refresh_table()

    def _confirm_restart_timer(self, index):
        if not index.isValid() or index.row() >= len(self.table_model.rows):
            return
        # 弹窗期间表格仍会刷新，必须捕获 ID，不能在确认后继续使用行号。
        entry = self.table_model.rows[index.row()]
        if not ask_confirmation(
                self, "重新倒计时",
                f"是否重新开始“{entry.name}”的倒计时？\n确认后将从 {entry.sec} 秒重新开始。"):
            return
        try:
            if not self.timers.restart(entry.id):
                self._error("该计时已被移除，请从左侧重新添加。")
                return
        except TimerError as exc:
            self._error(str(exc))
            return
        self._mark_dirty()
        self._refresh_table()
        self._select_entry(entry.id)
        logger.info("已重新开始倒计时：%s", entry.name)

    def _start_all(self):
        self.timers.cleanup()
        resumed = self.timers.start_all()
        if resumed:
            self._mark_dirty()
        self._refresh_table()
        logger.info("已恢复 %s 项计时", resumed)

    def _pause_all(self):
        count = self.timers.pause_all()
        if count:
            self._mark_dirty()
        self._refresh_table()
        logger.info("已暂停 %s 项计时", count)

    def _save_profile(self) -> bool:
        payload = self.timers.snapshot()
        if not payload:
            self._error("请先添加计时。")
            return False
        current = self.profile_service.find(self.active_profile_id)
        dialog = SaveProfileDialog(current, len(payload), self)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                # 用户输入期间计时持续更新，保存确认瞬间的状态。
                profile = self.profile_service.save(
                    dialog.name_edit.text(), self.timers.snapshot(),
                )
            except (ValueError, StorageError) as exc:
                dialog.error_label.setText(str(exc))
                continue
            self.active_profile_id = profile.id
            self.dirty = False
            logger.info("已保存配置：%s", profile.name)
            return True
        return False

    def _load_profile(self):
        if not self.profile_service.profiles:
            show_notice(self, "加载配置", "暂无保存的配置。请先添加计时并保存配置。")
            return
        dialog = LoadProfileDialog(self.profile_service.profiles, self,
                                   delete_profile=self._delete_profile)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile = self.profile_service.find(dialog.selected_profile().id)
        if profile is None:
            self._error("该配置不存在，请重新选择。")
            return
        try:
            self.timers.load_fresh(profile.timers, self.bosses)
        except TimerError as exc:
            self._error(str(exc))
            return
        self.active_profile_id = profile.id
        self.dirty = False
        self._refresh_table()
        logger.info("已加载并重新开始全部计时：%s", profile.name)

    def _delete_profile(self, profile_id: str):
        self.profile_service.delete(profile_id)
        if self.active_profile_id == profile_id:
            self.active_profile_id = None
        logger.info("已删除配置：%s", profile_id)

    def _checked_changed(self):
        self.catalog_dirty = True
        self.catalog_save_timer.start()

    def _persist_catalog(self) -> bool:
        if not self.catalog_dirty:
            return True
        try:
            self.bosses = self.boss_repository.save_checked(self.bosses, self.tree_model.checked_ids())
        except StorageError as exc:
            self._error(str(exc))
            return False
        self.catalog_dirty = False
        return True

    def _mark_dirty(self):
        self.dirty = True

    def _tick(self):
        removed = self.timers.cleanup()
        if removed:
            self._mark_dirty()
            logger.info("已自动移除 %s 项到期计时", len(removed))
        self._refresh_table()

    def _refresh_table(self):
        current = self.table.currentIndex()
        selected_id = (self.table_model.rows[current.row()].id
                       if current.isValid() and current.row() < len(self.table_model.rows) else None)
        if self.table_model.refresh() and selected_id:
            self._select_entry(selected_id, scroll=False)

    def _select_entry(self, entry_id: str, scroll=True):
        for row, entry in enumerate(self.table_model.rows):
            if entry.id == entry_id:
                self.table.selectRow(row)
                if scroll:
                    self.table.scrollTo(self.table_model.index(row, 0))
                return

    def _error(self, message: str):
        show_notice(self, "操作提示", message, QMessageBox.Icon.Warning)

    def closeEvent(self, event: QCloseEvent):
        # 关闭不再询问保存计时方案；目录勾选和窗口设置仍正常落盘。
        # 未保存提醒只用于加载其他方案、替换当前列表之前。
        if not self._persist_catalog():
            event.ignore()
            return
        try:
            self.settings_store.write({
                "geometry": base64.b64encode(bytes(self.saveGeometry())).decode("ascii"),
                "splitter": self.splitter.sizes(),
                "topmost": self.topmost_checkbox.isChecked(),
                "cleanup_seconds": self.cleanup_seconds_input.value(),
                "expanded": [key for key, item in self.tree_model.nodes.items()
                             if self.tree.isExpanded(item.index())],
            })
        except StorageError as exc:
            self._error(str(exc))
            event.ignore()
            return
        self.tick_timer.stop()
        self.catalog_save_timer.stop()
        event.accept()
