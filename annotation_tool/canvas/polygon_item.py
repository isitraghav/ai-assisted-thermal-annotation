"""QGraphicsPolygonItem subclass for shapefile panel polygons."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QColor, QPen, QBrush, QPolygonF
from PyQt5.QtWidgets import QGraphicsPolygonItem, QGraphicsItem

# Per-category fill colors (RGBA)
_CATEGORY_COLORS: dict[str, tuple[int, int, int, int]] = {
    "Bypass Diode":          (220, 50,  50,  100),
    "Cell":                  (220, 100, 50,  100),
    "Dust":                  (160, 120, 60,  100),
    "Module Missing":        (80,  80,  80,  130),
    "Module Offline":        (100, 100, 200, 100),
    "Multi Cell":            (200, 60,  60,  100),
    "Partial String Offline":(180, 100, 220, 100),
    "Physical Damage":       (200, 50,  160, 100),
    "Shading":               (60,  100, 160, 100),
    "Short Circuit":         (255, 30,  30,  120),
    "String Offline":        (150, 80,  220, 100),
    "Vegetation":            (50,  160, 50,  100),
}

_COLOR_UNANNOTATED_FILL = QColor(0, 255, 0, 30)
_COLOR_UNANNOTATED_LINE = QColor(0, 255, 0, 200)
_COLOR_ANNOTATED_LINE   = QColor(255, 165, 0, 220)
_COLOR_SELECTED_FILL    = QColor(255, 255, 0, 120)
_COLOR_SELECTED_LINE    = QColor(255, 255, 0, 255)
_LINE_WIDTH_NORMAL  = 1.0
_LINE_WIDTH_SELECTED = 2.0


class PolygonItem(QGraphicsPolygonItem):
    """Represents one shapefile panel polygon on the canvas."""

    def __init__(
        self,
        shp_index: int,
        pixel_coords: list,          # list of (u,v) tuples; None = sub-poly separator
        annotated: bool = False,
        anomaly_type: str | None = None,
        parent=None,
    ):
        # Draw the actual polygon instead of a bounding box
        poly_pts = []
        for pt in pixel_coords:
            if pt is not None:
                poly_pts.append(QPointF(float(pt[0]), float(pt[1])))
                
        # Fallback if empty
        if not poly_pts:
            poly_pts = [
                QPointF(0, 0),
                QPointF(10, 0),
                QPointF(10, 10),
                QPointF(0, 10)
            ]

        super().__init__(QPolygonF(poly_pts), parent)
        self._shp_index = shp_index
        self._pixel_coords = pixel_coords
        self._annotated = annotated
        self._anomaly_type = anomaly_type
        self._selected = False

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setZValue(1)

        self._apply_style()

    # ------------------------------------------------------------------
    def shp_index(self) -> int:
        return self._shp_index

    def is_annotated(self) -> bool:
        return self._annotated

    def anomaly_type(self) -> str | None:
        return self._anomaly_type

    # ------------------------------------------------------------------
    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style()

    def set_annotated(self, anomaly_type: str | None):
        self._annotated = anomaly_type is not None
        self._anomaly_type = anomaly_type
        self._apply_style()

    def set_unannotated(self):
        self._annotated = False
        self._anomaly_type = None
        self._apply_style()

    # ------------------------------------------------------------------
    def _apply_style(self):
        if self._selected:
            pen = QPen(_COLOR_SELECTED_LINE, _LINE_WIDTH_SELECTED)
            brush = QBrush(_COLOR_SELECTED_FILL)
        elif self._annotated and self._anomaly_type:
            rgba = _CATEGORY_COLORS.get(self._anomaly_type, (255, 165, 0, 100))
            fill = QColor(*rgba)
            line = QColor(rgba[0], rgba[1], rgba[2], 220)
            pen = QPen(line, _LINE_WIDTH_NORMAL)
            brush = QBrush(fill)
        else:
            pen = QPen(_COLOR_UNANNOTATED_LINE, _LINE_WIDTH_NORMAL)
            brush = QBrush(_COLOR_UNANNOTATED_FILL)

        self.setPen(pen)
        self.setBrush(brush)

    # ------------------------------------------------------------------
    def hoverEnterEvent(self, event):
        if not self._selected:
            pen = self.pen()
            pen.setWidth(2)
            self.setPen(pen)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if not self._selected:
            self._apply_style()
        super().hoverLeaveEvent(event)
