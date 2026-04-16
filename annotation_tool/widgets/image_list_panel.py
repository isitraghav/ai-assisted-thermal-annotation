"""Left sidebar: scrollable image list with thumbnails and annotation counts."""

from __future__ import annotations

import io
from pathlib import Path

from PyQt5.QtCore import Qt, QSize, pyqtSignal, QThread, QMutex
from PyQt5.QtGui import QPixmap, QImage, QIcon
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem

THUMB_W, THUMB_H = 80, 60
ITEM_HEIGHT = 80


class ThumbnailLoader(QThread):
    """Background thread that loads image thumbnails and emits them."""

    thumbnail_ready = pyqtSignal(int, QPixmap)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: list[tuple[int, Path]] = []
        self._mutex = QMutex()
        self._running = True

    def enqueue(self, idx: int, path: Path):
        self._mutex.lock()
        self._queue.append((idx, path))
        self._mutex.unlock()

    def stop(self):
        self._running = False

    def run(self):
        from PIL import Image

        while self._running:
            self._mutex.lock()
            if self._queue:
                idx, path = self._queue.pop(0)
                self._mutex.unlock()
            else:
                self._mutex.unlock()
                self.msleep(50)
                continue

            try:
                pil = Image.open(path).convert("RGB")
                pil.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
                buf = io.BytesIO()
                pil.save(buf, format="PNG")
                buf.seek(0)
                qimg = QImage()
                qimg.loadFromData(buf.read(), "PNG")
                px = QPixmap.fromImage(qimg)
                self.thumbnail_ready.emit(idx, px)
            except Exception:
                pass


class ImageListPanel(QWidget):
    """Left sidebar showing all images as a scrollable list with thumbnails."""

    navigate = pyqtSignal(int)  # absolute image index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self._image_paths: list[Path] = []
        self._annotation_counts: dict[int, int] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("Images")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-weight: bold; padding: 4px; background: #2a2a2a;")
        layout.addWidget(header)

        self._list = QListWidget()
        self._list.setIconSize(QSize(THUMB_W, THUMB_H))
        self._list.setSpacing(2)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        self._loader = ThumbnailLoader(self)
        self._loader.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._loader.start()

    def set_images(self, image_paths: list[Path]):
        self._image_paths = list(image_paths)
        self._annotation_counts.clear()
        self._list.clear()
        for i, p in enumerate(image_paths):
            item = QListWidgetItem(p.name)
            item.setData(Qt.UserRole, i)
            item.setSizeHint(QSize(200, ITEM_HEIGHT))
            self._list.addItem(item)
            self._loader.enqueue(i, p)

    def set_current(self, idx: int):
        if 0 <= idx < self._list.count():
            self._list.setCurrentRow(idx)
            item = self._list.item(idx)
            if item:
                self._list.scrollToItem(item)

    def update_annotation_count(self, idx: int, count: int):
        self._annotation_counts[idx] = count
        item = self._list.item(idx)
        if item and 0 <= idx < len(self._image_paths):
            name = self._image_paths[idx].name
            if count:
                item.setText(f"{name}\n{count} annotation(s)")
            else:
                item.setText(name)

    def _on_item_clicked(self, item: QListWidgetItem):
        idx = item.data(Qt.UserRole)
        if idx is not None:
            self.navigate.emit(idx)

    def _on_thumbnail_ready(self, idx: int, px: QPixmap):
        item = self._list.item(idx)
        if item:
            item.setIcon(QIcon(px))

    def closeEvent(self, event):
        self._loader.stop()
        self._loader.wait(500)
        super().closeEvent(event)
