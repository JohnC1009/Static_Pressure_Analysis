"""Visual representation of an equipment node on the flow diagram canvas."""

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import (QPainter, QColor, QPen, QBrush, QFont,
                          QLinearGradient)
from PyQt5.QtWidgets import QGraphicsItem

from static_pressure_analysis.models import NodeType
from .port_item import PortItem

# (background, accent, icon_char) per equipment type
NODE_COLORS = {
    NodeType.FAN:             ("#fff3e0", "#fb8c00", "F"),
    NodeType.DAMPER:          ("#e3f2fd", "#1e88e5", "D"),
    NodeType.MIXING_PLENUM:   ("#e0f7fa", "#00897b", "M"),
    NodeType.DUCT_SPLIT:      ("#e8f5e9", "#43a047", "Y"),
    NodeType.PRESSURE_OUTPUT: ("#f3e5f5", "#8e24aa", "P"),
}

WIDTH = 180
HEADER_H = 28
PORT_SPACING = 24
BODY_PAD = 8
CORNER_R = 8


class NodeItem(QGraphicsItem):
    """Rounded-rectangle equipment node with header, ports, and status text."""

    def __init__(self, node):
        super().__init__()
        self.node = node
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(1)

        self._inlet_port = None
        self._outlet_port = None
        self._status_lines: list[str] = []
        self._height = HEADER_H + BODY_PAD * 2 + PORT_SPACING

        self._create_ports()

    # ── Ports ────────────────────────────────────────────────────────

    def _create_ports(self):
        has_inlet = self.node.node_type != NodeType.FAN
        has_outlet = self.node.node_type != NodeType.PRESSURE_OUTPUT

        port_y = HEADER_H + BODY_PAD + PORT_SPACING / 2

        if has_inlet:
            self._inlet_port = PortItem("inlet", self)
            self._inlet_port.setPos(0, port_y)

        if has_outlet:
            self._outlet_port = PortItem("outlet", self)
            self._outlet_port.setPos(WIDTH, port_y)

    def get_inlet_port(self):
        return self._inlet_port

    def get_outlet_port(self):
        return self._outlet_port

    # ── Status display (populated after analysis) ────────────────────

    def set_status(self, lines: list[str]):
        self.prepareGeometryChange()
        self._status_lines = lines
        status_h = len(lines) * 16 + BODY_PAD if lines else 0
        self._height = HEADER_H + BODY_PAD * 2 + PORT_SPACING + status_h
        self.update()

    # ── Qt overrides ─────────────────────────────────────────────────

    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, WIDTH + 4, self._height + 4)

    def paint(self, painter: QPainter, option, widget):
        bg, accent, icon_char = NODE_COLORS.get(
            self.node.node_type, ("#f5f5f5", "#757575", "?")
        )

        # Body background
        rect = QRectF(0, 0, WIDTH, self._height)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(bg)))
        border_color = (QColor("#ff9800") if self.isSelected()
                        else QColor(accent))
        painter.setPen(QPen(border_color, 2.5 if self.isSelected() else 1.5))
        painter.drawRoundedRect(rect, CORNER_R, CORNER_R)

        # Header bar with gradient
        header_rect = QRectF(0, 0, WIDTH, HEADER_H)
        grad = QLinearGradient(0, 0, 0, HEADER_H)
        grad.setColorAt(0, QColor(accent))
        grad.setColorAt(1, QColor(accent).darker(120))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(header_rect, CORNER_R, CORNER_R)
        # Square off bottom corners of header
        painter.drawRect(QRectF(0, HEADER_H - CORNER_R, WIDTH, CORNER_R))

        # Icon circle in header
        painter.setBrush(QBrush(QColor(255, 255, 255, 60)))
        painter.drawEllipse(6, 4, 20, 20)
        painter.setPen(QPen(QColor("white")))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(QRectF(6, 4, 20, 20), Qt.AlignCenter, icon_char)

        # Header text
        painter.setPen(QPen(QColor("white")))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(
            header_rect.adjusted(30, 0, -8, 0),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.node.name,
        )

        # Port labels
        painter.setPen(QPen(QColor("#555")))
        painter.setFont(QFont("Segoe UI", 7))
        port_y = HEADER_H + BODY_PAD + PORT_SPACING / 2
        if self._inlet_port:
            painter.drawText(
                QRectF(14, port_y - 8, WIDTH / 2 - 14, 16),
                Qt.AlignVCenter | Qt.AlignLeft, "IN",
            )
        if self._outlet_port:
            painter.drawText(
                QRectF(WIDTH / 2, port_y - 8, WIDTH / 2 - 14, 16),
                Qt.AlignVCenter | Qt.AlignRight, "OUT",
            )

        # Status text (analysis results)
        if self._status_lines:
            painter.setFont(QFont("Consolas", 7))
            painter.setPen(QPen(QColor("#555")))
            base_y = HEADER_H + BODY_PAD * 2 + PORT_SPACING
            for i, line in enumerate(self._status_lines):
                painter.drawText(
                    QRectF(8, base_y + i * 16, WIDTH - 16, 16),
                    Qt.AlignVCenter | Qt.AlignLeft, line,
                )

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.node.x = self.pos().x()
            self.node.y = self.pos().y()
            scene = self.scene()
            if scene and hasattr(scene, "update_connectors_for_node"):
                scene.update_connectors_for_node(self.node.id)
        return super().itemChange(change, value)
