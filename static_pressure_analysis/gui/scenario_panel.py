"""Bottom scenario and results panel."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
                              QTableWidget, QTableWidgetItem, QPushButton,
                              QHeaderView, QTextEdit, QLabel, QAbstractItemView)

from static_pressure_analysis.models import (
    Project, Scenario, NodeType, FanParameters,
)
from static_pressure_analysis.analysis import AnalysisResult


class ScenarioPanel(QWidget):
    """Tabbed widget: Scenarios (editable table) + Results (text display)."""

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # -- Scenarios tab -------------------------------------------------
        scen_widget = QWidget()
        scen_layout = QVBoxLayout(scen_widget)
        scen_layout.setContentsMargins(4, 4, 4, 4)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("Add Scenario")
        add_btn.clicked.connect(self._add_scenario)
        toolbar.addWidget(add_btn)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_scenario)
        toolbar.addWidget(remove_btn)

        toolbar.addWidget(QLabel("  Double-click cells to edit overrides"))
        toolbar.addStretch()
        scen_layout.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.cellChanged.connect(self._on_cell_changed)
        scen_layout.addWidget(self.table)

        self.tabs.addTab(scen_widget, "Scenarios")

        # -- Results tab ---------------------------------------------------
        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        result_layout.setContentsMargins(4, 4, 4, 4)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFont(QFont("Courier", 10))
        result_layout.addWidget(self.result_text)

        self.tabs.addTab(result_widget, "Results")

    # -- Public API --------------------------------------------------------

    def rebuild_table(self):
        """Rebuild the scenario table with current fans as columns."""
        self.table.blockSignals(True)

        fans = self._get_fan_nodes()

        # Columns: Scenario Name + per fan (Base CFM, Override CFM, Base SP, Override SP)
        col_count = 1 + len(fans) * 4
        self.table.setColumnCount(col_count)

        headers = ["Scenario"]
        for fan in fans:
            short = fan.name[:14]
            headers.extend([
                f"{short}\nBase CFM",
                f"{short}\nOvr CFM",
                f"{short}\nBase SP",
                f"{short}\nOvr SP",
            ])
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )

        # Rows
        self.table.setRowCount(len(self.project.scenarios))

        for row, scen in enumerate(self.project.scenarios):
            # Scenario name
            item = QTableWidgetItem(scen.name)
            self.table.setItem(row, 0, item)

            for fi, fan in enumerate(fans):
                p = fan.parameters
                base_cfm = p.airflow if isinstance(p, FanParameters) else 0
                base_sp = p.static_pressure if isinstance(p, FanParameters) else 0
                ov = scen.fan_overrides.get(fan.id, {})
                ov_cfm = ov.get("airflow", "")
                ov_sp = ov.get("static_pressure", "")

                col_base = 1 + fi * 4

                # Base CFM (read-only)
                bcfm = QTableWidgetItem(f"{base_cfm:.0f}")
                bcfm.setFlags(bcfm.flags() & ~Qt.ItemIsEditable)
                bcfm.setBackground(Qt.lightGray)
                self.table.setItem(row, col_base, bcfm)

                # Override CFM (editable)
                self.table.setItem(row, col_base + 1,
                                   QTableWidgetItem(str(ov_cfm) if ov_cfm != "" else ""))

                # Base SP (read-only)
                bsp = QTableWidgetItem(f"{base_sp:.2f}")
                bsp.setFlags(bsp.flags() & ~Qt.ItemIsEditable)
                bsp.setBackground(Qt.lightGray)
                self.table.setItem(row, col_base + 2, bsp)

                # Override SP (editable)
                self.table.setItem(row, col_base + 3,
                                   QTableWidgetItem(str(ov_sp) if ov_sp != "" else ""))

        self.table.blockSignals(False)

    def show_results(self, results: list[AnalysisResult]):
        """Display analysis results in the Results tab."""
        self.result_text.clear()
        for res in results:
            self.result_text.append(f"{'='*60}")
            self.result_text.append(f" Scenario: {res.scenario_name or 'Baseline'}")
            self.result_text.append(f"{'='*60}")

            if res.warnings:
                for w in res.warnings:
                    self.result_text.append(f"  WARNING: {w}")

            self.result_text.append(
                f"  {'Node':<25} {'Type':<18} {'SP (in.wg)':>12} {'Airflow (CFM)':>14}"
            )
            self.result_text.append(
                f"  {'-'*25} {'-'*18} {'-'*12} {'-'*14}"
            )

            for nid, sp in res.pressures.items():
                node = self.project.nodes.get(nid)
                if not node:
                    continue
                af = res.airflows.get(nid, 0)
                self.result_text.append(
                    f"  {node.name:<25} {node.node_type.value:<18} {sp:>+12.3f} {af:>14.0f}"
                )
            self.result_text.append("")

        self.tabs.setCurrentIndex(1)

    def get_selected_scenario_index(self) -> int | None:
        """Return the selected row index or None."""
        rows = self.table.selectionModel().selectedRows()
        if rows:
            return rows[0].row()
        return None

    # -- Internal ----------------------------------------------------------

    def _get_fan_nodes(self):
        return [n for n in self.project.nodes.values()
                if n.node_type == NodeType.FAN]

    def _add_scenario(self):
        name = f"Scenario {len(self.project.scenarios) + 1}"
        self.project.scenarios.append(Scenario(name=name))
        self.rebuild_table()

    def _remove_scenario(self):
        idx = self.get_selected_scenario_index()
        if idx is not None and 0 <= idx < len(self.project.scenarios):
            self.project.scenarios.pop(idx)
            self.rebuild_table()

    def _on_cell_changed(self, row, col):
        """Persist cell edits back to the Scenario model."""
        if row < 0 or row >= len(self.project.scenarios):
            return
        scen = self.project.scenarios[row]

        if col == 0:
            # Scenario name
            item = self.table.item(row, 0)
            if item:
                scen.name = item.text()
            return

        # Figure out which fan and which field
        fans = self._get_fan_nodes()
        fan_idx = (col - 1) // 4
        field_offset = (col - 1) % 4

        if fan_idx < 0 or fan_idx >= len(fans):
            return

        # field_offset: 0=base_cfm(readonly), 1=ovr_cfm, 2=base_sp(readonly), 3=ovr_sp
        if field_offset not in (1, 3):
            return

        fan = fans[fan_idx]
        item = self.table.item(row, col)
        val_str = item.text().strip() if item else ""

        overrides = scen.fan_overrides.get(fan.id, {})

        if field_offset == 1:  # Override CFM
            if val_str:
                try:
                    overrides["airflow"] = float(val_str)
                except ValueError:
                    overrides.pop("airflow", None)
            else:
                overrides.pop("airflow", None)
        elif field_offset == 3:  # Override SP
            if val_str:
                try:
                    overrides["static_pressure"] = float(val_str)
                except ValueError:
                    overrides.pop("static_pressure", None)
            else:
                overrides.pop("static_pressure", None)

        if overrides:
            scen.fan_overrides[fan.id] = overrides
        else:
            scen.fan_overrides.pop(fan.id, None)
