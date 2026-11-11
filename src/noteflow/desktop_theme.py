"""Shared colors, controls and icons for the desktop workspace."""

from string import Template

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QComboBox


COLORS = {
    "window": "#17191f",
    "surface": "#20232b",
    "control": "#2b303c",
    "hover": "#353c4c",
    "pressed": "#404964",
    "line": "#343946",
    "text": "#f2f3fa",
    "muted": "#adb6cb",
    "disabled": "#798298",
    "accent": "#aab6ff",
    "accent_hover": "#c0c9ff",
    "accent_ink": "#1c254e",
    "focus": "#aab6ff",
}


STYLE = Template("""
QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; }
QMainWindow, QWidget#workspace, QWidget#startPage { background: ${window}; }
QFrame#toolbar, QWidget#editorTools, QWidget#calibration { background: ${surface}; }
QFrame#startCard, QFrame#tracks, QListWidget#recent {
    background: ${surface}; border: 1px solid ${line}; border-radius: 8px;
}
QFrame#startCard { border-radius: 16px; }
QFrame#tracks { background: ${window}; border-radius: 6px; }
QFrame#divider { background: ${line}; }
QLabel#startTitle { color: ${text}; font-size: 29px; font-weight: bold; }
QLabel#recentTitle { color: ${muted}; font-weight: bold; }
QLabel#caption { color: ${muted}; font-size: 12px; }
QLabel#hint { color: ${muted}; font-size: 14px; }
QLabel#time { color: ${muted}; font-family: "Consolas"; font-size: 12px; }
QPushButton {
    color: ${text}; background: ${control}; border: 1px solid ${line};
    border-radius: 6px; padding: 0 11px;
}
QPushButton:hover { background: ${hover}; }
QPushButton:pressed { background: ${pressed}; }
QPushButton#quiet, QPushButton#icon, QPushButton#track {
    background: transparent; border-color: transparent;
}
QPushButton#icon { padding: 0; }
QPushButton#quiet:hover, QPushButton#icon:hover, QPushButton#track:hover { background: ${hover}; }
QPushButton#quiet:pressed, QPushButton#icon:pressed, QPushButton#track:pressed { background: ${pressed}; }
QPushButton#track { padding: 0 8px; color: ${muted}; border-radius: 4px; }
QPushButton#track:checked, QPushButton#quiet:checked {
    color: ${accent_hover}; background: ${pressed};
}
QPushButton#primary {
    color: ${accent_ink}; background: ${accent}; border-color: ${accent};
    padding: 0 14px; font-weight: bold;
}
QPushButton#primary:hover { background: ${accent_hover}; }
QPushButton#primary:pressed { background: #8f9bea; }
QPushButton:disabled { color: ${disabled}; }
QPushButton#primary:disabled { color: ${disabled}; background: ${control}; border-color: ${line}; }
QPushButton#icon::menu-indicator { image: none; width: 0; }
QPushButton#export { padding-right: 23px; }
QPushButton#export::menu-indicator { subcontrol-position: right center; right: 9px; }
QComboBox {
    color: ${text}; background: ${control}; border: 1px solid ${line};
    border-radius: 6px; padding: 0 23px 0 8px;
}
QComboBox:hover { background: ${hover}; }
QComboBox:disabled { color: ${disabled}; }
QComboBox::drop-down { width: 22px; border: none; background: transparent; }
QComboBox QAbstractItemView { background: ${surface}; border: 1px solid ${line}; padding: 3px; }
QComboBox QAbstractItemView::item { min-height: 28px; padding-left: 6px; }
QPushButton:focus, QPushButton#icon:focus, QPushButton#quiet:focus,
QPushButton#track:focus, QComboBox:focus, QListWidget#recent:focus, QTableWidget:focus {
    border-color: ${focus};
}
QPushButton#primary:focus { border: 2px solid white; }
QTabBar::tab {
    color: ${muted}; background: transparent; border: 1px solid transparent;
    border-radius: 5px; padding: 0 12px; min-height: 29px;
}
QTabBar::tab:hover { color: ${text}; background: ${hover}; }
QTabBar::tab:selected { color: ${accent_hover}; background: ${pressed}; font-weight: bold; }
QTabBar::tab:focus { border-color: ${focus}; }
QScrollArea { border: 0; background: ${window}; }
QScrollArea#scoreScroll { border-left: 2px solid transparent; }
QScrollArea#scoreScroll:focus { border-left-color: ${focus}; }
QTableWidget {
    color: ${text}; background: ${surface}; alternate-background-color: ${window};
    selection-background-color: ${pressed}; selection-color: ${text};
    border: 1px solid ${line}; border-radius: 6px;
}
QHeaderView::section { background: ${control}; color: ${muted}; border: 0; padding: 8px; }
QTableWidget::item { padding: 4px 8px; }
QListWidget#recent { padding: 3px; outline: 0; }
QListWidget#recent::item { color: ${text}; padding: 0 8px; border-radius: 4px; }
QListWidget#recent::item:hover { background: ${hover}; }
QListWidget#recent::item:selected { background: ${pressed}; }
QSlider::groove:horizontal { height: 4px; background: ${line}; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #8898ed; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 12px; margin: -4px 0; background: ${accent}; border-radius: 6px;
}
QSlider::handle:horizontal:focus { border: 2px solid white; }
QSlider::sub-page:horizontal:disabled, QSlider::handle:horizontal:disabled { background: ${disabled}; }
QProgressBar { background: ${control}; border: 0; border-radius: 2px; }
QProgressBar::chunk { background: ${accent}; }
QMenu { background: ${surface}; padding: 5px; border: 1px solid ${line}; }
QMenu::item { color: ${text}; padding: 7px 22px; border-radius: 4px; }
QMenu::item:selected { background: ${pressed}; }
QMenu::item:disabled { color: ${disabled}; }
QMenu::separator { background: ${line}; height: 1px; margin: 4px 7px; }
QScrollBar:vertical { width: 10px; background: ${window}; margin: 0; }
QScrollBar::handle:vertical { background: #515a6d; min-height: 30px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #77829a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: ${control}; color: ${text}; border: 1px solid ${line}; padding: 5px; }
""").substitute(COLORS)


