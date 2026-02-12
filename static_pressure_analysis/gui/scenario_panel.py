"""Bottom panel with a scenario table for per-fan overrides."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QTableWidget, QTableWidgetItem,
                              QHeaderView)

from static_pressure_analysis.models import Project, Scenario, NodeType


class ScenarioPanel(QWidget):
    """Editable table of scenarios with per-fan airflow and SP overrides."""

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header row with buttons
        header_layout = QHBoxLayout()
        title = QLabel("Scenarios")
        title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        header_layout.addWidget(title)
        header_layout.addStretch()

        add_btn = QPushButton("+ Add Scenario")
        add_btn.setFixedHeight(26)
        add_btn.clicked.connect(self._add_scenario)
        header_layout.addWidget(add_btn)

        remove_btn = QPushButton("- Remove")
        remove_btn.setFixedHeight(26)
        remove_btn.clicked.connect(self._remove_scenario)
        header_layout.addWidget(remove_btn)

        layout.addLayout(header_layout)

        # Table
        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self._table)

        self._fan_ids: list[str] = []
        self.rebuild()

    def rebuild(self):
        """Rebuild the table from self.project."""
        self._table.blockSignals(True)

        fans = [(nid, n) for nid, n in self.project.nodes.items()
                if n.node_type == NodeType.FAN]

        # Columns: Scenario Name | Fan1 Airflow | Fan1 SP | ...
        col_count = 1 + len(fans) * 2
        self._table.setColumnCount(col_count)

        headers = ["Scenario"]
        self._fan_ids = []
        for fid, fan in fans:
            headers.append(f"{fan.name}\nAirflow (CFM)")
            headers.append(f"{fan.name}\nSP (in. w.g.)")
            self._fan_ids.append(fid)
        self._table.setHorizontalHeaderLabels(headers)

        # Ensure at least one scenario exists
        if not self.project.scenarios:
            self.project.scenarios.append(Scenario(name="Baseline"))

        self._table.setRowCount(len(self.project.scenarios))

        for row, scenario in enumerate(self.project.scenarios):
            self._table.setItem(row, 0, QTableWidgetItem(scenario.name))

            for fi, fid in enumerate(self._fan_ids):
                fan_node = self.project.nodes.get(fid)
                overrides = scenario.fan_overrides.get(fid, {})

                default_af = fan_node.parameters.airflow if fan_node else 0
                default_sp = (fan_node.parameters.static_pressure
                              if fan_node else 0)

                af_val = overrides.get("airflow", default_af)
                sp_val = overrides.get("static_pressure", default_sp)

                col_af = 1 + fi * 2
                col_sp = 2 + fi * 2

                self._table.setItem(
                    row, col_af, QTableWidgetItem(str(af_val)))
                self._table.setItem(
                    row, col_sp, QTableWidgetItem(str(sp_val)))

        self._table.blockSignals(False)

    def _on_cell_changed(self, row, col):
        if row >= len(self.project.scenarios):
            return
        scenario = self.project.scenarios[row]
        item = self._table.item(row, col)
        if not item:
            return
        text = item.text()

        if col == 0:
            scenario.name = text
        else:
            fi = (col - 1) // 2
            is_sp = (col - 1) % 2 == 1

            if fi < len(self._fan_ids):
                fid = self._fan_ids[fi]
                if fid not in scenario.fan_overrides:
                    scenario.fan_overrides[fid] = {}
                try:
                    val = float(text)
                except ValueError:
                    return
                key = "static_pressure" if is_sp else "airflow"
                scenario.fan_overrides[fid][key] = val

    def _add_scenario(self):
        name = f"Scenario {len(self.project.scenarios) + 1}"
        self.project.scenarios.append(Scenario(name=name))
        self.rebuild()

    def _remove_scenario(self):
        row = self._table.currentRow()
        if row >= 0 and len(self.project.scenarios) > 1:
            self.project.scenarios.pop(row)
            self.rebuild()
