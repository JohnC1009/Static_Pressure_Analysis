"""QGraphicsView with zoom, pan, and grid background for the flow diagram."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtWidgets import QGraphicsView

GRID_SIZE = 40


class FlowView(QGraphicsView):
    """Scrollable, zoomable view of the flow diagram scene."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setAcceptDrops(True)
        self.setBackgroundBrush(QColor("#F0F0EC"))

        self._zoom = 1.0
        self._panning = False
        self._pan_start = None

    # ── Grid background ──────────────────────────────────────────────

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        pen = QPen(QColor("#E2E2DE"), 0.5)
        painter.setPen(pen)

        left = int(rect.left()) - (int(rect.left()) % GRID_SIZE)
        top = int(rect.top()) - (int(rect.top()) % GRID_SIZE)

        x = left
        while x < rect.right():
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
            x += GRID_SIZE

        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)
            y += GRID_SIZE

    # ── Zoom with scroll wheel ───────────────────────────────────────

    def wheelEvent(self, event):
        factor = 1.15
        if event.angleDelta().y() > 0:
            self._zoom *= factor
            self.scale(factor, factor)
        else:
            self._zoom /= factor
            self.scale(1 / factor, 1 / factor)

    # ── Middle-click pan ─────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)
