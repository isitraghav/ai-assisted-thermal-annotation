"""QGraphicsPolygonItem subclass for shapefile panel polygons."""

from __future__ import annotations

import math

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QColor, QPen, QBrush, QPolygonF
from PyQt5.QtWidgets import (
    QGraphicsPolygonItem, QGraphicsItem, QGraphicsEllipseItem, QGraphicsLineItem,
)

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
_COLOR_SELECTED_FILL    = QColor(0, 220, 255, 40)
_COLOR_SELECTED_LINE    = QColor(0, 220, 255, 255)
_COLOR_VERTEX_FILL      = QColor(255, 255, 255, 255)
_COLOR_VERTEX_BORDER    = QColor(0, 180, 230, 255)
_COLOR_VERTEX_HOVER     = QColor(255, 220, 0, 255)
_COLOR_ROT_FILL         = QColor(0, 220, 255, 255)
_COLOR_ROT_BORDER       = QColor(255, 255, 255, 255)
_COLOR_ROT_LINE         = QColor(0, 220, 255, 180)
_COLOR_CENTROID         = QColor(255, 220, 0, 255)
_LINE_WIDTH_NORMAL   = 1.0
_LINE_WIDTH_SELECTED = 2.5


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
        self._rot_handle: RotationHandle | None = None
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
            self._simplify_to_corners()
        self._selected = selected
        self._apply_style()
        self._update_handles()

    def _simplify_to_corners(self):
        from shapely.geometry import Polygon as ShapelyPoly
        poly = self.polygon()
        pts = [(poly.at(i).x(), poly.at(i).y()) for i in range(poly.count())]
        if len(pts) < 3:
            return
        try:
            simplified = ShapelyPoly(pts).simplify(1.5, preserve_topology=True)
        except Exception:
            return
        if simplified.is_empty or simplified.geom_type != "Polygon":
            return
        corners = list(simplified.exterior.coords[:-1])  # drop closing duplicate
        if len(corners) < 3:
            return
        self.setPolygon(QPolygonF([QPointF(x, y) for x, y in corners]))
        self._pixel_coords = [[x, y] for x, y in corners]

    def _centroid(self) -> QPointF:
        poly = self.polygon()
        n = poly.count()
        cx = sum(poly.at(i).x() for i in range(n)) / n
        cy = sum(poly.at(i).y() for i in range(n)) / n
        return QPointF(cx, cy)

    def _rot_anchor_pos(self) -> QPointF:
        """Return snap position for rotation handle: below polygon, near centroid."""
        rect = self.polygon().boundingRect()
        cx = self._centroid().x()
        return QPointF(cx, rect.bottom() + RotationHandle._OFFSET)

    def rotate_by(self, delta_angle: float, centroid: QPointF):
        poly = self.polygon()
        cos_a = math.cos(delta_angle)
        sin_a = math.sin(delta_angle)
        new_pts = []
        for i in range(poly.count()):
            pt = poly.at(i)
            dx = pt.x() - centroid.x()
            dy = pt.y() - centroid.y()
            new_pts.append(QPointF(
                centroid.x() + dx * cos_a - dy * sin_a,
                centroid.y() + dx * sin_a + dy * cos_a,
            ))
        self.setPolygon(QPolygonF(new_pts))
        for i, handle in enumerate(self._handles):
            if i < len(new_pts):
                handle.setPos(new_pts[i])

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
                    handle = PolygonVertex(i, self)
                    handle.setPos(poly.at(i))
                    self._handles.append(handle)
            if self._rot_handle is None:
                self._rot_handle = RotationHandle(self)
                self._rot_handle.setPos(self._rot_anchor_pos())
        else:
            for handle in self._handles:
                if self.scene():
                    self.scene().removeItem(handle)
            self._handles.clear()
            if self._rot_handle is not None:
                self._rot_handle.cleanup()
                if self.scene():
                    self.scene().removeItem(self._rot_handle)
                self._rot_handle = None

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
        super().paint(painter, option, widget)

    # ------------------------------------------------------------------
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        offset = self.pos()
        if abs(offset.x()) > 0.5 or abs(offset.y()) > 0.5:
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
            if self._rot_handle is not None:
                self._rot_handle.setPos(self._rot_anchor_pos())
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
    _RADIUS = 6  # half-size in px

    def __init__(self, index: int, parent_polygon: PolygonItem):
        r = PolygonVertex._RADIUS
        super().__init__(-r, -r, r * 2, r * 2, parent_polygon)
        self._index = index
        self._polygon = parent_polygon
        self.setBrush(QBrush(_COLOR_VERTEX_FILL))
        self.setPen(QPen(_COLOR_VERTEX_BORDER, 1.8))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(11)
        self.setCursor(Qt.SizeAllCursor)

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(_COLOR_VERTEX_HOVER))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(_COLOR_VERTEX_FILL))
        super().hoverLeaveEvent(event)

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


