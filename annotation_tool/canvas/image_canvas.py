"""ImageCanvas: QGraphicsView with image display, polygon overlay, zoom/pan."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QPixmap, QColor, QPen, QBrush, QWheelEvent, QKeyEvent,
    QImage,
)
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QGraphicsTextItem, QGraphicsItem,
)

from annotation_tool.canvas.polygon_item import PolygonItem, PolygonVertex

_ZOOM_FACTOR = 1.15
_MARKER_RADIUS = 6


class ImageCanvas(QGraphicsView):
    """Displays a thermal image with projected polygon overlays.

    Signals:
        polygon_clicked(shp_index)  — user clicked on a polygon
        polygon_dragged(shp_index, dx, dy)  — user dragged the marker (visual only)
    """

    polygon_clicked = pyqtSignal(int)
    polygon_modified = pyqtSignal(int, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        from PyQt5.QtGui import QPainter
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor(30, 30, 30)))

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._polygon_items: dict[int, PolygonItem] = {}       # shp_index → item
        self._marker_items: dict[int, QGraphicsEllipseItem] = {}
        self._selected_shp_index: int | None = None

        # Pan state
        self._panning = False
        self._pan_start = QPointF()
        self._user_zoomed = False   # reset on each new image, set True on wheel zoom

        # Loading overlay text
        self._loading_text: QGraphicsTextItem | None = None
        self._markings_visible = True

    def toggle_markings(self):
        """Toggle visibility of polygon items and markers."""
        self._markings_visible = not self._markings_visible
        for item in self._polygon_items.values():
            item.setVisible(self._markings_visible)
        for item in self._marker_items.values():
            item.setVisible(self._markings_visible)

    # ------------------------------------------------------------------
    # Image loading
    # ------------------------------------------------------------------

    def load_image(self, image_path: Path):
        """Display the image. Clears polygons; call populate_polygons() after projection."""
        self._clear_polygons()
        self._clear_markers()
        self._user_zoomed = False

        pxmap = _load_pixmap(image_path)

        if self._pixmap_item is None:
            self._pixmap_item = QGraphicsPixmapItem(pxmap)
            self._pixmap_item.setZValue(0)
            self._scene.addItem(self._pixmap_item)
        else:
            self._pixmap_item.setPixmap(pxmap)

        self._scene.setSceneRect(QRectF(self._pixmap_item.boundingRect()))
        QTimer.singleShot(0, lambda: self.fitInView(self._pixmap_item, Qt.KeepAspectRatio))
        self._show_loading_text("Projecting polygons…")

    def fit_view(self):
        """Fit image to current view size."""
        if self._pixmap_item:
            self._user_zoomed = False
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._user_zoomed and self._pixmap_item:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    # ------------------------------------------------------------------
    # Polygon management
    # ------------------------------------------------------------------

    def populate_polygons(
        self,
        pixel_dict: dict,
        annotations: dict,
        selected_shp_index: int | None = None,
    ):
        """Create PolygonItems for all visible polygons."""
        self._hide_loading_text()
        self._clear_polygons()
        # Ensure image is visible (fit if transform hasn't been manually changed)
        if self._pixmap_item and not self._user_zoomed:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

        for shp_idx, coords in pixel_dict.items():
            rec = annotations.get(shp_idx)
            item = PolygonItem(
                shp_index=shp_idx,
                pixel_coords=coords,
                annotated=rec is not None,
                anomaly_type=rec.anomaly if rec else None,
            )
            item.setVisible(self._markings_visible)
            self._scene.addItem(item)
            self._polygon_items[shp_idx] = item

        # Restore selection highlight
        if selected_shp_index is not None and selected_shp_index in self._polygon_items:
            self._polygon_items[selected_shp_index].set_selected(True)
            self._selected_shp_index = selected_shp_index

        # Rebuild markers for annotated panels
        for shp_idx, rec in annotations.items():
            if shp_idx in pixel_dict:
                self._add_marker(shp_idx, pixel_dict[shp_idx])

    def update_polygon_state(self, shp_idx: int, anomaly_type: str | None):
        """Update a single polygon's visual state."""
        item = self._polygon_items.get(shp_idx)
        if item:
            if anomaly_type is None:
                item.set_unannotated()
            else:
                item.set_annotated(anomaly_type)

    def get_selected_shp_index(self) -> int | None:
        return self._selected_shp_index

    def deselect(self):
        if self._selected_shp_index is not None:
            item = self._polygon_items.get(self._selected_shp_index)
            if item:
                item.set_selected(False)
            self._selected_shp_index = None

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and event.modifiers() & Qt.AltModifier
        ):
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            items = self._scene.items(scene_pos)
            
            if items:
                top_item = items[0]
                # If we clicked a draggable vertex handle, let it handle the drag
                if isinstance(top_item, PolygonVertex):
                    super().mousePressEvent(event)
                    return

            clicked_poly = None
            for item in items:
                if isinstance(item, PolygonItem):
                    clicked_poly = item
                    break

            # Deselect previous
            if self._selected_shp_index is not None:
                old = self._polygon_items.get(self._selected_shp_index)
                if old:
                    old.set_selected(False)
                self._selected_shp_index = None

            if clicked_poly is not None:
                clicked_poly.set_selected(True)
                self._selected_shp_index = clicked_poly.shp_index()
                self.polygon_clicked.emit(self._selected_shp_index)
                super().mousePressEvent(event)
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.MiddleButton, Qt.LeftButton) and self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        self._user_zoomed = True
        if event.angleDelta().y() > 0:
            self.scale(_ZOOM_FACTOR, _ZOOM_FACTOR)
        else:
            self.scale(1.0 / _ZOOM_FACTOR, 1.0 / _ZOOM_FACTOR)
        event.accept()

    # ------------------------------------------------------------------
    # Markers (draggable pins on annotated panels)
    # ------------------------------------------------------------------

    def _add_marker(self, shp_idx: int, coords: list):
        """Add a small draggable marker at the polygon centroid."""
        # Compute centroid from coords
        pts = [(pt[0], pt[1]) for pt in coords if pt is not None]
        if not pts:
            return
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        r = _MARKER_RADIUS
        marker = _DraggableMarker(shp_idx, cx - r, cy - r, r * 2, r * 2)
        marker.setVisible(self._markings_visible)
        self._scene.addItem(marker)
        self._marker_items[shp_idx] = marker

    def remove_marker(self, shp_idx: int):
        marker = self._marker_items.pop(shp_idx, None)
        if marker:
            self._scene.removeItem(marker)

    def add_or_update_marker(self, shp_idx: int, coords: list):
        self.remove_marker(shp_idx)
        self._add_marker(shp_idx, coords)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clear_polygons(self):
        for item in self._polygon_items.values():
            self._scene.removeItem(item)
        self._polygon_items.clear()
        self._selected_shp_index = None

    def _clear_markers(self):
        for item in self._marker_items.values():
            self._scene.removeItem(item)
        self._marker_items.clear()

    def _show_loading_text(self, text: str):
        self._hide_loading_text()
        self._loading_text = QGraphicsTextItem(text)
        self._loading_text.setDefaultTextColor(QColor(255, 255, 100))
        self._loading_text.setZValue(10)
        # Position in top-left of image
        self._loading_text.setPos(10, 10)
        self._scene.addItem(self._loading_text)

    def _hide_loading_text(self):
        if self._loading_text:
            self._scene.removeItem(self._loading_text)
            self._loading_text = None


