"""Visual port (connection point) on an equipment node."""

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QBrush, QPen, QColor
from PyQt5.QtWidgets import QGraphicsEllipseItem

RADIUS = 7


class PortItem(QGraphicsEllipseItem):
    """Small circle on a node edge representing an inlet or outlet port.

    Dragging from an outlet to an inlet creates a connector.
    """

    def __init__(self, direction, parent_node_item):
        super().__init__(-RADIUS, -RADIUS, RADIUS * 2, RADIUS * 2,
                         parent_node_item)
        self.direction = direction  # "inlet" or "outlet"
        self.parent_node_item = parent_node_item
        self._is_outlet = (direction == "outlet")

        color = QColor("#4a90d9") if self._is_outlet else QColor("#50c878")
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#333"), 1.5))
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.setToolTip(f"{'Outlet' if self._is_outlet else 'Inlet'} port")

    def mousePressEvent(self, event):
        if self._is_outlet and event.button() == Qt.LeftButton:
            scene = self.scene()
            if scene and hasattr(scene, "start_connector_drag"):
                scene.start_connector_drag(self)
                event.accept()
                return
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor("#ffcc00")))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        color = QColor("#4a90d9") if self._is_outlet else QColor("#50c878")
        self.setBrush(QBrush(color))
        super().hoverLeaveEvent(event)

    def get_scene_center(self) -> QPointF:
        """Return this port's center in scene coordinates."""
        return self.mapToScene(self.boundingRect().center())
