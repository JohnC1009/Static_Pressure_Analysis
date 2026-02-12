"""GUI components for Static Pressure Analysis."""

import sys
from PyQt5.QtWidgets import QApplication
from static_pressure_analysis.gui.main_window import MainWindow


def run_app():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
