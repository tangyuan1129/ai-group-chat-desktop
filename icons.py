# -*- coding: utf-8 -*-
"""用 QPainter 画的一小组线性图标。

为什么自己画：项目里没有图标资源，用 emoji 当图标在不同字体下长相不一、
还会带上彩色，跟 ChatGPT 那种单色线性图标完全不搭。自己画能保证
线宽、圆角、配色完全一致，也不引第三方依赖。
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

__all__ = ["plus", "clock", "people", "sliders", "dots", "folder", "file",
           "gear", "arrow_up", "square_stop", "monitor", "grid", "chevron_down",
           "avatar"]


def _canvas(size: int):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    return pixmap, painter


def _pen(color: str, size: int, weight: float = None) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(weight if weight is not None else max(1.4, size / 13.0))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def plus(color: str, size: int = 20) -> QPixmap:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, size))
    pad = size * 0.22
    mid = size / 2.0
    painter.drawLine(QPointF(pad, mid), QPointF(size - pad, mid))
    painter.drawLine(QPointF(mid, pad), QPointF(mid, size - pad))
    painter.end()
    return pixmap


def clock(color: str, size: int = 20) -> QPixmap:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, size))
    pad = size * 0.16
    painter.drawEllipse(QRectF(pad, pad, size - pad * 2, size - pad * 2))
    mid = size / 2.0
    painter.drawLine(QPointF(mid, mid - size * 0.22), QPointF(mid, mid))
    painter.drawLine(QPointF(mid, mid), QPointF(mid + size * 0.18, mid + size * 0.10))
    painter.end()
    return pixmap


def people(color: str, size: int = 20) -> QPixmap:
    """两个人形：后面一个略小、略淡，做出层次。"""
    pixmap, painter = _canvas(size)

    painter.setPen(_pen(color, size))
    painter.setBrush(QColor(color))
    # 前面的人
    head_r = size * 0.15
    painter.drawEllipse(QPointF(size * 0.42, size * 0.36), head_r, head_r)
    body = QPainterPath()
    body.moveTo(size * 0.16, size * 0.84)
    body.arcTo(QRectF(size * 0.16, size * 0.52, size * 0.52, size * 0.46), 180, -180)
    painter.drawPath(body)

    # 后面的人（描边、不填充，避免糊成一团）
    back = QColor(color)
    back.setAlpha(120)
    painter.setPen(_pen(back.name(), size))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(size * 0.70, size * 0.34), head_r * 0.85, head_r * 0.85)
    arc = QPainterPath()
    arc.moveTo(size * 0.52, size * 0.80)
    arc.arcTo(QRectF(size * 0.50, size * 0.54, size * 0.42, size * 0.40), 180, -140)
    painter.drawPath(arc)
    painter.end()
    return pixmap


def sliders(color: str, size: int = 20) -> QPixmap:
    """三条带滑块的横线 —— 设置类的通用图标，比齿轮好画也更好认。"""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, size))
    left, right = size * 0.18, size * 0.82
    knobs = (0.34, 0.66, 0.44)
    for i, ratio in enumerate((0.26, 0.5, 0.74)):
        y = size * ratio
        painter.drawLine(QPointF(left, y), QPointF(right, y))
        x = left + (right - left) * knobs[i]
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(x, y), size * 0.085, size * 0.085)
        painter.setBrush(Qt.NoBrush)
    painter.end()
    return pixmap


def dots(color: str, size: int = 20) -> QPixmap:
    pixmap, painter = _canvas(size)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    r = size * 0.075
    for i in range(3):
        painter.drawEllipse(QPointF(size * (0.26 + i * 0.24), size / 2.0), r, r)
    painter.end()
    return pixmap


def folder(color: str, size: int = 16) -> QPixmap:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, size, weight=1.3))
    body = QRectF(size * 0.12, size * 0.26, size * 0.76, size * 0.52)
    painter.drawRoundedRect(body, size * 0.12, size * 0.12)
    tab = QPainterPath()
    tab.moveTo(size * 0.12, size * 0.36)
    tab.lineTo(size * 0.12, size * 0.22)
    tab.lineTo(size * 0.42, size * 0.22)
    tab.lineTo(size * 0.50, size * 0.32)
    painter.drawPath(tab)
    painter.end()
    return pixmap


def file(color: str, size: int = 16) -> QPixmap:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, size, weight=1.3))
    path = QPainterPath()
    path.moveTo(size * 0.24, size * 0.14)
    path.lineTo(size * 0.62, size * 0.14)
    path.lineTo(size * 0.78, size * 0.32)
    path.lineTo(size * 0.78, size * 0.86)
    path.lineTo(size * 0.24, size * 0.86)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(QPointF(size * 0.62, size * 0.14), QPointF(size * 0.62, size * 0.32))
    painter.drawLine(QPointF(size * 0.62, size * 0.32), QPointF(size * 0.78, size * 0.32))
    painter.end()
    return pixmap


def gear(color: str, size: int = 16) -> QPixmap:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, size, weight=1.3))
    mid = size / 2.0
    r_out = size * 0.36
    r_in = size * 0.13
    painter.drawEllipse(QPointF(mid, mid), r_in, r_in)
    import math
    for i in range(8):
        angle = math.pi / 4 * i
        x0 = mid + math.cos(angle) * (r_in + size * 0.08)
        y0 = mid + math.sin(angle) * (r_in + size * 0.08)
        x1 = mid + math.cos(angle) * r_out
        y1 = mid + math.sin(angle) * r_out
        painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    painter.end()
    return pixmap


def arrow_up(color: str, size: int = 18) -> QPixmap:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, size, weight=max(1.8, size / 9.0)))
    mid = size / 2.0
    painter.drawLine(QPointF(mid, size * 0.78), QPointF(mid, size * 0.24))
    painter.drawLine(QPointF(mid, size * 0.24), QPointF(size * 0.30, size * 0.50))
    painter.drawLine(QPointF(mid, size * 0.24), QPointF(size * 0.70, size * 0.50))
    painter.end()
    return pixmap


def square_stop(color: str, size: int = 14) -> QPixmap:
    pixmap, painter = _canvas(size)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    side = size * 0.52
    painter.drawRoundedRect(
        QRectF((size - side) / 2.0, (size - side) / 2.0, side, side),
        size * 0.12, size * 0.12)
    painter.end()
    return pixmap


def monitor(color: str, size: int = 16) -> QPixmap:
    """显示器 —— ChatGPT 工具行最右边那个。"""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, size, weight=1.3))
    painter.drawRoundedRect(
        QRectF(size * 0.10, size * 0.20, size * 0.80, size * 0.50),
        size * 0.10, size * 0.10)
    painter.drawLine(QPointF(size * 0.34, size * 0.82), QPointF(size * 0.66, size * 0.82))
    painter.drawLine(QPointF(size * 0.50, size * 0.70), QPointF(size * 0.50, size * 0.82))
    painter.end()
    return pixmap


def grid(color: str, size: int = 16) -> QPixmap:
    """田字格 —— ChatGPT 右上角那个面板图标。"""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, size, weight=1.3))
    gap = size * 0.10
    half = (size - gap * 3) / 2.0
    for row in range(2):
        for col in range(2):
            painter.drawRoundedRect(
                QRectF(gap + col * (half + gap), gap + row * (half + gap), half, half),
                size * 0.08, size * 0.08)
    painter.end()
    return pixmap


def chevron_down(color: str, size: int = 14) -> QPixmap:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, size, weight=1.5))
    mid = size / 2.0
    painter.drawLine(QPointF(size * 0.28, size * 0.42), QPointF(mid, size * 0.62))
    painter.drawLine(QPointF(mid, size * 0.62), QPointF(size * 0.72, size * 0.42))
    painter.end()
    return pixmap


def avatar(color: str, initials: str, size: int = 30) -> QPixmap:
    """圆形头像 —— 图标栏最底下那两个。"""
    from PySide6.QtGui import QFont
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    if initials:
        painter.setPen(QColor("#FFFFFF"))
        font = QFont("Microsoft YaHei UI", max(6, int(size * 0.32)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, initials)
    painter.end()
    return pixmap


if __name__ == "__main__":
    import os
    import sys

    from PySide6.QtGui import QGuiApplication
    # QPixmap 必须先有 app 才能构造，否则直接崩（这里以前就是这么崩的）
    QGuiApplication.instance() or QGuiApplication(sys.argv)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_icon_preview")
    os.makedirs(out, exist_ok=True)
    for name in __all__:
        # 头像多一个"缩写"参数，不能按统一的 (颜色, 尺寸) 调
        pixmap = (globals()[name]("#ECECEC", "AI", 40) if name == "avatar"
                  else globals()[name]("#ECECEC", 40))
        pixmap.save(os.path.join(out, "%s.png" % name))
    print("已输出预览图到 %s" % out)
