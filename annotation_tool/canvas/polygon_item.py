"""QGraphicsPolygonItem subclass for shapefile panel polygons."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QColor, QPen, QBrush, QPolygonF
from PyQt5.QtWidgets import QGraphicsPolygonItem, QGraphicsItem, QGraphicsEllipseItem

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

_COLOR_UNANNOTATED_FILL = QColor(255, 255, 255, 20)
_COLOR_UNANNOTATED_LINE = QColor(255, 255, 255, 200)
_COLOR_ANNOTATED_LINE   = QColor(255, 165, 0, 220)
_COLOR_SELECTED_FILL    = QColor(180, 0, 0, 60)
_COLOR_SELECTED_LINE    = QColor(180, 0, 0, 255)
_LINE_WIDTH_NORMAL   = 1.0
_LINE_WIDTH_SELECTED = 2.5
_SELECTION_INSET     = 5  # pixels inset on each side when selected


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
        # Enable dragging the entire polygon
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setZValue(1)

        self._handles: list[PolygonVertex] = []
        self._apply_style()

    # ------------------------------------------------------------------
    def update_vertex(self, index: int, new_pos: QPointF):
        poly = self.polygon()
        poly[index] = new_pos
        self.setPolygon(poly)

    def notify_vertex_changed(self):
        poly = self.polygon()
        idx = 0
        new_coords = []
        for pt in self._pixel_coords:
            if pt is None:
                new_coords.append(None)
            else:
                new_p = poly[idx]
                new_coords.append([new_p.x(), new_p.y()])
                idx += 1
        self._pixel_coords = new_coords
        
        view = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if view and hasattr(view, 'polygon_modified'):
            view.polygon_modified.emit(self._shp_index, self._pixel_coords)

    def shp_index(self) -> int:
        return self._shp_index

    def is_annotated(self) -> bool:
        return self._annotated

    def anomaly_type(self) -> str | None:
        return self._anomaly_type

    # ------------------------------------------------------------------
    def _convert_to_resize_box(self):
        """Converts the arbitrary incoming polygon into a manageable 4-point rectangle/square."""
        poly = self.polygon()
        rect = poly.boundingRect()
        
        # A simple 4-corner bounding box for resizing
        p1 = rect.topLeft()
        p2 = rect.topRight()
        p3 = rect.bottomRight()
        p4 = rect.bottomLeft()
        
        new_poly = QPolygonF([p1, p2, p3, p4])
        self.setPolygon(new_poly)
        
        self._pixel_coords = [
            [p1.x(), p1.y()],
            [p2.x(), p2.y()],
            [p3.x(), p3.y()],
            [p4.x(), p4.y()]
        ]
        
        # Dispatch event so UI + Delta T calculations re-align
        if self.scene() and self.scene().views():
            view = self.scene().views()[0]
            if hasattr(view, 'polygon_modified'):
                view.polygon_modified.emit(self._shp_index, self._pixel_coords)

    def set_selected(self, selected: bool):
        if selected and not self._selected:
            self._convert_to_resize_box()
            
        self._selected = selected
        self._apply_style()
        self._update_handles()

    def set_annotated(self, anomaly_type: str | None):
        self._annotated = anomaly_type is not None
        self._anomaly_type = anomaly_type
        self._apply_style()

    def set_unannotated(self):
        self._annotated = False
        self._anomaly_type = None
        self._apply_style()

    def _update_handles(self):
        if self._selected:
            if not self._handles:
                poly = self.polygon()
                for i in range(poly.count()):
                    pt = poly.at(i)
                    handle = PolygonVertex(i, self)
                    handle.setPos(pt)
                    self._handles.append(handle)
        else:
            for handle in self._handles:
                if self.scene():
                    self.scene().removeItem(handle)
            self._handles.clear()

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
    def paint(self, painter, option, widget=None):
        if self._selected:
            i = _SELECTION_INSET
            rect = self.polygon().boundingRect().adjusted(i, i, -i, -i)
            painter.setBrush(self.brush())
            painter.setPen(self.pen())
            painter.drawRect(rect)
        else:
            super().paint(painter, option, widget)

    # ------------------------------------------------------------------
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        offset = self.pos()
        if offset.x() != 0.0 or offset.y() != 0.0:
            # Absorb the drag offset into _pixel_coords so scene coords stay correct
            new_coords = []
            for pt in self._pixel_coords:
                if pt is None:
                    new_coords.append(None)
                else:
                    new_coords.append([pt[0] + offset.x(), pt[1] + offset.y()])
            self._pixel_coords = new_coords
            # Rebuild polygon in local space at origin
            new_poly = QPolygonF([
                QPointF(pt[0], pt[1]) for pt in new_coords if pt is not None
            ])
            self.setPolygon(new_poly)
            self.setPos(0, 0)
            # Re-sync handle positions
            for i, handle in enumerate(self._handles):
                if i < new_poly.count():
                    handle.setPos(new_poly.at(i))
            # Notify screen
            if self.scene() and self.scene().views():
                view = self.scene().views()[0]
                if hasattr(view, 'polygon_modified'):
                    view.polygon_modified.emit(self._shp_index, self._pixel_coords)

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

class PolygonVertex(QGraphicsEllipseItem):
    """Draggable vertex handle for PolygonItem."""
    def __init__(self, index: int, parent_polygon: PolygonItem):
        super().__init__(-4, -4, 8, 8, parent_polygon)
        self._index = index
        self._polygon = parent_polygon
        self.setBrush(QBrush(QColor(255, 0, 0)))
        self.setPen(QPen(QColor(0, 0, 0), 1))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setZValue(10)
        self.setCursor(Qt.CrossCursor)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            self._polygon.update_vertex(self._index, value)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._polygon.notify_vertex_changed()
        # Re-sync handle visual position after drag
        poly = self._polygon.polygon()
        if self._index < poly.count():
            self.setPos(poly.at(self._index))
