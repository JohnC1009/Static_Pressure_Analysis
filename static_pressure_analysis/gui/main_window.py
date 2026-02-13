"""Main application window — assembles toolbox, canvas, property panel, and scenarios."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence, QFont
from PyQt5.QtWidgets import (QMainWindow, QSplitter, QToolBar, QAction,
                              QMessageBox, QFileDialog, QStatusBar, QLabel,
                              QComboBox)

from static_pressure_analysis.models import Project, Scenario
from static_pressure_analysis.analysis import run_analysis, run_all_scenarios
from static_pressure_analysis.analysis_iterative import (
    run_iterative_analysis, run_all_iterative,
)
from static_pressure_analysis.serialization import save_project, load_project

from .toolbox_panel import ToolboxPanel
from .canvas.flow_scene import FlowScene
from .canvas.flow_view import FlowView
from .property_panel import PropertyPanel
from .scenario_panel import ScenarioPanel


class MainWindow(QMainWindow):
    """
    Layout:
    +----------+----------------------------+-----------------+
    | Toolbox  |     Flow Diagram Canvas    | Property Editor |
    |  Panel   |   (drag & drop nodes,     |     Panel       |
    |          |    wire connectors)        |                 |
    +----------+----------------------------+-----------------+
    |                 Scenario Table                          |
    +---------------------------------------------------------+
    """

    def __init__(self):
        super().__init__()
        self.project = Project()
        self._setup_ui()
        self._create_toolbar()
        self._create_statusbar()
        self._connect_signals()

    # ── UI setup ─────────────────────────────────────────────────────

    def _setup_ui(self):
        self.toolbox = ToolboxPanel()
        self.canvas_scene = FlowScene(self.project)
        self.canvas_view = FlowView()
        self.canvas_view.setScene(self.canvas_scene)
        self.property_panel = PropertyPanel()
        self.scenario_panel = ScenarioPanel(self.project)

        # Horizontal splitter: toolbox | canvas | property editor
        h_split = QSplitter(Qt.Horizontal)
        h_split.addWidget(self.toolbox)
        h_split.addWidget(self.canvas_view)
        h_split.addWidget(self.property_panel)
        h_split.setSizes([200, 800, 280])
        h_split.setStretchFactor(0, 0)
        h_split.setStretchFactor(1, 1)
        h_split.setStretchFactor(2, 0)

        # Vertical splitter: top row | scenario table
        v_split = QSplitter(Qt.Vertical)
        v_split.addWidget(h_split)
        v_split.addWidget(self.scenario_panel)
        v_split.setSizes([600, 200])
        v_split.setStretchFactor(0, 1)
        v_split.setStretchFactor(1, 0)

        self.setCentralWidget(v_split)

    def _create_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 6px; padding: 4px; }")
        self.addToolBar(toolbar)

        # New
        new_act = QAction("New", self)
        new_act.setShortcut(QKeySequence.New)
        new_act.setToolTip("New project (Ctrl+N)")
        new_act.triggered.connect(self._on_new)
        toolbar.addAction(new_act)

        # Open
        open_act = QAction("Open", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.setToolTip("Open project (Ctrl+O)")
        open_act.triggered.connect(self._on_open)
        toolbar.addAction(open_act)

        # Save
        save_act = QAction("Save", self)
        save_act.setShortcut(QKeySequence.Save)
        save_act.setToolTip("Save project (Ctrl+S)")
        save_act.triggered.connect(self._on_save)
        toolbar.addAction(save_act)

        toolbar.addSeparator()

        # Solver selector
        self._solver_combo = QComboBox()
        self._solver_combo.addItems(["BFS (Quick)", "Hardy-Cross (Iterative)"])
        self._solver_combo.setMinimumWidth(160)
        toolbar.addWidget(QLabel(" Solver: "))
        toolbar.addWidget(self._solver_combo)

        toolbar.addSeparator()

        # Scenario selector
        self._scenario_combo = QComboBox()
        self._scenario_combo.setMinimumWidth(150)
        self._update_scenario_combo()
        toolbar.addWidget(QLabel(" Scenario: "))
        toolbar.addWidget(self._scenario_combo)

        # Run analysis
        run_act = QAction("Run Analysis", self)
        run_act.setShortcut(QKeySequence("F5"))
        run_act.setToolTip("Run static pressure analysis (F5)")
        run_act.triggered.connect(self._on_run)
        toolbar.addAction(run_act)

        run_all_act = QAction("Run All", self)
        run_all_act.setToolTip("Run analysis for every scenario")
        run_all_act.triggered.connect(self._on_run_all)
        toolbar.addAction(run_all_act)

        toolbar.addSeparator()

        # Delete
        del_act = QAction("Delete Selected", self)
        del_act.setShortcut(QKeySequence.Delete)
        del_act.setToolTip("Delete selected items (Del)")
        del_act.triggered.connect(self._on_delete)
        toolbar.addAction(del_act)

    def _create_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._status_label = QLabel("Ready")
        self._statusbar.addWidget(self._status_label)

    def _connect_signals(self):
        self.canvas_scene.node_selected.connect(self.property_panel.show_node)
        self.canvas_scene.connector_selected.connect(
            self.property_panel.show_connector
        )
        self.canvas_scene.selection_cleared.connect(
            self.property_panel.clear_selection
        )

    def _update_scenario_combo(self):
        self._scenario_combo.clear()
        if not self.project.scenarios:
            self._scenario_combo.addItem("Baseline")
        else:
            for s in self.project.scenarios:
                self._scenario_combo.addItem(s.name)

    # ── Actions ──────────────────────────────────────────────────────

    def _on_new(self):
        reply = QMessageBox.question(
            self, "New Project",
            "Discard current project and start fresh?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.project = Project()
            self.canvas_scene.project = self.project
            self.canvas_scene.rebuild()
            self.scenario_panel.project = self.project
            self.scenario_panel.rebuild()
            self.property_panel.clear_selection()
            self._update_scenario_combo()
            self._status_label.setText("New project created")

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            "Static Pressure Project (*.spa);;JSON Files (*.json);;All (*)",
        )
        if path:
            try:
                self.project = load_project(path)
                self.canvas_scene.project = self.project
                self.canvas_scene.rebuild()
                self.scenario_panel.project = self.project
                self.scenario_panel.rebuild()
                self.property_panel.clear_selection()
                self._update_scenario_combo()
                self._status_label.setText(f"Loaded: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Open Error", str(e))

    def _on_save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "",
            "Static Pressure Project (*.spa);;JSON Files (*.json);;All (*)",
        )
        if path:
            try:
                save_project(self.project, path)
                self._status_label.setText(f"Saved: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", str(e))

    def _on_run(self):
        # Refresh scenario panel so overrides are current
        self.scenario_panel.rebuild()
        self._update_scenario_combo()

        idx = self._scenario_combo.currentIndex()
        if self.project.scenarios and 0 <= idx < len(self.project.scenarios):
            scenario = self.project.scenarios[idx]
        else:
            scenario = Scenario(name="Baseline")

        use_iterative = self._solver_combo.currentIndex() == 1
        if use_iterative:
            result = run_iterative_analysis(self.project, scenario)
        else:
            result = run_analysis(self.project, scenario)
        self.canvas_scene.update_node_displays(result)

        solver_tag = "Hardy-Cross" if use_iterative else "BFS"
        if result.warnings:
            self._status_label.setText(
                f"{solver_tag} complete — {len(result.warnings)} warning(s)"
            )
            QMessageBox.information(
                self, "Analysis Warnings", "\n".join(result.warnings)
            )
        else:
            count = len(result.pressures)
            extra = ""
            if use_iterative and hasattr(result, "iterations"):
                extra = f" ({result.iterations} iterations)"
            self._status_label.setText(
                f"{solver_tag} complete — {count} nodes calculated{extra}"
            )

    def _on_run_all(self):
        self.scenario_panel.rebuild()
        self._update_scenario_combo()

        use_iterative = self._solver_combo.currentIndex() == 1
        if use_iterative:
            results = run_all_iterative(self.project)
        else:
            results = run_all_scenarios(self.project)
        if results:
            # Display first scenario's results on canvas
            self.canvas_scene.update_node_displays(results[0])

        total_warnings = sum(len(r.warnings) for r in results)
        solver_tag = "Hardy-Cross" if use_iterative else "BFS"
        self._status_label.setText(
            f"{solver_tag}: Ran {len(results)} scenario(s) — {total_warnings} warning(s)"
        )

        # Show results summary dialog
        summary_parts = []
        for r in results:
            lines = [f"=== {r.scenario_name} ==="]
            for nid, sp in r.pressures.items():
                node = self.project.nodes.get(nid)
                name = node.name if node else nid
                af = r.airflows.get(nid, 0)
                lines.append(
                    f"  {name}: SP={sp:.2f} in.w.g.  Airflow={af:.0f} CFM"
                )
            if r.warnings:
                lines.extend(f"  WARNING: {w}" for w in r.warnings)
            summary_parts.append("\n".join(lines))

        QMessageBox.information(
            self, "Analysis Results", "\n\n".join(summary_parts)
        )

    def _on_delete(self):
        self.canvas_scene.delete_selected()
        self.property_panel.clear_selection()
        self.scenario_panel.rebuild()
        self._update_scenario_combo()
