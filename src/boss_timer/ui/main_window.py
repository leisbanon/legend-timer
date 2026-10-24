from __future__ import annotations

import base64
import logging
from dataclasses import replace

from PySide6.QtCore import QByteArray, QEvent, QRect, QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter, QStyle,
    QStyleOptionViewItem, QTableView, QTreeView, QVBoxLayout, QWidget,
)

from boss_timer.domain.models import BossDefinition, TimerState
from boss_timer.repositories.boss_repository import BossRepository
from boss_timer.repositories.json_store import JsonStore, StorageError
from boss_timer.services.profile_service import ProfileService
from boss_timer.services.timer_service import DuplicateBossError, TimerError, TimerService
from boss_timer.ui.dialogs.boss_editor import BossEditorDialog
from boss_timer.ui.dialogs.profile_dialogs import LoadProfileDialog, SaveProfileDialog
from boss_timer.ui.models.boss_tree import BossTreeModel
from boss_timer.ui.models.timer_table import TimerTableModel
from boss_timer.ui.theme import configure_table_appearance, configure_tree_appearance

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """负责视图连接；计时与保存规则交给服务、仓储处理。"""

    def __init__(self, boss_repository: BossRepository, profile_service: ProfileService,
                 timer_service: TimerService, settings_store: JsonStore):
        super().__init__()
        self.boss_repository = boss_repository
        self.profile_service = profile_service
        self.timers = timer_service
        self.settings_store = settings_store
        self.bosses = boss_repository.load()
        self.active_profile_id: str | None = None
        self.dirty = False
        self.catalog_dirty = False
        self.setWindowTitle("传奇 BOSS 计时工具")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(1200, 760)
        self.setMinimumSize(980, 580)
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
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(12)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        toolbar.addStretch()
        for text, handler, tip in [
            ("全部开始", self._start_all, "添加左侧已勾选的 BOSS，并恢复右侧暂停的计时；同名条目不会重复添加"),
            ("全部暂停", self._pause_all, "暂停右侧所有正在运行的计时"),
            ("保存配置", self._save_profile, "保存右侧已勾选的条目"),
            ("加载配置", self._load_profile, "从本地保存的配置中选择并加载"),
        ]:
            button = QPushButton(text)
            button.setMinimumHeight(32)
            button.setToolTip(tip)
            button.clicked.connect(handler)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        left = QWidget()
        left.setMinimumWidth(245)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(QLabel("BOSS 地图目录"))
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
        right_layout.addWidget(QLabel("正在计时（按剩余时间排序，到期 120 秒后移除）"))
        self.table = QTableView()
        self.table_model = TimerTableModel(self.timers, self)
        self.table_model.selectionChanged.connect(self._mark_dirty)
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        configure_table_appearance(self.table)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(100)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(self.table, 1)
        self.splitter.addWidget(right)
        self.splitter.setSizes([335, 829])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

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
        geometry = settings.get("geometry")
        if isinstance(geometry, str):
            try:
                self.restoreGeometry(QByteArray(base64.b64decode(geometry, validate=True)))
            except ValueError:
                pass
        sizes = settings.get("splitter")
        if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(v, int) and v > 0 for v in sizes):
            self.splitter.setSizes(sizes)
        expanded = settings.get("expanded")
        if isinstance(expanded, list):
            for key in expanded:
                if key in self.tree_model.nodes:
                    self.tree.expand(self.tree_model.nodes[key].index())
        else:
            # 首次打开分类，并展开第一个地图，避免 311 条目一次铺满。
            self.tree.expandToDepth(0)
            first = next((item for key, item in self.tree_model.nodes.items() if key.startswith("map:")), None)
            if first is not None:
                self.tree.expand(first.index())
    def _find_boss(self, boss_id: str) -> BossDefinition:
        return next(boss for boss in self.bosses if boss.id == boss_id)

    def _tree_context_menu(self, position):
        index = self.tree.indexAt(position)
        boss_id = index.data(BossTreeModel.BOSS_ROLE)
        if not boss_id:
            return
        self.tree.setCurrentIndex(index)
        boss = self._find_boss(boss_id)
        menu = QMenu(self)
        action = menu.addAction("开始计时" if boss.sec > 0 else "开始计时（请先设置刷新时间）")
        action.setEnabled(boss.sec > 0)
        action.triggered.connect(lambda: self._start_boss(boss))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _start_boss(self, boss: BossDefinition):
        self.timers.cleanup()
        try:
            entry = self.timers.start(boss)
        except DuplicateBossError as exc:
            self._refresh_table()
            self._select_entry(exc.entry_id)
            QMessageBox.information(self, "计时已存在", str(exc))
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

    def _start_all(self):
        self.timers.cleanup()
        checked = self.tree_model.checked_ids()
        added, resumed, invalid = self.timers.start_all([boss for boss in self.bosses if boss.id in checked])
        if added or resumed:
            self._mark_dirty()
        self._refresh_table()
        logger.info("批量开始：新增 %s 项，恢复 %s 项，无有效刷新时间 %s 项", added, resumed, invalid)

    def _pause_all(self):
        count = self.timers.pause_all()
        if count:
            self._mark_dirty()
        self._refresh_table()
        logger.info("已暂停 %s 项计时", count)

    def _save_profile(self) -> bool:
        payload = self.timers.snapshot()
        if not payload:
            self._error("请先添加计时，并至少勾选右侧一条记录。")
            return False
        current = self.profile_service.find(self.active_profile_id)
        dialog = SaveProfileDialog(current, len(payload), self)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                # 用户输入期间计时持续更新，保存确认瞬间的状态。
                profile = self.profile_service.save(
                    dialog.name_edit.text(), self.timers.snapshot(),
                    None if dialog.save_as_new.isChecked() else self.active_profile_id,
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
            QMessageBox.information(self, "加载配置", "暂无保存的配置。请先添加计时并保存配置。")
            return
        dialog = LoadProfileDialog(self.profile_service.profiles, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not self._confirm_discard():
            return
        # “先保存”可能修改了刚选中的同一方案，此时必须加载最新内容。
        profile = self.profile_service.find(dialog.selected_profile().id)
        if profile is None:
            self._error("该配置不存在，请重新选择。")
            return
        try:
            removed = self.timers.restore(profile.timers, self.bosses)
        except TimerError as exc:
            self._error(str(exc))
            return
        self.active_profile_id = profile.id
        self.dirty = bool(removed)
        self._refresh_table()
        logger.info("已加载：%s；清理过期计时 %s 项", profile.name, removed)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("尚未保存配置")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("右侧列表有未保存的修改，是否先保存？")
        save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("放弃修改", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() == save:
            return self._save_profile()
        return box.clickedButton() == discard

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
        QMessageBox.warning(self, "操作提示", message)

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
