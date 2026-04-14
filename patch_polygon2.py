import re
with open('annotation_tool/canvas/polygon_item.py', 'r') as f:
    text = f.read()

# patch vertex
v_class = '''class PolygonVertex(QGraphicsEllipseItem):
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
'''

text = re.sub(r'class PolygonVertex\(QGraphicsEllipseItem\):.*?return super\(\)\.itemChange\(change, value\)', v_class.strip(), text, flags=re.DOTALL)

with open('annotation_tool/canvas/polygon_item.py', 'w') as f:
    f.write(text)

