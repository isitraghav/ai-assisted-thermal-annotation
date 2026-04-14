import re
with open('annotation_tool/canvas/polygon_item.py', 'r') as f:
    text = f.read()

# patch PolygonItem mouseReleaseEvent
release_func = '''    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.pos() != QPointF(0, 0):
            # Bake the translation into the polygon itself
            poly = self.polygon()
            translated_poly = poly.translated(self.pos())
            self.setPolygon(translated_poly)
            self.setPos(0, 0)
            
            # Reposition handles relative to new 0,0
            for i, handle in enumerate(self._handles):
                handle.setPos(translated_poly[i])
                
            self.notify_vertex_changed()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
'''

text = text.replace('    # ------------------------------------------------------------------', release_func + '\n    # ------------------------------------------------------------------', 1)

with open('annotation_tool/canvas/polygon_item.py', 'w') as f:
    f.write(text)

