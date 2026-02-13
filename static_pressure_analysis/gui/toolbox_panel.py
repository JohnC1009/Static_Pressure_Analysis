"""Left-side equipment toolbox with drag-and-drop buttons."""

from PyQt5.QtCore import Qt, QMimeData, QPoint
from PyQt5.QtGui import QDrag, QFont, QColor, QIcon, QPixmap, QPainter
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton,
                              QFrame, QScrollArea)

from static_pressure_analysis.models import NodeType

# (NodeType, display_name, icon_char, accent_color)
EQUIPMENT = [
    (NodeType.FAN,              "Fan",              "F", "#fb8c00"),
    (NodeType.DAMPER,           "Damper",           "D", "#1e88e5"),
    (NodeType.MIXING_PLENUM,    "Mixing Plenum",    "M", "#00897b"),
    (NodeType.DUCT_SPLIT,       "Duct Split",       "Y", "#43a047"),
    (NodeType.DUCT_SINK_SOURCE, "Duct Sink/Source", "Z", "#6d4c41"),
    (NodeType.RIGID_DUCT,       "Rigid Duct",       "R", "#546e7a"),
    (NodeType.PRESSURE_OUTPUT,  "Pressure Output",  "P", "#8e24aa"),
]


def _make_icon(char: str, color: str, size: int = 32) -> QIcon:
    """Create a coloured-circle icon with a character label."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Segoe UI", int(size * 0.38), QFont.Bold))
    painter.drawText(pm.rect(), Qt.AlignCenter, char)
    painter.end()
    return QIcon(pm)


class EquipmentDragButton(QPushButton):
    """A button that initiates a drag carrying the equipment type value."""

    def __init__(self, node_type: NodeType, display_name: str,
                 icon_char: str, color: str, parent=None):
        super().__init__(parent)
        self.node_type = node_type
        self.setText(f"  {display_name}")
        self.setIcon(_make_icon(icon_char, color))
        self.setIconSize(self.iconSize())
        self.setFixedHeight(38)
        self.setCursor(Qt.OpenHandCursor)
        self.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 4px 8px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background: #fafafa;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #e3f2fd;
                border-color: #90caf9;
            }
        """)
        self._drag_start: QPoint | None = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._drag_start is not None
                and (event.pos() - self._drag_start).manhattanLength() > 10):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(self.node_type.value)  # e.g. "Fan", "Damper", ...
            drag.setMimeData(mime)
            drag.exec_(Qt.CopyAction)
            self._drag_start = None
        super().mouseMoveEvent(event)


class ToolboxPanel(QWidget):
    """Left panel containing draggable equipment buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header = QLabel("Equipment Toolbox")
        header.setFont(QFont("Segoe UI", 11, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        for node_type, name, icon_char, color in EQUIPMENT:
            btn = EquipmentDragButton(node_type, name, icon_char, color)
            layout.addWidget(btn)

        layout.addStretch()

        hint = QLabel("Drag equipment onto\nthe canvas to add it.")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        scroll.setWidget(inner)
