"""Right-side property editor for selected nodes and connectors."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QFormLayout,
                              QDoubleSpinBox, QLineEdit, QGroupBox,
                              QScrollArea, QFrame)

from static_pressure_analysis.models import (
    FanParameters, DamperParameters,
    MixingPlenumParameters, DuctSplitParameters, PressureOutputParameters,
)


class PropertyPanel(QWidget):
    """Dynamically builds a form for the selected node or connector."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self._current_node = None
        self._current_connector = None

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

    # ── Public API ───────────────────────────────────────────────────

    def show_node(self, node):
        """Rebuild the form for the given Node."""
        self._clear()
        self._current_node = node
        self._title.setText(node.node_type.value)

        # General group
        gen_group = QGroupBox("General")
        gen_form = QFormLayout()
        gen_group.setLayout(gen_form)

        name_edit = QLineEdit(node.name)
        name_edit.textChanged.connect(lambda v: setattr(node, "name", v))
        gen_form.addRow("Name", name_edit)
        self._layout.addWidget(gen_group)

        # Parameters group
        params = node.parameters
        param_group = QGroupBox("Parameters")
        param_form = QFormLayout()
        param_group.setLayout(param_form)

        if isinstance(params, FanParameters):
            self._add_spin(param_form, "BHP", params.bhp, 0, 1000, 1,
                           lambda v: setattr(params, "bhp", v))
            self._add_spin(param_form, "Static Pressure (in. w.g.)",
                           params.static_pressure, 0, 20, 2,
                           lambda v: setattr(params, "static_pressure", v))
            self._add_spin(param_form, "Airflow (CFM)", params.airflow,
                           0, 100000, 0,
                           lambda v: setattr(params, "airflow", v))

        elif isinstance(params, DamperParameters):
            self._add_spin(param_form, "Pressure Drop (in. w.g.)",
                           params.pressure_drop, 0, 10, 2,
                           lambda v: setattr(params, "pressure_drop", v))

        elif isinstance(params, MixingPlenumParameters):
            self._add_spin(param_form, "Pressure Drop (in. w.g.)",
                           params.pressure_drop, 0, 10, 2,
                           lambda v: setattr(params, "pressure_drop", v))

        elif isinstance(params, DuctSplitParameters):
            self._add_spin(param_form, "Pressure Drop (in. w.g.)",
                           params.pressure_drop, 0, 10, 2,
                           lambda v: setattr(params, "pressure_drop", v))

        elif isinstance(params, PressureOutputParameters):
            label_edit = QLineEdit(params.label)
            label_edit.textChanged.connect(
                lambda v: setattr(params, "label", v)
            )
            param_form.addRow("Label", label_edit)

        self._layout.addWidget(param_group)
        self._layout.addStretch()

    def show_connector(self, connector):
        """Rebuild the form for the given Connector."""
        self._clear()
        self._current_connector = connector
        self._title.setText("Duct Connector")

        group = QGroupBox("Duct Properties")
        form = QFormLayout()
        group.setLayout(form)

        self._add_spin(form, "Length (ft)", connector.length, 0, 10000, 1,
                       lambda v: setattr(connector, "length", v))
        self._add_spin(form, "Diameter (in)", connector.diameter, 1, 120, 1,
                       lambda v: setattr(connector, "diameter", v))
        self._add_spin(form, "Friction Rate (in/100ft)",
                       connector.friction_rate, 0, 1, 4,
                       lambda v: setattr(connector, "friction_rate", v))

        label_edit = QLineEdit(connector.label)
        label_edit.textChanged.connect(
            lambda v: setattr(connector, "label", v)
        )
        form.addRow("Label", label_edit)

        # Calculated pressure drop (read-only)
        pd_label = QLabel(f"{connector.pressure_drop:.4f} in. w.g.")
        pd_label.setFont(QFont("Consolas", 9))
        form.addRow("Pressure Drop", pd_label)

        self._layout.addWidget(group)
        self._layout.addStretch()

    def clear_selection(self):
        self._clear()
        self._title.setText("No Selection")

    # ── Internal ─────────────────────────────────────────────────────

    def _clear(self):
        self._current_node = None
        self._current_connector = None
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _add_spin(self, form, label, value, min_val, max_val, decimals,
                  callback):
        sb = QDoubleSpinBox()
        sb.setDecimals(decimals)
        sb.setRange(min_val, max_val)
        sb.setValue(value)
        sb.valueChanged.connect(callback)
        form.addRow(label, sb)
        return sb
