"""QGraphicsScene for the flow diagram — handles drops, connector wiring, selection."""

from PyQt5.QtCore import Qt, pyqtSignal, QPointF
from PyQt5.QtWidgets import QGraphicsScene

from static_pressure_analysis.models import Node, NodeType, Connector
from .node_item import NodeItem
from .port_item import PortItem
from .connector_item import ConnectorItem, TempConnectorItem


class FlowScene(QGraphicsScene):
    """Scene managing equipment nodes and connector wiring."""

    node_selected = pyqtSignal(object)       # emits Node
    connector_selected = pyqtSignal(object)  # emits Connector
    selection_cleared = pyqtSignal()

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self._node_items: dict = {}        # node_id -> NodeItem
        self._connector_items: dict = {}   # connector_id -> ConnectorItem

        self._dragging_connector = False
        self._temp_connector: TempConnectorItem | None = None
        self._drag_source_port: PortItem | None = None

        self.setSceneRect(-2000, -2000, 6000, 6000)
        self.selectionChanged.connect(self._on_selection_changed)

    # ── Drop from toolbox ────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        type_name = event.mimeData().text()
        try:
            node_type = NodeType(type_name)
        except ValueError:
            return

        pos = event.scenePos()
        node = Node(node_type=node_type)
        node.x = pos.x()
        node.y = pos.y()
        self.project.add_node(node)

        item = NodeItem(node)
        item.setPos(pos)
        self.addItem(item)
        self._node_items[node.id] = item

    # ── Connector wiring via port drag ───────────────────────────────

    def start_connector_drag(self, port_item: PortItem):
        """Begin drawing a temporary connector from an outlet port."""
        self._dragging_connector = True
        self._drag_source_port = port_item
        start = port_item.get_scene_center()
        self._temp_connector = TempConnectorItem(start)
        self.addItem(self._temp_connector)

    def mouseMoveEvent(self, event):
        if self._dragging_connector and self._temp_connector:
            self._temp_connector.update_end(event.scenePos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging_connector:
            self._finish_connector_drag(event.scenePos())
        super().mouseReleaseEvent(event)

    def _finish_connector_drag(self, end_pos: QPointF):
        # Clean up temp line
        if self._temp_connector:
            self.removeItem(self._temp_connector)
            self._temp_connector = None
        self._dragging_connector = False

        # Find target port under the cursor
        target_port = None
        for item in self.items(end_pos):
            if isinstance(item, PortItem) and item.direction == "inlet":
                target_port = item
                break

        if target_port is None or target_port == self._drag_source_port:
            self._drag_source_port = None
            return

        src_node = self._drag_source_port.parent_node_item.node
        tgt_node = target_port.parent_node_item.node

        # No self-connections
        if src_node.id == tgt_node.id:
            self._drag_source_port = None
            return

        connector = Connector(source_id=src_node.id, target_id=tgt_node.id)
        self.project.add_connector(connector)

        ci = ConnectorItem(connector, self._drag_source_port, target_port)
        self.addItem(ci)
        self._connector_items[connector.id] = ci

        self._drag_source_port = None

    # ── Connector path updates when nodes move ───────────────────────

    def update_connectors_for_node(self, node_id: str):
        for c in self.project.connectors.values():
            if c.source_id == node_id or c.target_id == node_id:
                ci = self._connector_items.get(c.id)
                if ci:
                    ci.update_path()

    # ── Update node displays after analysis ──────────────────────────

    def update_node_displays(self, result):
        for nid, ni in self._node_items.items():
            lines = []
            if nid in result.pressures:
                lines.append(f"SP: {result.pressures[nid]:.2f} in. w.g.")
            if nid in result.airflows:
                lines.append(f"Airflow: {result.airflows[nid]:.0f} CFM")
            ni.set_status(lines)

    def clear_status(self):
        for ni in self._node_items.values():
            ni.set_status([])

    # ── Selection handling ───────────────────────────────────────────

    def _on_selection_changed(self):
        selected = self.selectedItems()
        node_items = [i for i in selected if isinstance(i, NodeItem)]
        conn_items = [i for i in selected if isinstance(i, ConnectorItem)]

        if node_items:
            self.node_selected.emit(node_items[0].node)
        elif conn_items:
            self.connector_selected.emit(conn_items[0].connector)
        else:
            self.selection_cleared.emit()

    # ── Deletion ─────────────────────────────────────────────────────

    def delete_selected(self):
        """Remove selected nodes and connectors from both scene and project."""
        for item in list(self.selectedItems()):
            if isinstance(item, ConnectorItem):
                self.project.remove_connector(item.connector.id)
                self._connector_items.pop(item.connector.id, None)
                self.removeItem(item)
            elif isinstance(item, NodeItem):
                # Remove attached connectors first
                attached = [
                    cid for cid, c in self.project.connectors.items()
                    if c.source_id == item.node.id
                    or c.target_id == item.node.id
                ]
                for cid in attached:
                    ci = self._connector_items.pop(cid, None)
                    if ci:
                        self.removeItem(ci)
                self.project.remove_node(item.node.id)
                self._node_items.pop(item.node.id, None)
                self.removeItem(item)

    # ── Rebuild from project (after load / new) ──────────────────────

    def rebuild(self):
        """Clear the scene and recreate all items from self.project."""
        self.clear()
        self._node_items.clear()
        self._connector_items.clear()

        for node in self.project.nodes.values():
            item = NodeItem(node)
            item.setPos(node.x, node.y)
            self.addItem(item)
            self._node_items[node.id] = item

        for c in self.project.connectors.values():
            src_ni = self._node_items.get(c.source_id)
            tgt_ni = self._node_items.get(c.target_id)
            if src_ni and tgt_ni:
                sp = src_ni.get_outlet_port()
                tp = tgt_ni.get_inlet_port()
                if sp and tp:
                    ci = ConnectorItem(c, sp, tp)
                    self.addItem(ci)
                    self._connector_items[c.id] = ci
