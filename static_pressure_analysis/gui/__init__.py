"""PyQt5 GUI for the Static Pressure Analysis tool."""

import sys
from PyQt5.QtWidgets import QApplication
from .main_window import MainWindow


def run_app():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.setWindowTitle("Static Pressure Analysis")
    window.resize(1400, 900)
    window.show()
    sys.exit(app.exec_())
