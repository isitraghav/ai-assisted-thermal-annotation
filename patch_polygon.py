import re

with open('annotation_tool/canvas/polygon_item.py', 'r') as f:
    content = f.read()

# I will use a rewrite replacing PolygonItem entirely with an editable version