def apply_theme(window):
    palette = window.palette()
    roles = QPalette.ColorRole
    for role, color in (
        (roles.Window, "window"), (roles.Base, "surface"), (roles.AlternateBase, "window"),
        (roles.Button, "control"), (roles.WindowText, "text"), (roles.Text, "text"),
        (roles.ButtonText, "text"), (roles.PlaceholderText, "muted"),
        (roles.Highlight, "pressed"), (roles.HighlightedText, "text"),
        (roles.Mid, "line"), (roles.Dark, "window"), (roles.Light, "hover"),
    ):
        palette.setColor(role, QColor(COLORS[color]))
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(COLORS["disabled"]))
    QApplication.setPalette(palette)
    window.setStyleSheet(STYLE)


class ComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = COLORS["muted" if self.isEnabled() else "disabled"]
        painter.setPen(QPen(QBrush(QColor(color)), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x, y = self.width() - 11, self.height() / 2
        painter.drawLine(QPointF(x - 3, y - 1.5), QPointF(x, y + 1.5))
        painter.drawLine(QPointF(x, y + 1.5), QPointF(x + 3, y - 1.5))


# Icon coordinates share a 20 × 20 canvas and the same rounded stroke.
_ICON_LINES = {
    "import": (((10, 3), (10, 13)), ((6, 9), (10, 13), (14, 9)), ((3, 13), (3, 17), (17, 17), (17, 13))),
    "folder": (((2.5, 5), (8, 5), (10, 7), (17.5, 7), (17.5, 16), (2.5, 16), (2.5, 5)),),
    "save": (((3, 3), (14, 3), (17, 6), (17, 17), (3, 17), (3, 3)),
             ((6, 3), (6, 8), (13, 8), (13, 3)), ((6, 17), (6, 12), (14, 12), (14, 17))),
    "undo": (((7, 5), (3, 9), (7, 13)), ((3, 9), (12.5, 9), (15, 10), (17, 12.5), (17, 15))),
    "redo": (((13, 5), (17, 9), (13, 13)), ((17, 9), (7.5, 9), (5, 10), (3, 12.5), (3, 15))),
    "pause": (((7, 5), (7, 15)), ((13, 5), (13, 15))),
    "play": (((7, 4), (15, 10), (7, 16), (7, 4)),),
    "stop": (((5, 5), (15, 5), (15, 15), (5, 15), (5, 5)),),
    "volume": (((3, 8), (6, 8), (10, 5), (10, 15), (6, 12), (3, 12), (3, 8)),
               ((13, 7), (14.5, 10), (13, 13)), ((15, 5), (17.5, 10), (15, 15))),
}


def icon(name, *, accent_ink=False):
    result = QIcon()
    for mode, color in ((QIcon.Mode.Normal, "accent_ink" if accent_ink else "text"),
                        (QIcon.Mode.Disabled, "disabled")):
        for scale in (1, 2):
            pixmap = QPixmap(20 * scale, 20 * scale)
            pixmap.setDevicePixelRatio(scale)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            ink = QColor(COLORS[color])
            if name == "more":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(ink)
                for x in (5, 10, 15):
                    painter.drawEllipse(QPointF(x, 10), 1.1, 1.1)
            else:
                painter.setPen(QPen(QBrush(ink), 1.5, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                for line in _ICON_LINES[name]:
                    path = QPainterPath(QPointF(*line[0]))
                    for point in line[1:]:
                        path.lineTo(QPointF(*point))
                    painter.drawPath(path)
            painter.end()
            result.addPixmap(pixmap, mode)
    return result


ICON_SIZE = QSize(17, 17)
