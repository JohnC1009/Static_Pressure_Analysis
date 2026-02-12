"""Main application window — assembles toolbox, canvas, property panel, and scenarios."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QMainWindow, QSplitter, QToolBar, QAction,
                              QMessageBox, QFileDialog, QStatusBar, QLabel)

from static_pressure_analysis.models import Project
from static_pressure_analysis.analysis import run_analysis, run_all_scenarios
from static_pressure_analysis.serialization import save_project, load_project
from static_pressure_analysis.gui.toolbox_panel import ToolboxPanel
from static_pressure_analysis.gui.canvas.flow_scene import FlowScene
from static_pressure_analysis.gui.canvas.flow_view import FlowView
from static_pressure_analysis.gui.property_panel import PropertyPanel
from static_pressure_analysis.gui.scenario_panel import ScenarioPanel


class MainWindow(QMainWindow):
    """
    Layout:
    +-----------------------------------------------------------+
    |  Toolbar: [Run] [Run All] [Save] [Open] [Delete] [Clear]  |
    +----------+----------------------------+-------------------+
    | Toolbox  |    Flow Diagram Canvas     |  Property         |
    |  Panel   |    (drag & drop nodes,     |  Editor           |
    |          |     wire connectors)       |  Panel            |
    +----------+----------------------------+-------------------+
    |              Scenarios / Results (tabs)                    |
    +-----------------------------------------------------------+
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Static Pressure Analysis")
        self.resize(1400, 850)
        self.setMinimumSize(1000, 600)

        self.project = Project()
        self._last_results = []

        self._setup_ui()
        self._create_toolbar()
        self._create_statusbar()
        self._connect_signals()

    # -- UI setup ----------------------------------------------------------

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

        # Vertical splitter: top row | scenario panel
        v_split = QSplitter(Qt.Vertical)
        v_split.addWidget(h_split)
        v_split.addWidget(self.scenario_panel)
        v_split.setSizes([550, 250])
        v_split.setStretchFactor(0, 1)
        v_split.setStretchFactor(1, 0)

        self.setCentralWidget(v_split)

    def _create_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 6px; padding: 4px; }")
        self.addToolBar(toolbar)

        run_act = QAction("Run Analysis", self)
        run_act.setShortcut(QKeySequence("F5"))
        run_act.setToolTip("Run analysis on selected scenario (F5)")
        run_act.triggered.connect(self._on_run)
        toolbar.addAction(run_act)

        run_all_act = QAction("Run All Scenarios", self)
        run_all_act.setToolTip("Run analysis on all scenarios")
        run_all_act.triggered.connect(self._on_run_all)
        toolbar.addAction(run_all_act)

        toolbar.addSeparator()

        save_act = QAction("Save", self)
        save_act.setShortcut(QKeySequence.Save)
        save_act.triggered.connect(self._on_save)
        toolbar.addAction(save_act)

        open_act = QAction("Open", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self._on_open)
        toolbar.addAction(open_act)

        toolbar.addSeparator()

        del_act = QAction("Delete Selected", self)
        del_act.setShortcut(QKeySequence.Delete)
        del_act.triggered.connect(self._on_delete)
        toolbar.addAction(del_act)

        clear_act = QAction("Clear All", self)
        clear_act.triggered.connect(self._on_clear)
        toolbar.addAction(clear_act)

    def _create_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._status_label = QLabel("Ready")
        self._statusbar.addWidget(self._status_label)

    def _connect_signals(self):
        self.canvas_scene.node_selected.connect(self.property_panel.show_node)
        self.canvas_scene.connector_selected.connect(
            lambda c: self.property_panel.show_connector(c, self.project)
        )
        self.canvas_scene.node_deselected.connect(
            self.property_panel.clear_selection
        )

    # -- Actions -----------------------------------------------------------

    def _on_run(self):
        # Rebuild scenario table in case new fans were added
        self.scenario_panel.rebuild_table()

        idx = self.scenario_panel.get_selected_scenario_index()
        if idx is not None and idx < len(self.project.scenarios):
            result = run_analysis(self.project, self.project.scenarios[idx])
        else:
            result = run_analysis(self.project)

        self._last_results = [result]
        self.canvas_scene.update_node_displays(self._last_results)
        self.scenario_panel.show_results(self._last_results)

        if result.warnings:
            self._status_label.setText(
                f"Analysis complete — {len(result.warnings)} warning(s)"
            )
        else:
            self._status_label.setText("Analysis complete")

    def _on_run_all(self):
        self.scenario_panel.rebuild_table()
        self._last_results = run_all_scenarios(self.project)
        self.canvas_scene.update_node_displays(self._last_results)
        self.scenario_panel.show_results(self._last_results)
        self._status_label.setText(
            f"Ran {len(self._last_results)} scenario(s)"
        )

    def _on_save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "",
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            try:
                save_project(self.project, path)
                self._status_label.setText(f"Saved: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", str(e))

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            try:
                self.project = load_project(path)
                self.canvas_scene.project = self.project
                self.canvas_scene.rebuild_from_project()
                self.scenario_panel.project = self.project
                self.scenario_panel.rebuild_table()
                self.property_panel.clear_selection()
                self._status_label.setText(f"Loaded: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Open Error", str(e))

    def _on_delete(self):
        self.canvas_scene.delete_selected()
        self.property_panel.clear_selection()
        self.scenario_panel.rebuild_table()

    def _on_clear(self):
        reply = QMessageBox.question(
            self, "Clear All",
            "Remove all nodes and connectors from the canvas?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.project.nodes.clear()
            self.project.connectors.clear()
            self.canvas_scene.rebuild_from_project()
            self.property_panel.clear_selection()
            self.scenario_panel.rebuild_table()
            self._status_label.setText("Canvas cleared")
