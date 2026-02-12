"""Visual representation of an equipment node on the flow diagram canvas."""

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import (QPainter, QColor, QPen, QBrush, QFont,
                          QLinearGradient)
from PyQt5.QtWidgets import QGraphicsItem

from static_pressure_analysis.models import (
    Node, NodeType, FanParameters, DamperParameters,
    MixingPlenumParameters, DuctSplitParameters, PressureOutputParameters,
)
from static_pressure_analysis.gui.canvas.port_item import PortItem

# Node colour palette: (light_bg, accent) keyed by NodeType
NODE_COLORS = {
    NodeType.FAN:              ("#e3f2fd", "#4A90D9"),
    NodeType.DAMPER:           ("#fff3e0", "#E8943A"),
    NodeType.MIXING_PLENUM:    ("#e8f5e9", "#6BBF6B"),
    NodeType.DUCT_SPLIT:       ("#f3e5f5", "#C47DD8"),
    NodeType.PRESSURE_OUTPUT:  ("#fbe9e7", "#E05555"),
}

WIDTH = 180
HEADER_H = 28
PORT_ROW_H = 22
BODY_PAD = 6
CORNER_R = 8


class NodeItem(QGraphicsItem):
    """Rounded-rectangle equipment node with header, ports, and status text."""

    def __init__(self, node: Node):
        super().__init__()
        self.node = node
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptDrops(False)
        self.setZValue(1)

        self._inlet_port: PortItem | None = None
        self._outlet_port: PortItem | None = None
        self._status_lines: list[str] = []
        self._height = HEADER_H + BODY_PAD
        self._create_ports()
        self._update_status()

    # -- Port layout -------------------------------------------------------

    def _create_ports(self):
        """Create inlet/outlet ports based on node type."""
        has_inlet = self.node.node_type != NodeType.FAN
        has_outlet = self.node.node_type != NodeType.PRESSURE_OUTPUT

        port_count = max(int(has_inlet) + int(has_outlet), 1)
        body_h = port_count * PORT_ROW_H + BODY_PAD * 2
        self._height = HEADER_H + body_h

        y_center = HEADER_H + body_h / 2

        if has_inlet:
            self._inlet_port = PortItem("inlet", self)
            self._inlet_port.setPos(0, y_center)

        if has_outlet:
            self._outlet_port = PortItem("outlet", self)
            self._outlet_port.setPos(WIDTH, y_center)

    def get_port_item(self, direction: str) -> PortItem | None:
        if direction == "inlet":
            return self._inlet_port
        if direction == "outlet":
            return self._outlet_port
        return None

    # -- Status display ----------------------------------------------------

    def _update_status(self):
        self._status_lines.clear()
        p = self.node.parameters
        if isinstance(p, FanParameters):
            self._status_lines.append(f"Airflow: {p.airflow:.0f} CFM")
            self._status_lines.append(f"SP: {p.static_pressure:.2f} in.wg")
        elif isinstance(p, DamperParameters):
            self._status_lines.append(f"dP: {p.pressure_drop:.2f} in.wg")
        elif isinstance(p, MixingPlenumParameters):
            self._status_lines.append(f"dP: {p.pressure_drop:.2f} in.wg")
        elif isinstance(p, DuctSplitParameters):
            self._status_lines.append(f"dP: {p.pressure_drop:.2f} in.wg")
        elif isinstance(p, PressureOutputParameters):
            self._status_lines.append(p.label)

        # Recalculate height to fit status
        has_inlet = self._inlet_port is not None
        has_outlet = self._outlet_port is not None
        port_rows = max(int(has_inlet), int(has_outlet), 1)
        port_h = port_rows * PORT_ROW_H + BODY_PAD * 2
        status_h = (len(self._status_lines) * 16 + BODY_PAD
                     if self._status_lines else 0)
        self._height = HEADER_H + max(port_h, status_h + PORT_ROW_H)

    def set_result_text(self, text: str | None):
        """Set an analysis result annotation (e.g. pressure reading)."""
        self.prepareGeometryChange()
        self._update_status()
        if text:
            self._status_lines.append(text)
            port_h = PORT_ROW_H + BODY_PAD * 2
            status_h = len(self._status_lines) * 16 + BODY_PAD
            self._height = HEADER_H + max(port_h, status_h + PORT_ROW_H)
        self.update()

    def refresh(self):
        """Call after solver or parameter change to update visuals."""
        self.prepareGeometryChange()
        self._update_status()
        self.update()

    # -- Qt overrides ------------------------------------------------------

    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, WIDTH + 4, self._height + 4)

    def paint(self, painter: QPainter, option, widget):
        bg, accent = NODE_COLORS.get(self.node.node_type, ("#f5f5f5", "#757575"))

        rect = QRectF(0, 0, WIDTH, self._height)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(bg)))
        border_color = (QColor("#ff9800") if self.isSelected()
                        else QColor(accent))
        painter.setPen(QPen(border_color, 2.5 if self.isSelected() else 1.5))
        painter.drawRoundedRect(rect, CORNER_R, CORNER_R)

        # Header bar
        header_rect = QRectF(0, 0, WIDTH, HEADER_H)
        grad = QLinearGradient(0, 0, 0, HEADER_H)
        grad.setColorAt(0, QColor(accent))
        grad.setColorAt(1, QColor(accent).darker(120))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(header_rect, CORNER_R, CORNER_R)
        painter.drawRect(QRectF(0, HEADER_H - CORNER_R, WIDTH, CORNER_R))

        # Header text
        painter.setPen(QPen(QColor("white")))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        display_name = self.node.name
        if len(display_name) > 22:
            display_name = display_name[:20] + ".."
        painter.drawText(header_rect.adjusted(8, 0, -8, 0),
                         Qt.AlignVCenter | Qt.AlignLeft, display_name)

        # Port labels
        painter.setPen(QPen(QColor("#333")))
        painter.setFont(QFont("Segoe UI", 7))
        if self._inlet_port:
            y = self._inlet_port.y()
            painter.drawText(QRectF(14, y - 8, WIDTH / 2 - 14, 16),
                             Qt.AlignVCenter | Qt.AlignLeft, "inlet")
        if self._outlet_port:
            y = self._outlet_port.y()
            painter.drawText(QRectF(WIDTH / 2, y - 8, WIDTH / 2 - 14, 16),
                             Qt.AlignVCenter | Qt.AlignRight, "outlet")

        # Status text
        if self._status_lines:
            painter.setFont(QFont("Consolas", 7))
            painter.setPen(QPen(QColor("#555")))
            base_y = HEADER_H + PORT_ROW_H + BODY_PAD
            for i, line in enumerate(self._status_lines):
                painter.drawText(
                    QRectF(8, base_y + i * 16, WIDTH - 16, 16),
                    Qt.AlignVCenter | Qt.AlignLeft, line,
                )

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            pos = self.pos()
            self.node.x = pos.x()
            self.node.y = pos.y()
            scene = self.scene()
            if scene and hasattr(scene, "update_connectors_for_node"):
                scene.update_connectors_for_node(self.node.id)
        return super().itemChange(change, value)
