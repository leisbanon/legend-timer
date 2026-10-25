"""局部调整列表选中、黑白复选框和树节点图标，其余控件使用平台原生绘制。"""

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QHeaderView, QProxyStyle, QStyle, QStyledItemDelegate,
    QStyleFactory, QStyleOptionButton, QStyleOptionViewItem,
)


BLUE = "#0078d7"
TABLE_ROW_HEIGHT = 24
CHECKBOX_SIZE = 13


class NativeButtonStyle(QProxyStyle):
    """由当前平台绘制按钮，仅省略默认/焦点按钮的强调装饰。"""

    def drawControl(self, element, option, painter, widget=None):
        if isinstance(option, QStyleOptionButton) and element in (
            QStyle.ControlElement.CE_PushButton,
            QStyle.ControlElement.CE_PushButtonBevel,
            QStyle.ControlElement.CE_PushButtonLabel,
        ):
            native_option = QStyleOptionButton(option)
            native_option.state &= ~(QStyle.StateFlag.State_HasFocus |
                                     QStyle.StateFlag.State_KeyboardFocusChange)
            native_option.features &= ~(QStyleOptionButton.ButtonFeature.DefaultButton |
                                        QStyleOptionButton.ButtonFeature.AutoDefaultButton)
            # 只修改本次绘制的选项，不改变按钮的焦点、Enter 或 Tab 行为。
            return super().drawControl(element, native_option, painter, widget)
        return super().drawControl(element, option, painter, widget)


def configure_button_appearance(app: QApplication) -> None:
    if isinstance(app.style(), NativeButtonStyle):
        return
    style_name = app.style().objectName()
    style = NativeButtonStyle(style_name)
    # 保留平台样式名，供复选框局部代理创建同样的平台样式。
    style.setObjectName(style_name)
    app.setStyle(style)


