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

# Default (inlet_count, outlet_count) per node type
_PORT_COUNTS = {
    NodeType.FAN:             (0, 1),
    NodeType.DAMPER:          (1, 1),
    NodeType.MIXING_PLENUM:   (3, 1),   # multiple inlets
    NodeType.DUCT_SPLIT:      (1, 3),   # multiple outlets
    NodeType.PRESSURE_OUTPUT: (1, 0),
}

WIDTH = 180
HEADER_H = 28
PORT_SPACING = 22
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

        self._inlet_ports: list[PortItem] = []
        self._outlet_ports: list[PortItem] = []
        self._status_lines: list[str] = []

        n_in, n_out = _PORT_COUNTS.get(self.node.node_type, (1, 1))
        self._create_ports(n_in, n_out)
        self._recalc_height()

    # ── Ports ────────────────────────────────────────────────────────

    def _create_ports(self, n_inlets: int, n_outlets: int):
        for i in range(n_inlets):
            p = PortItem("inlet", self, index=i)
            self._inlet_ports.append(p)

        for i in range(n_outlets):
            p = PortItem("outlet", self, index=i)
            self._outlet_ports.append(p)

        self._layout_ports()

    def _layout_ports(self):
        """Position all port items along the left/right edges."""
        for i, p in enumerate(self._inlet_ports):
            y = HEADER_H + BODY_PAD + PORT_SPACING / 2 + i * PORT_SPACING
            p.setPos(0, y)

        for i, p in enumerate(self._outlet_ports):
            y = HEADER_H + BODY_PAD + PORT_SPACING / 2 + i * PORT_SPACING
            p.setPos(WIDTH, y)

    def _recalc_height(self):
        max_ports = max(len(self._inlet_ports), len(self._outlet_ports), 1)
        port_h = max_ports * PORT_SPACING + BODY_PAD * 2
        status_h = len(self._status_lines) * 16 + BODY_PAD if self._status_lines else 0
        self._height = HEADER_H + max(port_h, PORT_SPACING + BODY_PAD * 2) + status_h

    def add_inlet_port(self) -> PortItem:
        """Add a new inlet port and reflow the layout."""
        self.prepareGeometryChange()
        p = PortItem("inlet", self, index=len(self._inlet_ports))
        self._inlet_ports.append(p)
        self._layout_ports()
        self._recalc_height()
        self.update()
        return p

    def add_outlet_port(self) -> PortItem:
        """Add a new outlet port and reflow the layout."""
        self.prepareGeometryChange()
        p = PortItem("outlet", self, index=len(self._outlet_ports))
        self._outlet_ports.append(p)
        self._layout_ports()
        self._recalc_height()
        self.update()
        return p

    def get_available_inlet(self) -> PortItem | None:
        """Return the first unconnected inlet port, or add one if all full."""
        for p in self._inlet_ports:
            if not p.connected:
                return p
        # All occupied — grow if this node type supports multiple inlets
        if self.node.node_type == NodeType.MIXING_PLENUM:
            return self.add_inlet_port()
        return None

    def get_available_outlet(self) -> PortItem | None:
        """Return the first unconnected outlet port, or add one if all full."""
        for p in self._outlet_ports:
            if not p.connected:
                return p
        # All occupied — grow if this node type supports multiple outlets
        if self.node.node_type == NodeType.DUCT_SPLIT:
            return self.add_outlet_port()
        return None

    def get_inlet_port(self) -> PortItem | None:
        """Return first inlet port (for single-inlet nodes)."""
        return self._inlet_ports[0] if self._inlet_ports else None

    def get_outlet_port(self) -> PortItem | None:
        """Return first outlet port (for single-outlet nodes)."""
        return self._outlet_ports[0] if self._outlet_ports else None

    # ── Status display (populated after analysis) ────────────────────

    def set_status(self, lines: list[str]):
        self.prepareGeometryChange()
        self._status_lines = lines
        self._recalc_height()
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
        for i, p in enumerate(self._inlet_ports):
            y = p.y()
            label = f"IN {i+1}" if len(self._inlet_ports) > 1 else "IN"
            painter.drawText(
                QRectF(14, y - 8, WIDTH / 2 - 14, 16),
                Qt.AlignVCenter | Qt.AlignLeft, label,
            )
        for i, p in enumerate(self._outlet_ports):
            y = p.y()
            label = f"OUT {i+1}" if len(self._outlet_ports) > 1 else "OUT"
            painter.drawText(
                QRectF(WIDTH / 2, y - 8, WIDTH / 2 - 14, 16),
                Qt.AlignVCenter | Qt.AlignRight, label,
            )

        # Status text (analysis results)
        if self._status_lines:
            painter.setFont(QFont("Consolas", 7))
            painter.setPen(QPen(QColor("#555")))
            max_ports = max(len(self._inlet_ports), len(self._outlet_ports), 1)
            base_y = HEADER_H + BODY_PAD * 2 + max_ports * PORT_SPACING
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
