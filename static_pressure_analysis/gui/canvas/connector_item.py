"""Visual connector (duct line) between two ports on the canvas."""

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QPen, QColor, QPainterPath, QPainter
from PyQt5.QtWidgets import QGraphicsPathItem


class ConnectorItem(QGraphicsPathItem):
    """Bezier curve connecting an outlet PortItem to an inlet PortItem."""

    def __init__(self, connector, source_port_item, target_port_item):
        super().__init__()
        self.connector = connector
        self.source_port_item = source_port_item
        self.target_port_item = target_port_item

        self.setPen(QPen(QColor("#4a90d9"), 2.5, Qt.SolidLine, Qt.RoundCap))
        self.setZValue(0)
        self.setFlag(QGraphicsPathItem.ItemIsSelectable)
        self.update_path()

    def update_path(self):
        """Recalculate the bezier path based on current port positions."""
        p1 = self.source_port_item.get_scene_center()
        p2 = self.target_port_item.get_scene_center()

        dx = max(abs(p2.x() - p1.x()) * 0.5, 40)

        path = QPainterPath(p1)
        path.cubicTo(
            p1.x() + dx, p1.y(),
            p2.x() - dx, p2.y(),
            p2.x(), p2.y(),
        )
        self.setPath(path)

    def paint(self, painter: QPainter, option, widget):
        if self.isSelected():
            self.setPen(QPen(QColor("#ff9800"), 3.0, Qt.SolidLine, Qt.RoundCap))
        else:
            self.setPen(QPen(QColor("#4a90d9"), 2.5, Qt.SolidLine, Qt.RoundCap))
        super().paint(painter, option, widget)


class TempConnectorItem(QGraphicsPathItem):
    """Temporary dashed line shown while the user drags a new connection."""

    def __init__(self, start_pos: QPointF):
        super().__init__()
        self._start = start_pos
        self.setPen(QPen(QColor("#aaa"), 2.0, Qt.DashLine))
        self.setZValue(10)

    def update_end(self, end_pos: QPointF):
        dx = max(abs(end_pos.x() - self._start.x()) * 0.5, 40)
        path = QPainterPath(self._start)
        path.cubicTo(
            self._start.x() + dx, self._start.y(),
            end_pos.x() - dx, end_pos.y(),
            end_pos.x(), end_pos.y(),
        )
        self.setPath(path)
