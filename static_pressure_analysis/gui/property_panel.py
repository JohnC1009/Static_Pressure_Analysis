"""Right-side property editor for selected nodes and connectors."""

from dataclasses import fields as dataclass_fields

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QFormLayout,
                              QDoubleSpinBox, QLineEdit, QGroupBox,
                              QScrollArea, QFrame, QPushButton)

from static_pressure_analysis.models import (
    Node, Connector, NodeType,
    FanParameters, DamperParameters, MixingPlenumParameters,
    DuctSplitParameters, PressureOutputParameters,
)


class PropertyPanel(QWidget):
    """Dynamically builds a form for the selected node's or connector's parameters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self._current_node: Node | None = None
        self._current_connector: Connector | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        self._title = QLabel("No Selection")
        self._title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self._title.setAlignment(Qt.AlignCenter)
        outer.addWidget(self._title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(8)
        scroll.setWidget(self._inner)

    # -- Public API --------------------------------------------------------

    def show_node(self, node: Node):
        """Rebuild the form for the given node."""
        self._clear()
        self._current_node = node
        self._current_connector = None
        self._title.setText(f"{node.node_type.value}: {node.name}")

        # Name editor
        name_group = QGroupBox("Identity")
        name_form = QFormLayout()
        name_group.setLayout(name_form)
        name_edit = QLineEdit(node.name)
        name_edit.textChanged.connect(lambda v: setattr(node, "name", v))
        name_form.addRow("Name", name_edit)
        self._layout.addWidget(name_group)

        # Parameters
        params = node.parameters
        param_group = QGroupBox("Parameters")
        param_form = QFormLayout()
        param_group.setLayout(param_form)

        for f in dataclass_fields(type(params)):
            val = getattr(params, f.name)
            label_text = f.name.replace("_", " ").title()

            if isinstance(val, float):
                sb = QDoubleSpinBox()
                sb.setDecimals(4)
                sb.setRange(-1e9, 1e9)
                sb.setValue(val)
                sb.valueChanged.connect(
                    lambda v, attr=f.name: setattr(params, attr, v)
                )
                param_form.addRow(label_text, sb)
            elif isinstance(val, str):
                le = QLineEdit(val)
                le.textChanged.connect(
                    lambda v, attr=f.name: setattr(params, attr, v)
                )
                param_form.addRow(label_text, le)

        self._layout.addWidget(param_group)
        self._layout.addStretch()

    def show_connector(self, connector: Connector, project=None):
        """Rebuild the form for the given connector."""
        self._clear()
        self._current_connector = connector
        self._current_node = None
        self._title.setText("Duct Connector")

        # Endpoint info
        if project:
            src = project.nodes.get(connector.source_id)
            tgt = project.nodes.get(connector.target_id)
            info_group = QGroupBox("Endpoints")
            info_form = QFormLayout()
            info_group.setLayout(info_form)
            info_form.addRow("From", QLabel(src.name if src else "?"))
            info_form.addRow("To", QLabel(tgt.name if tgt else "?"))
            self._layout.addWidget(info_group)

        # Duct properties
        prop_group = QGroupBox("Duct Properties")
        prop_form = QFormLayout()
        prop_group.setLayout(prop_form)

        for attr, label, unit in [
            ("label", "Label", ""),
            ("length", "Length", "ft"),
            ("diameter", "Diameter", "in"),
            ("friction_rate", "Friction Rate", "in/100ft"),
        ]:
            val = getattr(connector, attr)
            disp = f"{label} ({unit})" if unit else label

            if isinstance(val, float):
                sb = QDoubleSpinBox()
                sb.setDecimals(4)
                sb.setRange(0, 1e9)
                sb.setValue(val)
                sb.valueChanged.connect(
                    lambda v, a=attr: setattr(connector, a, v)
                )
                prop_form.addRow(disp, sb)
            elif isinstance(val, str):
                le = QLineEdit(val)
                le.textChanged.connect(
                    lambda v, a=attr: setattr(connector, a, v)
                )
                prop_form.addRow(disp, le)

        self._layout.addWidget(prop_group)

        # Computed pressure drop
        dp_label = QLabel(f"{connector.pressure_drop:.4f} in.wg")
        dp_label.setFont(QFont("Consolas", 9))
        dp_group = QGroupBox("Computed")
        dp_form = QFormLayout()
        dp_group.setLayout(dp_form)
        dp_form.addRow("Pressure Drop", dp_label)
        self._layout.addWidget(dp_group)

        self._layout.addStretch()

    def clear_selection(self):
        self._clear()
        self._title.setText("No Selection")

    # -- Internal ----------------------------------------------------------

    def _clear(self):
        self._current_node = None
        self._current_connector = None
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
