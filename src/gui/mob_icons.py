from __future__ import annotations

import io
from typing import Optional

from loguru import logger
from PyQt6.QtGui import QImage, QPainter, QPen, QPixmap, QColor
from PyQt6.QtCore import Qt


class IconCache:
    def __init__(self, fallback_size: int = 48):
        self._pixmaps: dict[int, QPixmap] = {}
        self._failed: set[int] = set()
        self._fallback_size = fallback_size
        self._fallback_pixmap: Optional[QPixmap] = None

    # public API

    def get(self, template_id: int) -> Optional[QPixmap]:
        return self._pixmaps.get(int(template_id))

    def get_or_fallback(self, template_id: int, *, size: int | None = None) -> QPixmap:
        px = self._pixmaps.get(int(template_id))
        if px is not None:
            return (
                px
                if size is None
                else px.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        return self._fallback(size or self._fallback_size)

    def has(self, template_id: int) -> bool:
        tid = int(template_id)
        return tid in self._pixmaps or tid in self._failed

    def ingest(self, template_id: int, raw_bytes: bytes) -> bool:
        tid = int(template_id)
        if tid in self._pixmaps:
            return True
        if not raw_bytes:
            self._failed.add(tid)
            return False
        try:
            from PIL import (
                Image,
            )  # local import: GUI may run before Pillow is installed

            img = Image.open(io.BytesIO(raw_bytes))
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            # QImage doesn't copy the buffer - copy() detaches before ``data``
            # goes out of scope, otherwise we'd render garbage
            self._pixmaps[tid] = QPixmap.fromImage(qimg.copy())
            return True
        except Exception as exc:
            logger.debug(f"[mob_icons] decode failed for template {tid}: {exc}")
            self._failed.add(tid)
            return False

    def clear(self) -> None:
        self._pixmaps.clear()
        self._failed.clear()
        self._fallback_pixmap = None

    # placeholder rendering

    def _fallback(self, size: int) -> QPixmap:
        if self._fallback_pixmap is not None and self._fallback_pixmap.width() == size:
            return self._fallback_pixmap
        px = QPixmap(size, size)
        px.fill(QColor(60, 60, 64))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(110, 110, 116))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawRect(0, 0, size - 1, size - 1)
        # diagonal hint that this is a placeholder
        p.drawLine(2, 2, size - 3, size - 3)
        p.drawLine(size - 3, 2, 2, size - 3)
        p.end()
        self._fallback_pixmap = px
        return px