class RotationHandle(QGraphicsEllipseItem):
    """Cyan handle above polygon — drag to rotate around centroid."""

    _OFFSET = 18  # px gap below polygon bottom edge
    _HANDLE_R = 8

    def __init__(self, parent_polygon: PolygonItem):
        r = RotationHandle._HANDLE_R
        super().__init__(-r, -r, r * 2, r * 2, parent_polygon)
        self._polygon = parent_polygon
        self._drag_centroid: QPointF | None = None
        self._last_angle: float | None = None

        self.setBrush(QBrush(_COLOR_ROT_FILL))
        self.setPen(QPen(_COLOR_ROT_BORDER, 2.0))
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setZValue(12)
        self.setCursor(Qt.OpenHandCursor)

        # Connection line from centroid to handle (child of polygon, not handle,
        # so it isn't affected by ItemIgnoresTransformations)
        self._line = QGraphicsLineItem(parent_polygon)
        pen = QPen(_COLOR_ROT_LINE, 1.2, Qt.DashLine)
        pen.setCosmetic(True)
        self._line.setPen(pen)
        self._line.setZValue(9)

        # Centroid marker
        self._centroid_dot = QGraphicsEllipseItem(-3, -3, 6, 6, parent_polygon)
        self._centroid_dot.setBrush(QBrush(_COLOR_CENTROID))
        self._centroid_dot.setPen(QPen(QColor(0, 0, 0), 1))
        self._centroid_dot.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self._centroid_dot.setZValue(11)

        self._refresh_decoration()

    def _refresh_decoration(self):
        c = self._polygon._centroid()
        self._centroid_dot.setPos(c)
        p = self.pos()
        self._line.setLine(c.x(), c.y(), p.x(), p.y())

    def setPos(self, *args, **kwargs):
        super().setPos(*args, **kwargs)
        if hasattr(self, "_line"):
            self._refresh_decoration()

    def cleanup(self):
        scene = self.scene()
        if scene:
            scene.removeItem(self._line)
            scene.removeItem(self._centroid_dot)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        c = self._polygon._centroid()
        self._drag_centroid = c
        sp = event.scenePos()
        self._last_angle = math.atan2(-(sp.y() - c.y()), sp.x() - c.x())
        self.setCursor(Qt.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._last_angle is None:
            event.ignore()
            return
        c = self._drag_centroid
        sp = event.scenePos()
        dx = sp.x() - c.x()
        dy = sp.y() - c.y()
        if dx * dx + dy * dy < 1:
            event.accept()
            return
        angle = math.atan2(-dy, dx)
        delta = (angle - self._last_angle + math.pi) % (2 * math.pi) - math.pi
        self._polygon.rotate_by(-delta, c)  # reversed
        self._last_angle = angle
        self.setPos(sp)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        if self._drag_centroid is not None:
            self._polygon.notify_vertex_changed()
        self._drag_centroid = None
        self._last_angle = None
        self.setCursor(Qt.OpenHandCursor)
        self.setPos(self._polygon._rot_anchor_pos())
        event.accept()