def _load_pixmap(image_path: Path) -> QPixmap:
    """Load a JPEG (including DJI RJPEG) as QPixmap via PIL to avoid Qt codec issues."""
    try:
        from PIL import Image
        import io as _io
        pil_img = Image.open(image_path).convert("RGB")
        buf = _io.BytesIO()
        pil_img.save(buf, format="PNG")
        buf.seek(0)
        qimg = QImage()
        qimg.loadFromData(buf.read(), "PNG")
        if not qimg.isNull():
            return QPixmap.fromImage(qimg)
    except Exception:
        pass

    # Fallback 1: direct Qt load
    qimg = QImage(str(image_path))
    if not qimg.isNull():
        return QPixmap.fromImage(qimg)

    # Fallback 2: error placeholder (dark red)
    placeholder = QPixmap(640, 480)
    placeholder.fill(QColor(80, 20, 20))
    return placeholder


class _DraggableMarker(QGraphicsEllipseItem):
    """Small draggable annotation marker (visual only, does not change geometry)."""

    def __init__(self, shp_index: int, x: float, y: float, w: float, h: float):
        super().__init__(x, y, w, h)
        self._shp_index = shp_index
        self.setZValue(2)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setPen(QPen(QColor(255, 50, 50, 255), 1.5))
        self.setBrush(QBrush(QColor(255, 80, 80, 180)))
        self.setToolTip(f"Panel #{shp_index}")