class SimpleCheckboxStyle(QProxyStyle):
    """绘制简约黑白复选框及加减号树节点，其余交给系统样式。"""

    _checkbox_icons: dict[tuple[bool, bool, int], QSvgRenderer] = {}

    def __init__(self, parent, *, suppress_focus_frame: bool = False):
        # 创建独立的原生样式实例，避免接管 QApplication 的共享样式。
        base = QStyleFactory.create(QApplication.instance().style().objectName())
        super().__init__(base)
        self.setParent(parent)
        self._suppress_focus_frame = suppress_focus_frame

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PixelMetric.PM_IndicatorWidth,
                      QStyle.PixelMetric.PM_IndicatorHeight):
            return CHECKBOX_SIZE
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        # QTreeView 在委托之外单独绘制整行背景，包含左侧缩进区域。
        # 该区域不经过 FlatRowDelegate，因此在这里移除原生悬浮底色。
        if (self._suppress_focus_frame and
                element == QStyle.PrimitiveElement.PE_PanelItemViewRow):
            if not option.state & QStyle.StateFlag.State_Selected:
                return
            row_option = QStyleOptionViewItem(option)
            row_option.state &= ~QStyle.StateFlag.State_MouseOver
            return super().drawPrimitive(element, row_option, painter, widget)
        # Windows 原生样式会在当前条目外再绘制一圈深色焦点框。
        # 列表已用整行蓝色清楚表达当前位置，因此此处仅省略该装饰。
        if (self._suppress_focus_frame and
                element == QStyle.PrimitiveElement.PE_FrameFocusRect):
            return
        if element not in (QStyle.PrimitiveElement.PE_IndicatorCheckBox,
                           QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck):
            return super().drawPrimitive(element, option, painter, widget)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        state = (2 if option.state & QStyle.StateFlag.State_NoChange else
                 1 if option.state & QStyle.StateFlag.State_On else 0)
        key = (selected, enabled, state)
        renderer = self._checkbox_icons.get(key)
        if renderer is None:
            border = "#ffffff" if selected else ("#555555" if enabled else "#b8b8b8")
            background = "none" if selected else ("#ffffff" if enabled else "#f3f3f3")
            mark = "#ffffff" if selected else ("#111111" if enabled else "#888888")
            if state == 2:
                symbol = '<path d="M3.8 6.5H9.2"/>'
            elif state == 1:
                symbol = '<path d="M3.6 6.5L5.5 8.4L9.3 4.2"/>'
            else:
                symbol = ""
            svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13"
                viewBox="0 0 13 13" fill="none">
                <rect x="1.5" y="1.5" width="10" height="10" fill="{background}"
                    stroke="{border}" stroke-width="1"/>
                <g stroke="{mark}" stroke-width="1.4" stroke-linecap="round"
                    stroke-linejoin="round">{symbol}</g>
            </svg>"""
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            self._checkbox_icons[key] = renderer
        target = QRectF(0, 0, CHECKBOX_SIZE, CHECKBOX_SIZE)
        target.moveCenter(QRectF(option.rect).center())
        renderer.render(painter, target)

def configure_checkbox_appearance(widget, *, suppress_focus_frame: bool = False) -> None:
    style = SimpleCheckboxStyle(widget, suppress_focus_frame=suppress_focus_frame)
    # QWidget 不接管样式所有权；父子关系和引用共同保证其生命周期。
    widget._checkbox_style = style
    widget.setStyle(style)


class FlatRowDelegate(QStyledItemDelegate):
    """保留 Qt 的文字、复选框和状态色绘制，移除单元格焦点边框。"""

    def paint(self, painter, option, index):
        flat_option = QStyleOptionViewItem(option)
        flat_option.state &= ~QStyle.StateFlag.State_HasFocus
        # 鼠标经过只用于定位和提示，不绘制类似“已选中”的灰色背景。
        flat_option.state &= ~QStyle.StateFlag.State_MouseOver
        flat_option.showDecorationSelected = True
        super().paint(painter, flat_option, index)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 22))


def _configure_selection(view, selector: str) -> None:
    # 规则只匹配列表条目；表头、滚动条和按钮均交给原生样式。
    # ::item 的矩形填充用于覆盖 Windows 11 默认的圆角、留白选中效果。
    view.setStyleSheet(f"""
        {selector} {{
            selection-background-color: {BLUE};
            selection-color: white;
            outline: 0px;
        }}
        {selector}::item:selected {{
            background-color: {BLUE};
            color: white;
            border: 0px;
            outline: 0px;
            border-radius: 0px;
            margin: 0px;
        }}
    """)


def configure_tree_appearance(tree) -> None:
    configure_checkbox_appearance(tree, suppress_focus_frame=True)
    _configure_selection(tree, "QTreeView")
    icon_dir = Path(__file__).resolve().parent.parent / "resources" / "icons"
    normal_closed_icon = (icon_dir / "branch_closed.svg").as_posix()
    normal_open_icon = (icon_dir / "branch_open.svg").as_posix()
    closed_icon = (icon_dir / "branch_closed_selected.svg").as_posix()
    open_icon = (icon_dir / "branch_open_selected.svg").as_posix()
    tree.setStyleSheet(tree.styleSheet() + f"""
        QTreeView {{ show-decoration-selected: 1; }}
        QTreeView::item:hover:!selected,
        QTreeView::branch:hover:!selected {{
            background-color: transparent;
            border: 0px;
        }}
        QTreeView::branch:selected {{ background-color: {BLUE}; }}
        QTreeView::branch:has-children:closed {{
            image: url("{normal_closed_icon}");
        }}
        QTreeView::branch:has-children:open {{
            image: url("{normal_open_icon}");
        }}
        QTreeView::branch:selected:has-children:closed {{
            image: url("{closed_icon}");
        }}
        QTreeView::branch:selected:has-children:open {{
            image: url("{open_icon}");
        }}
    """)
    tree.setItemDelegate(FlatRowDelegate(tree))
    tree.setAllColumnsShowFocus(True)
    # 最后一列铺满视口，使叶子节点选中背景也能延伸到菜单右边缘。
    tree.header().setStretchLastSection(True)


def configure_table_appearance(table) -> None:
    configure_checkbox_appearance(table, suppress_focus_frame=True)
    _configure_selection(table, "QTableView")
    table.setItemDelegate(FlatRowDelegate(table))
    table.setAlternatingRowColors(False)
    table.setShowGrid(False)
    header = table.verticalHeader()
    header.setMinimumSectionSize(TABLE_ROW_HEIGHT)
    header.setDefaultSectionSize(TABLE_ROW_HEIGHT)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
