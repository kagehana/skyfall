from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)


class RoundedCard(QWidget):
    def __init__(
        self,
        bg_color: str,
        radius: int = 12,
        border_color: str = "rgba(255,255,255,0.08)",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._bg = QColor(bg_color)
        self._radius = radius
        self._border = self._parse_rgba(border_color)

    @staticmethod
    def _parse_rgba(s: str) -> QColor:
        s = s.strip()
        if s.startswith("rgba"):
            inner = s[s.index("(") + 1 : s.rindex(")")]
            parts = [p.strip() for p in inner.split(",")]
            r, g, b = (int(parts[0]), int(parts[1]), int(parts[2]))
            a = int(round(float(parts[3]) * 255)) if len(parts) > 3 else 255
            return QColor(r, g, b, a)
        return QColor(s)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(self._bg)
        pen = QPen(self._border)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawRoundedRect(rect, self._radius, self._radius)
        p.end()


class StrokedButton(QPushButton):
    _STROKE = QColor(0, 0, 0, 55)
    _STROKE_W = 2.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._right_icon = None
        self._right_icon_sz = 12

    def set_right_icon(self, icon, size: int = 12) -> None:
        self._right_icon = icon
        self._right_icon_sz = size
        self.update()

    def paintEvent(self, event):
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        label = opt.text

        # capture the content rect while text is still set so the stylesheet
        # padding (which affects subElementRect) is accounted for correctly
        cr = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, opt, self
        )

        opt.text = ""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, opt, p, self)

        # right icon - draw relative to full widget rect so padding doesn't hide it
        if self._right_icon is not None:
            sz = self._right_icon_sz
            pm = self._right_icon.pixmap(sz, sz)
            r = self.rect()
            p.setOpacity(1.0)
            p.drawPixmap(r.right() - sz - 8, r.top() + (r.height() - sz) // 2, pm)

        if not label:
            return

        fm = QFontMetrics(self.font())
        y = cr.top() + (cr.height() - fm.height()) // 2 + fm.ascent()
        x = cr.left()

        # nudge text right to clear a left icon placed via setIcon()
        if not self.icon().isNull():
            x += self.iconSize().width() + 4

        path = QPainterPath()
        path.addText(x, y, self.font(), label)

        pen = QPen(self._STROKE)
        pen.setWidthF(self._STROKE_W)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.strokePath(path, pen)
        p.fillPath(path, opt.palette.buttonText().color())


PAGE_MARGINS = (28, 22, 28, 16)

MUTED_TEXT = "rgba(236,236,236,0.55)"
META_TEXT = "rgba(236,236,236,0.50)"
DIM_TEXT = "rgba(236,236,236,0.38)"
HAIRLINE_RGBA = "rgba(255,255,255,0.06)"


def accent_of(ctx) -> str:
    return getattr(ctx, "btn_color_hex", "#ff557f")


def page_layout(widget: QWidget) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*PAGE_MARGINS)
    layout.setSpacing(0)
    return layout


def hairline() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background-color: {HAIRLINE_RGBA}; border: none;")
    return line


def vrule() -> QFrame:
    line = QFrame()
    line.setFixedWidth(1)
    line.setStyleSheet(f"background-color: {HAIRLINE_RGBA}; border: none;")
    return line


def eyebrow(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        "color: rgba(236,236,236,0.45);"
        " font-size: 8pt;"
        " font-weight: 600;"
        " letter-spacing: 1.8px;"
    )
    return lbl


def heading(text: str, size_pt: int = 22) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: rgba(236,236,236,0.95);"
        f" font-size: {size_pt}pt;"
        f" font-weight: 700;"
        f" letter-spacing: 0.2px;"
    )
    return lbl


def subtitle(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {MUTED_TEXT}; font-size: 9pt; font-style: italic;")
    lbl.setWordWrap(True)
    return lbl


def meta(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {META_TEXT}; font-size: 8pt; letter-spacing: 0.4px;")
    return lbl


def stat_value(text: str = "—", size_pt: int = 28) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color: rgba(236,236,236,0.95);"
        f" font-size: {size_pt}pt;"
        f" font-weight: 700;"
        f" letter-spacing: -0.5px;"
    )
    return lbl


def mono_label(text: str = "", size_pt: float = 8.3) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color: rgba(236,236,236,0.85);"
        " font-family: 'Cascadia Mono', 'Consolas', monospace;"
        f" font-size: {size_pt}pt;"
    )
    return lbl


def switcher_styles(accent: str):
    active = (
        "QPushButton {"
        "  background: transparent;"
        "  color: rgba(236,236,236,0.95);"
        "  border: none;"
        f"  border-bottom: 2px solid {accent};"
        "  padding: 8px 0 6px 0;"
        "  margin: 0 22px 0 0;"
        "  font-size: 9pt;"
        "  font-weight: 700;"
        "  letter-spacing: 2px;"
        "  text-align: left;"
        "}"
    )
    inactive = (
        "QPushButton {"
        "  background: transparent;"
        f"  color: {DIM_TEXT};"
        "  border: none;"
        "  border-bottom: 2px solid transparent;"
        "  padding: 8px 0 6px 0;"
        "  margin: 0 22px 0 0;"
        "  font-size: 9pt;"
        "  font-weight: 500;"
        "  letter-spacing: 2px;"
        "  text-align: left;"
        "}"
        "QPushButton:hover { color: rgba(236,236,236,0.85); }"
    )
    return active, inactive


def make_switcher(labels: list[str], accent: str):
    active, inactive = switcher_styles(accent)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    btns: list[QPushButton] = []
    for label in labels:
        btn = QPushButton(label.upper())
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFlat(True)
        btn.setFixedHeight(30)
        btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        btns.append(btn)
        row.addWidget(btn)
    row.addStretch()

    def apply_active(idx: int):
        for i, b in enumerate(btns):
            b.setStyleSheet(active if i == idx else inactive)

    return row, btns, apply_active


def section_eyebrow_row(text: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    row.addWidget(eyebrow(text))
    row.addWidget(hairline(), 1)
    return row
