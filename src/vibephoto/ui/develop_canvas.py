"""The Develop canvas — image viewer with zoom/pan, before/after, and overlays.

Fits the rendered preview to the widget, and supports zoom (scroll wheel toward
the cursor, or +/- buttons), pan (left-drag when zoomed in), and Fit↔100%
(double-click). Composition overlays (thirds, golden ratio/spiral, …) draw on top
with adjustable opacity/rotation/flip. It holds no editing logic — the
:class:`DevelopModule` hands it finished frames as ``QImage``s.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QWidget

from vibephoto.processing.mask import Mask
from vibephoto.ui.crop_overlay import (
    crop_handles,
    drag_crop_handle,
    hit_crop_handle,
    inside_crop,
    move_crop,
)
from vibephoto.ui.mask_overlay import (
    drag_handle,
    hit_handle,
    inside_radial,
    mask_handles,
    paint_dab,
)
from vibephoto.ui.overlays import Overlay, draw_overlay

_MAX_ZOOM = 8.0


def ndarray_to_qimage(arr: NDArray[np.uint8]) -> QImage:
    """Convert a contiguous ``(H, W, 3)`` uint8 RGB array to a standalone QImage."""
    contiguous = np.ascontiguousarray(arr)
    height, width = contiguous.shape[0], contiguous.shape[1]
    image = QImage(contiguous.data, width, height, 3 * width, QImage.Format.Format_RGB888)
    return image.copy()  # detach from the NumPy buffer so Qt owns the pixels


class DevelopCanvas(QWidget):
    """Displays the rendered preview with zoom/pan, before/after, and overlays."""

    zoom_changed = Signal(float)  # zoom relative to fit (1.0 = fit-to-window)
    point_picked = Signal(float, float)  # normalized (x, y) in the image, for the WB eyedropper
    mask_edited = Signal(object)  # the edited Mask, after a handle drag or brush stroke
    crop_changed = Signal(object)  # the edited crop rect (left, top, right, bottom)
    crop_rotated = Signal(float)  # straighten angle (degrees) from dragging outside the box

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._after = QPixmap()
        self._before = QPixmap()
        self._show_before = False
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._dragging = False
        self._picking = False
        self._last_pos = QPointF(0.0, 0.0)
        self._overlay = Overlay.NONE
        self._overlay_opacity = 0.5
        self._overlay_rotation = 0
        self._flip_h = False
        self._flip_v = False
        # Mask editing: when a mask is being edited it draws over the image and the
        # mouse manipulates it (drag handles, or paint brush dabs) instead of panning.
        self._edit_mask: Mask | None = None
        self._brush_radius = 0.06
        self._active_handle: str | None = None
        self._painting = False
        # Crop tool: when active, draws the crop rectangle over the (uncropped) image
        # and the mouse resizes/moves it.
        self._crop_mode = False
        self._crop_rect: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
        self._crop_handle: str | None = None
        self._crop_moving = False
        self._crop_angle = 0.0  # current straighten angle (for drag-to-rotate)
        self._crop_rotating = False
        self._crop_rot_base = 0.0
        self._crop_rot_mouse0 = 0.0
        self._crop_last = (0.0, 0.0)
        self.setMinimumSize(360, 300)
        self.setStyleSheet("background:#0e0f11;")
        self.setMouseTracking(True)

    # -- image ------------------------------------------------------------- #

    def set_images(self, after: QImage, before: QImage) -> None:
        self._after = QPixmap.fromImage(after)
        self._before = QPixmap.fromImage(before)
        self.update()

    def clear(self) -> None:
        self._after = QPixmap()
        self._before = QPixmap()
        self.update()

    def set_show_before(self, show: bool) -> None:
        self._show_before = show
        self.update()

    def reset_view(self) -> None:
        """Return to fit-to-window (called when a new photo opens)."""
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.zoom_changed.emit(self._zoom)
        self.update()

    # -- overlays ---------------------------------------------------------- #

    def set_overlay(self, overlay: Overlay) -> None:
        self._overlay = overlay
        self.update()

    def set_overlay_opacity(self, opacity: float) -> None:
        self._overlay_opacity = opacity
        self.update()

    def rotate_overlay(self) -> None:
        self._overlay_rotation = (self._overlay_rotation + 90) % 360
        self.update()

    def set_overlay_flip_h(self, flip: bool) -> None:
        self._flip_h = flip
        self.update()

    def set_overlay_flip_v(self, flip: bool) -> None:
        self._flip_v = flip
        self.update()

    # -- zoom -------------------------------------------------------------- #

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom * 1.25)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom / 1.25)

    def toggle_fit_100(self) -> None:
        pixmap = self._current_pixmap()
        if pixmap.isNull():
            return
        if abs(self._zoom - 1.0) < 0.01:
            self._zoom = max(1.0, 1.0 / self._fit_scale(pixmap))  # 100%
        else:
            self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._after_zoom_change()

    def _set_zoom(self, zoom: float) -> None:
        self._zoom = max(1.0, min(_MAX_ZOOM, zoom))
        self._after_zoom_change()

    def _after_zoom_change(self) -> None:
        self._clamp_pan()
        self.zoom_changed.emit(self._zoom)
        self.update()

    # -- geometry ---------------------------------------------------------- #

    def _current_pixmap(self) -> QPixmap:
        if self._show_before and not self._before.isNull():
            return self._before
        return self._after

    def _fit_scale(self, pixmap: QPixmap) -> float:
        if pixmap.isNull() or pixmap.width() == 0 or pixmap.height() == 0:
            return 1.0
        return min(self.width() / pixmap.width(), self.height() / pixmap.height())

    def _display_rect(self, pixmap: QPixmap) -> QRectF:
        scale = self._fit_scale(pixmap) * self._zoom
        dw = pixmap.width() * scale
        dh = pixmap.height() * scale
        x = (self.width() - dw) / 2 + self._pan.x()
        y = (self.height() - dh) / 2 + self._pan.y()
        return QRectF(x, y, dw, dh)

    def _clamp_pan(self) -> None:
        pixmap = self._current_pixmap()
        if pixmap.isNull():
            return
        scale = self._fit_scale(pixmap) * self._zoom
        max_x = max(0.0, (pixmap.width() * scale - self.width()) / 2)
        max_y = max(0.0, (pixmap.height() * scale - self.height()) / 2)
        self._pan.setX(max(-max_x, min(max_x, self._pan.x())))
        self._pan.setY(max(-max_y, min(max_y, self._pan.y())))

    # -- events ------------------------------------------------------------ #

    def wheelEvent(self, event: QWheelEvent) -> None:
        pixmap = self._current_pixmap()
        if pixmap.isNull():
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
        new_zoom = max(1.0, min(_MAX_ZOOM, self._zoom * factor))
        if new_zoom == self._zoom:
            return
        rect = self._display_rect(pixmap)
        cursor = event.position()
        old_scale = self._fit_scale(pixmap) * self._zoom
        img_x = (cursor.x() - rect.left()) / old_scale
        img_y = (cursor.y() - rect.top()) / old_scale
        self._zoom = new_zoom
        new_scale = self._fit_scale(pixmap) * self._zoom
        center_x = (self.width() - pixmap.width() * new_scale) / 2
        center_y = (self.height() - pixmap.height() * new_scale) / 2
        self._pan.setX(cursor.x() - img_x * new_scale - center_x)
        self._pan.setY(cursor.y() - img_y * new_scale - center_y)
        self._after_zoom_change()

    def set_pick_mode(self, active: bool) -> None:
        """Arm/disarm the eyedropper: the next left-click samples instead of panning."""
        self._picking = active
        if active:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()

    # -- mask editing ------------------------------------------------------- #

    def set_mask_edit(self, mask: object) -> None:
        """Edit ``mask`` on the canvas (drag handles / paint), or ``None`` to stop."""
        self._edit_mask = mask if isinstance(mask, Mask) else None
        self._active_handle = None
        self._painting = False
        if self._edit_mask is not None:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()
        self.update()

    def set_brush_radius(self, radius: float) -> None:
        self._brush_radius = max(0.01, min(0.5, radius))

    def _norm_point(self, event: QMouseEvent) -> tuple[float, float] | None:
        """The cursor position as a normalized image coordinate, or ``None``."""
        rect = self._display_rect(self._after)
        if rect.width() <= 0 or rect.height() <= 0:
            return None
        nx = (event.position().x() - rect.left()) / rect.width()
        ny = (event.position().y() - rect.top()) / rect.height()
        return (nx, ny)

    def _mask_press(self, event: QMouseEvent) -> bool:
        """Begin a mask edit if a mask is active; returns True if handled."""
        if self._edit_mask is None:
            return False
        point = self._norm_point(event)
        if point is None:
            return True
        nx, ny = point
        mask = self._edit_mask
        if mask.kind == "brush":
            self._painting = True
            self._edit_mask = paint_dab(mask, nx, ny, self._brush_radius)
            self.update()
            return True
        handle = hit_handle(mask, nx, ny)
        if handle is None and inside_radial(mask, nx, ny):
            handle = "center"
        self._active_handle = handle
        if handle is not None:
            self._edit_mask = drag_handle(mask, handle, nx, ny)
            self.update()
        return True

    def _mask_move(self, event: QMouseEvent) -> bool:
        if self._edit_mask is None:
            return False
        point = self._norm_point(event)
        if point is None:
            return True
        nx, ny = point
        if self._painting and self._edit_mask.kind == "brush":
            self._edit_mask = paint_dab(self._edit_mask, nx, ny, self._brush_radius)
            self.update()
        elif self._active_handle is not None:
            self._edit_mask = drag_handle(self._edit_mask, self._active_handle, nx, ny)
            self.mask_edited.emit(self._edit_mask)  # live-update the render
            self.update()
        return True

    def _mask_release(self) -> bool:
        if self._edit_mask is None:
            return False
        if self._painting or self._active_handle is not None:
            self.mask_edited.emit(self._edit_mask)
        self._painting = False
        self._active_handle = None
        return True

    # -- crop tool ---------------------------------------------------------- #

    def set_crop_mode(self, active: bool, rect: object = None, angle: float = 0.0) -> None:
        """Show + edit the crop rectangle over the uncropped image (or stop)."""
        self._crop_mode = active
        if isinstance(rect, tuple) and len(rect) == 4:
            self._crop_rect = tuple(float(v) for v in rect)  # type: ignore[assignment]
        self._crop_angle = angle
        self._crop_handle = None
        self._crop_moving = False
        self._crop_rotating = False
        if active:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()
        self.update()

    @staticmethod
    def _angle_at(nx: float, ny: float) -> float:
        """Angle (degrees) of a point about the image centre, for rotate-dragging."""
        return math.degrees(math.atan2(ny - 0.5, nx - 0.5))

    def _crop_press(self, event: QMouseEvent) -> bool:
        if not self._crop_mode:
            return False
        point = self._norm_point(event)
        if point is None:
            return True
        nx, ny = point
        handle = hit_crop_handle(self._crop_rect, nx, ny)
        self._crop_handle = handle
        if handle is not None:
            return True
        if inside_crop(self._crop_rect, nx, ny):
            self._crop_moving = True
            self._crop_last = (nx, ny)
        else:  # outside the box → rotate (Photoshop-style straighten)
            self._crop_rotating = True
            self._crop_rot_base = self._crop_angle
            self._crop_rot_mouse0 = self._angle_at(nx, ny)
        return True

    def _crop_move(self, event: QMouseEvent) -> bool:
        if not self._crop_mode:
            return False
        point = self._norm_point(event)
        if point is None:
            return True
        nx, ny = point
        if self._crop_handle is not None:
            self._crop_rect = drag_crop_handle(self._crop_rect, self._crop_handle, nx, ny)
            self.update()
        elif self._crop_moving:
            dx, dy = nx - self._crop_last[0], ny - self._crop_last[1]
            self._crop_rect = move_crop(self._crop_rect, dx, dy)
            self._crop_last = (nx, ny)
            self.update()
        elif self._crop_rotating:
            delta = self._angle_at(nx, ny) - self._crop_rot_mouse0
            self._crop_angle = max(-45.0, min(45.0, self._crop_rot_base - delta))
            self.crop_rotated.emit(self._crop_angle)  # module re-renders the rotated image
        return True

    def _crop_release(self) -> bool:
        if not self._crop_mode:
            return False
        if self._crop_handle is not None or self._crop_moving:
            self.crop_changed.emit(self._crop_rect)
        elif self._crop_rotating:
            self.crop_rotated.emit(self._crop_angle)
        self._crop_handle = None
        self._crop_moving = False
        self._crop_rotating = False
        return True

    def _emit_picked(self, event: QMouseEvent) -> bool:
        """If picking, emit the normalized image point under the cursor and disarm."""
        pixmap = self._current_pixmap()
        if pixmap.isNull():
            return False
        rect = self._display_rect(pixmap)
        if rect.width() <= 0 or rect.height() <= 0:
            return False
        nx = (event.position().x() - rect.left()) / rect.width()
        ny = (event.position().y() - rect.top()) / rect.height()
        if 0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0:
            self.point_picked.emit(float(nx), float(ny))
        self.set_pick_mode(False)
        return True

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._picking:
                self._emit_picked(event)
                return
            if self._crop_press(event):  # crop tool takes precedence
                return
            if self._mask_press(event):  # mask editing takes precedence over panning
                return
            self._dragging = True
            self._last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._crop_mode:
            self._crop_move(event)
            return
        if self._edit_mask is not None:
            self._mask_move(event)
            return
        if self._dragging:
            self._pan += event.position() - self._last_pos
            self._last_pos = event.position()
            self._clamp_pan()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._crop_release():
                return
            if self._mask_release():
                return
            self._dragging = False
            self.unsetCursor()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.toggle_fit_100()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0e0f11"))
        pixmap = self._current_pixmap()
        if pixmap.isNull():
            painter.setPen(QColor("#6b6f76"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Select a photo and press D to develop"
            )
            return
        rect = self._display_rect(pixmap)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
        draw_overlay(
            painter, rect.left(), rect.top(), rect.width(), rect.height(), self._overlay,
            opacity=self._overlay_opacity, rotation=self._overlay_rotation,
            flip_h=self._flip_h, flip_v=self._flip_v,
        )
        if self._crop_mode:
            self._draw_crop(painter, rect)
        if self._edit_mask is not None:
            self._draw_mask(painter, rect)
        if self._show_before:
            painter.setPen(QColor("#e6e7e9"))
            painter.drawText(int(rect.left()) + 10, int(rect.top()) + 22, "Before")

    def _draw_crop(self, painter: QPainter, rect: QRectF) -> None:
        """Dim outside the crop, draw the border, rule-of-thirds grid, and handles."""
        left, top, right, bottom = self._crop_rect
        cx0 = rect.left() + left * rect.width()
        cy0 = rect.top() + top * rect.height()
        cw = (right - left) * rect.width()
        ch = (bottom - top) * rect.height()
        crop = QRectF(cx0, cy0, cw, ch)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Dim the four bands outside the crop rectangle.
        shade = QColor(0, 0, 0, 130)
        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width(), cy0 - rect.top()), shade)
        painter.fillRect(
            QRectF(rect.left(), crop.bottom(), rect.width(), rect.bottom() - crop.bottom()), shade
        )
        painter.fillRect(QRectF(rect.left(), cy0, cx0 - rect.left(), ch), shade)
        painter.fillRect(QRectF(crop.right(), cy0, rect.right() - crop.right(), ch), shade)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(240, 240, 240, 220), 1.4))
        painter.drawRect(crop)
        # Rule-of-thirds guides.
        painter.setPen(QPen(QColor(240, 240, 240, 90), 0.8))
        for i in (1, 2):
            x = cx0 + cw * i / 3.0
            y = cy0 + ch * i / 3.0
            painter.drawLine(QPointF(x, cy0), QPointF(x, cy0 + ch))
            painter.drawLine(QPointF(cx0, y), QPointF(cx0 + cw, y))
        # Handles.
        painter.setBrush(QColor(240, 240, 240, 235))
        painter.setPen(QColor(20, 20, 20, 200))
        for _name, (hx, hy) in crop_handles(self._crop_rect).items():
            hx_px = rect.left() + hx * rect.width()
            hy_px = rect.top() + hy * rect.height()
            painter.drawRect(QRectF(hx_px - 4, hy_px - 4, 8, 8))

    def _draw_mask(self, painter: QPainter, rect: QRectF) -> None:
        """Draw the editable mask's shape + handles over the image."""
        mask = self._edit_mask
        if mask is None:
            return

        def to_px(nx: float, ny: float) -> QPointF:
            return QPointF(rect.left() + nx * rect.width(), rect.top() + ny * rect.height())

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(80, 180, 255, 220))
        pen.setWidthF(1.6)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if mask.kind == "radial":
            p = mask.params
            centre = to_px(float(p.get("cx", 0.5)), float(p.get("cy", 0.5)))
            rx = float(p.get("rx", 0.3)) * rect.width()
            ry = float(p.get("ry", 0.3)) * rect.height()
            painter.drawEllipse(centre, rx, ry)
        elif mask.kind == "linear":
            handles = mask_handles(mask)
            painter.drawLine(to_px(*handles["start"]), to_px(*handles["end"]))
        elif mask.kind == "brush":
            painter.setPen(QColor(80, 180, 255, 120))
            for dab in mask.params.get("dabs", []):
                painter.drawEllipse(
                    to_px(float(dab[0]), float(dab[1])),
                    float(dab[2]) * rect.width(),
                    float(dab[2]) * rect.height(),
                )
        # Handle knobs.
        painter.setBrush(QColor(80, 180, 255, 230))
        painter.setPen(QColor(20, 30, 40, 230))
        for _name, (hx, hy) in mask_handles(mask).items():
            painter.drawEllipse(to_px(hx, hy), 5.0, 5.0)
