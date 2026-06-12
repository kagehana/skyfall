from loguru import logger

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal

from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap

from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


from src.gui.editorial import StrokedButton
from src.gui.commands import GUICommand, GUICommandType

from src.gui.helpers import (
    repo_icon_btn,
)

from src.gui.widgets import (
    AnimatedStackedWidget,
    DuelCircleWidget,
)


class _LiveStatBar(QWidget):
    def __init__(
        self,
        fill_color: QColor,
        track_color: QColor = QColor(255, 255, 255, 18),
        height: int = 14,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._fill = fill_color
        self._track = track_color
        self._value: float = 0
        self._max: float = 0
        self._suffix = ""
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, value, maximum, suffix: str = "") -> None:
        self._value = float(value or 0)
        self._max = float(maximum or 0)
        self._suffix = suffix
        self.update()

    def paintEvent(self, _ev):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        track_path = QPainterPath()
        track_path.addRoundedRect(r, 3, 3)
        p.fillPath(track_path, self._track)
        if self._max > 0:
            ratio = max(0.0, min(1.0, self._value / self._max))
            fill_rect = QRectF(r.x(), r.y(), r.width() * ratio, r.height())
            fill_path = QPainterPath()
            fill_path.addRoundedRect(fill_rect, 3, 3)
            p.fillPath(fill_path, self._fill)
        p.setPen(QColor(236, 236, 236, 230))
        f = self.font()
        f.setPointSizeF(7.5)
        f.setBold(True)
        p.setFont(f)
        text = f"{self._fmt(self._value)} / {self._fmt(self._max)}{self._suffix}"
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    @staticmethod
    def _fmt(v: float) -> str:
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if abs(v) >= 1000:
            return f"{v / 1000:.1f}k"
        return str(int(v))


class _StatusChip(QLabel):
    def __init__(self, text: str, bg: QColor, parent: QWidget | None = None):
        super().__init__(text.upper(), parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()}); "
            "color: rgba(245,245,245,0.9); "
            "padding: 2px 6px; border-radius: 6px; "
            "font-size: 8pt; font-weight: 600; letter-spacing: 0.4px;"
        )


class _CombatantCard(QFrame):
    clicked = pyqtSignal(int)

    _SCHOOL_COLORS = {
        "Fire": "#e76b6b",
        "Ice": "#7aa9e0",
        "Storm": "#b86bd9",
        "Myth": "#d4b35a",
        "Life": "#80c47d",
        "Death": "#9d8ab5",
        "Balance": "#c89a64",
        "Star": "#d6c97d",
        "Sun": "#e07e4f",
        "Moon": "#b8b8d4",
        "Shadow": "#6b6b78",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("combatantCard")
        self.setStyleSheet(
            "QFrame#combatantCard { background: rgba(255,255,255,0.04); "
            "border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; } "
            "QFrame#combatantCard:hover { background: rgba(255,255,255,0.07); "
            "border: 1px solid rgba(255,255,255,0.14); } "
            "QFrame#combatantCard QLabel { background: transparent; }"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._owner_id = 0
        self._build()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._owner_id:
            self.clicked.emit(self._owner_id)
        super().mousePressEvent(event)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 7, 8, 7)
        root.setSpacing(4)

        # header: icon | name + meta
        top = QHBoxLayout()
        top.setSpacing(8)
        self._icon = QLabel()
        self._icon.setFixedSize(36, 36)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("background: rgba(0,0,0,0.25); border-radius: 5px;")
        top.addWidget(self._icon)
        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        self._name_lbl = QLabel("—")
        self._name_lbl.setStyleSheet("font-size: 10pt; font-weight: 600;")
        name_col.addWidget(self._name_lbl)
        self._meta_lbl = QLabel("")
        self._meta_lbl.setStyleSheet("color: rgba(236,236,236,0.55); font-size: 8pt;")
        self._meta_lbl.setTextFormat(Qt.TextFormat.RichText)
        name_col.addWidget(self._meta_lbl)
        top.addLayout(name_col, 1)
        root.addLayout(top)

        # bars (shorter - 11px vs the earlier 14)
        self._hp_bar = _LiveStatBar(QColor(220, 80, 80), height=11)
        self._mana_bar = _LiveStatBar(QColor(80, 140, 220), height=11)
        self._am_bar = _LiveStatBar(QColor(220, 180, 90), height=11)
        root.addWidget(self._hp_bar)
        root.addWidget(self._mana_bar)
        root.addWidget(self._am_bar)

        # pips - a horizontal strip of small pip pixmaps. we rebuild
        # the children of ``_pips_row`` each update; one suspended-state
        # text label trails the icons when relevant
        pips_host = QWidget()
        self._pips_row = QHBoxLayout(pips_host)
        self._pips_row.setContentsMargins(0, 0, 0, 0)
        self._pips_row.setSpacing(2)
        self._pips_row.addStretch(1)
        pips_host.setFixedHeight(18)
        self._pip_widgets: list[QWidget] = []
        root.addWidget(pips_host)

        # stats grid: DMG / RES / PIERCE / ACC
        stats_box = QFrame()
        stats_box.setStyleSheet(
            "QFrame { background: rgba(0,0,0,0.18); border-radius: 6px; }"
            "QLabel { background: transparent; }"
        )
        stats_grid = QGridLayout(stats_box)
        stats_grid.setContentsMargins(6, 4, 6, 4)
        stats_grid.setHorizontalSpacing(8)
        stats_grid.setVerticalSpacing(1)
        self._stat_value_lbls: dict[str, QLabel] = {}
        for col, key in enumerate(("DMG", "RES", "PIERCE", "ACC")):
            cap = QLabel(key)
            cap.setStyleSheet(
                "color: rgba(236,236,236,0.45); font-size: 7pt; "
                "font-weight: 700; letter-spacing: 0.8px;"
            )
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stats_grid.addWidget(cap, 0, col)
            val = QLabel("—")
            val.setStyleSheet("font-size: 9pt; font-weight: 600;")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stats_grid.addWidget(val, 1, col)
            self._stat_value_lbls[key] = val
        root.addWidget(stats_box)

        # chip row
        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.setSpacing(4)
        chip_row.addStretch(1)
        self._chip_row = chip_row
        self._chip_widgets: list[QWidget] = []
        root.addLayout(chip_row)

        # footer (effect counts)
        self._footer_lbl = QLabel("")
        self._footer_lbl.setStyleSheet(
            "color: rgba(236,236,236,0.4); font-size: 7.5pt; letter-spacing: 0.4px;"
        )
        self._footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._footer_lbl)

    _PIP_DISPLAY_ORDER = (
        "normal",
        "power",
        "fire",
        "ice",
        "storm",
        "myth",
        "life",
        "death",
        "balance",
        "shadow",
    )

    def update_from(
        self,
        data: dict,
        icon_cache,
        pip_pixmaps: dict[str, "QPixmap"] | None = None,
    ) -> None:
        self._owner_id = int(data.get("owner_id", 0) or 0)
        tid = int(data.get("template_id", 0) or 0)
        self._icon.setPixmap(icon_cache.get_or_fallback(tid, size=36))

        name = data.get("name") or "<unknown>"
        self._name_lbl.setText(name)
        school = data.get("school", "Unknown")
        lvl = data.get("level") or data.get("mob_level") or 0
        accent = self._SCHOOL_COLORS.get(school, "#9c9c9c")
        bits: list[str] = []
        if lvl:
            bits.append(f"Lv {lvl}")
        bits.append(f"<span style='color:{accent}'>{school}</span>")
        self._meta_lbl.setText(" · ".join(bits))

        self._hp_bar.set_values(data.get("health", 0), data.get("max_health", 0))
        max_mana = data.get("max_mana", 0) or 0
        if max_mana > 0:
            self._mana_bar.set_values(data.get("mana", 0), max_mana)
            self._mana_bar.show()
        else:
            self._mana_bar.hide()
        am_max = data.get("max_archmastery_points", 0.0) or 0.0
        if am_max > 0:
            self._am_bar.set_values(
                data.get("archmastery_points", 0.0), am_max, " ArchM"
            )
            self._am_bar.show()
        else:
            self._am_bar.hide()

        # rebuild the pip strip from the full breakdown
        for w in self._pip_widgets:
            self._pips_row.removeWidget(w)
            w.deleteLater()
        self._pip_widgets.clear()
        breakdown = data.get("pips_breakdown") or {}
        pip_pixmaps = pip_pixmaps or {}
        pip_size = 14
        total = 0
        for kind in self._PIP_DISPLAY_ORDER:
            count = int(breakdown.get(kind, 0) or 0)
            for _ in range(count):
                total += 1
                lbl = QLabel()
                lbl.setFixedSize(pip_size, pip_size)
                px = pip_pixmaps.get(kind)
                if px is not None:
                    lbl.setPixmap(
                        px.scaled(
                            pip_size,
                            pip_size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                else:
                    # fallback when the pip asset failed to ship - show
                    # the kind's first letter so the row is still readable
                    lbl.setText(kind[:1].upper())
                    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    lbl.setStyleSheet(
                        "color: rgba(236,236,236,0.7); font-size: 9pt; "
                        "font-weight: 700;"
                    )
                lbl.setToolTip(f"{kind.capitalize()} pip")
                # insert before the trailing stretch so pips stack left-to-right
                self._pips_row.insertWidget(self._pips_row.count() - 1, lbl)
                self._pip_widgets.append(lbl)

        if total == 0:
            empty = QLabel("—")
            empty.setStyleSheet("color: rgba(236,236,236,0.4); font-size: 10pt;")
            self._pips_row.insertWidget(self._pips_row.count() - 1, empty)
            self._pip_widgets.append(empty)

        if data.get("pips_suspended"):
            sus = QLabel("(suspended)")
            sus.setStyleSheet(
                "color: rgba(236,180,80,0.85); font-size: 8pt; "
                "font-style: italic; padding-left: 6px;"
            )
            self._pips_row.insertWidget(self._pips_row.count() - 1, sus)
            self._pip_widgets.append(sus)

        self._stat_value_lbls["DMG"].setText(self._pct(data.get("stat_damage")))
        self._stat_value_lbls["RES"].setText(self._pct(data.get("stat_resist")))
        self._stat_value_lbls["PIERCE"].setText(self._pct(data.get("stat_pierce")))
        self._stat_value_lbls["ACC"].setText(
            self._pct(data.get("accuracy_bonus"), additive=True)
        )

        # rebuild chips
        for w in self._chip_widgets:
            self._chip_row.removeWidget(w)
            w.deleteLater()
        self._chip_widgets.clear()
        chips: list[tuple[str, QColor]] = []
        if data.get("is_boss"):
            chips.append(("BOSS", QColor(220, 100, 80, 80)))
        if data.get("is_minion"):
            chips.append(("MINION", QColor(120, 120, 180, 70)))
        if data.get("is_player"):
            chips.append(("PLAYER", QColor(80, 160, 200, 80)))
        if data.get("is_dead"):
            chips.append(("DEAD", QColor(60, 60, 60, 110)))
        if data.get("stunned"):
            chips.append(("STUNNED", QColor(220, 200, 70, 80)))
        if data.get("mindcontrolled"):
            chips.append(("MIND-CTRL", QColor(180, 80, 200, 80)))
        if data.get("confused"):
            chips.append(("CONFUSED", QColor(200, 140, 60, 80)))
        if data.get("untargetable"):
            chips.append(("UNTGT", QColor(120, 120, 120, 80)))
        if data.get("vanish"):
            chips.append(("VANISH", QColor(100, 100, 130, 80)))
        if data.get("auto_pass"):
            chips.append(("AUTO-PASS", QColor(100, 130, 110, 80)))
        for text, color in chips:
            chip = _StatusChip(text, color)
            self._chip_row.insertWidget(self._chip_row.count() - 1, chip)
            self._chip_widgets.append(chip)

        hangs = int(data.get("hang_count", 0) or 0)
        auras = int(data.get("aura_count", 0) or 0)
        backlash = int(data.get("backlash", 0) or 0)
        footer_bits = [f"Hangs {hangs}", f"Auras {auras}"]
        if backlash:
            footer_bits.append(f"Backlash {backlash}")
        self._footer_lbl.setText("   ·   ".join(footer_bits))

    @staticmethod
    def _pct(v, *, additive: bool = False) -> str:
        if v is None:
            return "—"
        try:
            f = float(v)
        except Exception:
            return "—"
        if additive:
            return f"{f * 100:+.0f}%"
        return f"{f * 100:.0f}%"


class _FullStatsDialog(QDialog):
    _DETAIL_SCHOOLS = ("Fire", "Ice", "Storm", "Myth", "Life", "Death", "Balance")
    _STAT_ROWS = (
        ("damage", "Damage", "%"),
        ("resist", "Resist", "%"),
        ("pierce", "Pierce", "%"),
        ("accuracy", "Accuracy", "%"),
        ("crit", "Crit Rating", ""),
        ("block", "Block Rating", ""),
    )
    _SCHOOL_COLORS = _CombatantCard._SCHOOL_COLORS

    def __init__(
        self,
        owner_id: int,
        parent: QWidget | None = None,
        icon_cache=None,
        pip_pixmaps: dict | None = None,
        school_pixmaps: dict | None = None,
        bg_color: str = "#1a1a1d",
        text_color: str = "rgba(236,236,236,0.92)",
    ):
        super().__init__(parent)
        self.owner_id = owner_id
        self._icon_cache = icon_cache
        self._pip_pixmaps = pip_pixmaps or {}
        self._school_pixmaps = school_pixmaps or {}
        self.setWindowTitle("Combatant Stats")
        self.setModal(False)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.resize(560, 460)
        self.setStyleSheet(
            f"QDialog {{ background: {bg_color}; }}"
            f"QLabel {{ background: transparent; color: {text_color}; }}"
        )
        # closing the dialog should free its widgets - without this the
        # parent (the main window) keeps holding the QDialog object even
        # though we've popped it from ``open_dialogs``
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._build()

    # construction
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # header: icon | name + meta
        head = QHBoxLayout()
        head.setSpacing(12)
        self._icon = QLabel()
        self._icon.setFixedSize(64, 64)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("background: rgba(0,0,0,0.3); border-radius: 8px;")
        head.addWidget(self._icon)
        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        self._name_lbl = QLabel("—")
        self._name_lbl.setStyleSheet("font-size: 14pt; font-weight: 700;")
        name_col.addWidget(self._name_lbl)
        self._meta_lbl = QLabel("")
        self._meta_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._meta_lbl.setStyleSheet("color: rgba(236,236,236,0.65); font-size: 9pt;")
        name_col.addWidget(self._meta_lbl)
        head.addLayout(name_col, 1)
        root.addLayout(head)

        # bars
        self._hp_bar = _LiveStatBar(QColor(220, 80, 80), height=14)
        self._mana_bar = _LiveStatBar(QColor(80, 140, 220), height=14)
        self._am_bar = _LiveStatBar(QColor(220, 180, 90), height=14)
        root.addWidget(self._hp_bar)
        root.addWidget(self._mana_bar)
        root.addWidget(self._am_bar)

        # pip strip
        pips_host = QWidget()
        self._pips_row = QHBoxLayout(pips_host)
        self._pips_row.setContentsMargins(0, 4, 0, 4)
        self._pips_row.setSpacing(2)
        self._pips_row.addStretch(1)
        pips_host.setFixedHeight(22)
        self._pip_widgets: list[QWidget] = []
        root.addWidget(pips_host)

        # chips row
        chips_host = QWidget()
        self._chip_row = QHBoxLayout(chips_host)
        self._chip_row.setContentsMargins(0, 0, 0, 0)
        self._chip_row.setSpacing(4)
        self._chip_row.addStretch(1)
        self._chip_widgets: list[QWidget] = []
        root.addWidget(chips_host)

        # per-school table
        table_box = QFrame()
        table_box.setStyleSheet(
            "QFrame { background: rgba(0,0,0,0.18); border-radius: 6px; }"
            "QLabel { background: transparent; }"
        )
        grid = QGridLayout(table_box)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)

        # header row: blank corner + 7 school slot widgets. the actual
        # pixmap / fallback text is applied by ``_apply_school_headers``
        # so we can refresh them when assets arrive after build time
        corner = QLabel("")
        grid.addWidget(corner, 0, 0)
        self._school_value_lbls: dict[tuple[str, str], QLabel] = {}
        self._school_header_lbls: dict[str, QLabel] = {}
        for col, school in enumerate(self._DETAIL_SCHOOLS, start=1):
            hdr = QLabel()
            hdr.setFixedSize(22, 22)
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hdr.setToolTip(school)
            grid.addWidget(hdr, 0, col, alignment=Qt.AlignmentFlag.AlignCenter)
            self._school_header_lbls[school] = hdr
        self._apply_school_headers()

        # stat rows
        for row, (key, label, _suffix) in enumerate(self._STAT_ROWS, start=1):
            lbl = QLabel(label)
            lbl.setStyleSheet(
                "color: rgba(236,236,236,0.5); font-size: 8.5pt; "
                "font-weight: 700; letter-spacing: 0.6px;"
            )
            lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            grid.addWidget(lbl, row, 0)
            for col, school in enumerate(self._DETAIL_SCHOOLS, start=1):
                val = QLabel("—")
                val.setStyleSheet("font-size: 10pt; font-weight: 600;")
                val.setAlignment(Qt.AlignmentFlag.AlignCenter)
                grid.addWidget(val, row, col)
                self._school_value_lbls[(key, school)] = val

        root.addWidget(table_box)

        # footer with template / owner ids
        self._footer_lbl = QLabel("")
        self._footer_lbl.setStyleSheet(
            "color: rgba(236,236,236,0.4); font-size: 7.5pt;"
        )
        self._footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._footer_lbl)

        root.addStretch(1)

    def _apply_school_headers(self) -> None:
        for school, hdr in self._school_header_lbls.items():
            px = self._school_pixmaps.get(school)
            if px is not None:
                hdr.setPixmap(
                    px.scaled(
                        22,
                        22,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                hdr.setText("")
                hdr.setStyleSheet("")
            else:
                hdr.clear()
                hdr.setText(school[:1])
                color = self._SCHOOL_COLORS.get(school, "#9c9c9c")
                hdr.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 11pt;")

    # update
    def update_from(self, data: dict) -> None:
        # re-apply school headers in case new school icons arrived in
        # the snapshot envelope after this dialog was constructed
        self._apply_school_headers()

        # icon
        tid = int(data.get("template_id", 0) or 0)
        if self._icon_cache is not None:
            self._icon.setPixmap(self._icon_cache.get_or_fallback(tid, size=64))

        # name + meta
        name = data.get("name") or "<unknown>"
        self._name_lbl.setText(name)
        school = data.get("school", "Unknown")
        lvl = data.get("level") or data.get("mob_level") or 0
        accent = self._SCHOOL_COLORS.get(school, "#9c9c9c")
        bits = []
        if lvl:
            bits.append(f"Lv {lvl}")
        bits.append(f"<span style='color:{accent}'>{school}</span>")
        if data.get("is_boss"):
            bits.append("Boss")
        elif data.get("is_minion"):
            bits.append("Minion")
        elif data.get("is_player"):
            bits.append("Player")
        self._meta_lbl.setText("  ·  ".join(bits))

        # bars
        self._hp_bar.set_values(data.get("health", 0), data.get("max_health", 0))
        max_mana = data.get("max_mana", 0) or 0
        if max_mana > 0:
            self._mana_bar.set_values(data.get("mana", 0), max_mana)
            self._mana_bar.show()
        else:
            self._mana_bar.hide()
        am_max = data.get("max_archmastery_points", 0.0) or 0.0
        if am_max > 0:
            self._am_bar.set_values(
                data.get("archmastery_points", 0.0), am_max, " ArchM"
            )
            self._am_bar.show()
        else:
            self._am_bar.hide()

        # pip strip (reuse the card's rendering convention)
        for w in self._pip_widgets:
            self._pips_row.removeWidget(w)
            w.deleteLater()
        self._pip_widgets.clear()
        breakdown = data.get("pips_breakdown") or {}
        for kind in _CombatantCard._PIP_DISPLAY_ORDER:
            count = int(breakdown.get(kind, 0) or 0)
            for _ in range(count):
                lbl = QLabel()
                lbl.setFixedSize(18, 18)
                px = self._pip_pixmaps.get(kind)
                if px is not None:
                    lbl.setPixmap(
                        px.scaled(
                            18,
                            18,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                else:
                    lbl.setText(kind[:1].upper())
                    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setToolTip(f"{kind.capitalize()} pip")
                self._pips_row.insertWidget(self._pips_row.count() - 1, lbl)
                self._pip_widgets.append(lbl)

        # chips
        for w in self._chip_widgets:
            self._chip_row.removeWidget(w)
            w.deleteLater()
        self._chip_widgets.clear()
        for flag, label, color in (
            ("is_dead", "DEAD", QColor(60, 60, 60, 130)),
            ("stunned", "STUNNED", QColor(220, 200, 70, 80)),
            ("mindcontrolled", "MIND-CTRL", QColor(180, 80, 200, 80)),
            ("confused", "CONFUSED", QColor(200, 140, 60, 80)),
            ("untargetable", "UNTGT", QColor(120, 120, 120, 80)),
            ("vanish", "VANISH", QColor(100, 100, 130, 80)),
            ("auto_pass", "AUTO-PASS", QColor(100, 130, 110, 80)),
        ):
            if data.get(flag):
                chip = _StatusChip(label, color)
                self._chip_row.insertWidget(self._chip_row.count() - 1, chip)
                self._chip_widgets.append(chip)

        # per-school stat table
        school_stats = data.get("school_stats") or {}
        for stat_key, _label, suffix in self._STAT_ROWS:
            for school in self._DETAIL_SCHOOLS:
                cell = self._school_value_lbls[(stat_key, school)]
                v = (school_stats.get(school) or {}).get(stat_key)
                if v is None:
                    cell.setText("—")
                    continue
                try:
                    fv = float(v)
                except Exception:
                    cell.setText("—")
                    continue
                if suffix == "%":
                    cell.setText(f"{fv * 100:.0f}%")
                else:
                    # crit/block ratings are raw integers in W101
                    cell.setText(f"{int(fv)}")

        # footer
        self._footer_lbl.setText(
            f"Owner ID {data.get('owner_id', 0)}   ·   "
            f"Template {data.get('template_id', 0)}   ·   "
            f"Side {data.get('side') or '—'}"
        )


def build_stats_tab(ctx):

    from src.gui import editorial as ed
    from src.gui.mob_icons import IconCache

    tab = QWidget()
    stats_layout = ed.page_layout(tab)
    tl = ctx.tl
    send_queue = ctx.send_queue

    # header
    head_row = QHBoxLayout()
    head_row.setContentsMargins(0, 0, 0, 0)
    head_row.setSpacing(8)
    head_row.addWidget(ed.heading(tl("stats") if hasattr(ctx, "tl") else "Stats"))
    head_row.addStretch(1)
    head_row.addWidget(
        repo_icon_btn(
            ctx, ctx.svgs["readme"], tl("tooltip_wiki_stats"), f"{ctx.wiki_base}/Stats"
        )
    )
    stats_layout.addLayout(head_row)

    stats_layout.addSpacing(6)
    stats_layout.addWidget(
        ed.subtitle(
            "Live combat info, updated every second during a fight."
        )
    )
    stats_layout.addSpacing(18)

    # status banner + view toggle
    def _build_stats_seg_on():
        a = ed.accent_of(ctx)
        return (
            f"QPushButton {{ background: {a}; color: #fff; border: none; "
            f"padding: 4px 14px; font-weight: 600; font-size: 8pt; "
            f"letter-spacing: 1px; }} "
            f"QPushButton:hover {{ background: {a}; }}"
        )

    _seg_on = _build_stats_seg_on()
    _seg_off = (
        "QPushButton { background: transparent; color: rgba(236,236,236,0.45); "
        "border: none; padding: 4px 14px; font-size: 8pt; letter-spacing: 1px; } "
        "QPushButton:hover { color: rgba(236,236,236,0.85); }"
    )
    seg_bar = QWidget()
    seg_bar.setFixedHeight(28)
    seg_bar.setStyleSheet(
        "QWidget { background: rgba(255,255,255,0.04); border-radius: 6px; }"
    )
    seg_bar_layout = QHBoxLayout(seg_bar)
    seg_bar_layout.setContentsMargins(2, 2, 2, 2)
    seg_bar_layout.setSpacing(0)
    cards_seg = StrokedButton("CARDS")
    cards_seg.setCursor(Qt.CursorShape.PointingHandCursor)
    cards_seg.setStyleSheet(_seg_on)
    ring_seg = StrokedButton("DUEL RING")
    ring_seg.setCursor(Qt.CursorShape.PointingHandCursor)
    ring_seg.setStyleSheet(_seg_off)
    seg_bar_layout.addWidget(cards_seg)
    seg_bar_layout.addWidget(ring_seg)

    status_lbl = QLabel("NOT IN COMBAT")
    status_lbl.setStyleSheet(
        "color: rgba(236,236,236,0.55); font-size: 9pt; font-weight: 700; "
        "letter-spacing: 1.2px;"
    )
    status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

    status_row = QHBoxLayout()
    status_row.setContentsMargins(0, 0, 0, 0)
    status_row.addStretch(1)
    status_row.addWidget(status_lbl)
    status_row.addStretch(1)
    status_row.addWidget(seg_bar)
    stats_layout.addLayout(status_row)
    stats_layout.addSpacing(14)

    # Stacked views: Cards | Duel Ring
    view_stack = AnimatedStackedWidget()
    stats_layout.addWidget(view_stack, 1)

    # page 0: cards grid (scrollable)
    cards_page = QWidget()
    cards_page_layout = QVBoxLayout(cards_page)
    cards_page_layout.setContentsMargins(0, 0, 0, 0)
    cards_page_layout.setSpacing(0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    grid_host = QWidget()
    grid_layout = QHBoxLayout(grid_host)
    grid_layout.setContentsMargins(0, 0, 0, 0)
    grid_layout.setSpacing(16)

    def _make_column(title: str) -> tuple[QVBoxLayout, QLabel]:
        wrap = QVBoxLayout()
        wrap.setSpacing(8)
        wrap.addLayout(ed.section_eyebrow_row(title))
        wrap.addSpacing(8)
        placeholder = QLabel("Nothing here.")
        placeholder.setStyleSheet(
            "color: rgba(236,236,236,0.35); font-size: 9pt; font-style: italic; "
            "padding: 14px;"
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap.addWidget(placeholder)
        wrap.addStretch(1)
        return wrap, placeholder

    enemies_col, enemies_empty = _make_column("Enemies")
    allies_col, allies_empty = _make_column("Allies")
    grid_layout.addLayout(enemies_col, 1)
    grid_layout.addLayout(allies_col, 1)
    scroll.setWidget(grid_host)
    cards_page_layout.addWidget(scroll)
    view_stack.addWidget(cards_page)

    # page 1: duel ring
    ring_page = QWidget()
    ring_page_layout = QHBoxLayout(ring_page)
    ring_page_layout.setContentsMargins(0, 0, 0, 0)
    ring_page_layout.addStretch(1)
    duel_circle = DuelCircleWidget(
        stroke_color=ctx.stroke_color,
        text_color=ctx.text_color,
        bg_color=ctx.bg_color,
        button_color=ctx.btn_color_hex,
        tl=tl,
    )
    duel_circle.set_status_message(
        tl("not_in_combat") if hasattr(ctx, "tl") else "Not in combat"
    )
    duel_circle.set_enemy_count(0)
    duel_circle.set_ally_count(0)
    ring_page_layout.addWidget(duel_circle)
    ring_page_layout.addStretch(1)
    view_stack.addWidget(ring_page)

    def _show_cards():
        cards_seg.setStyleSheet(_seg_on)
        ring_seg.setStyleSheet(_seg_off)
        view_stack.slide_to(0)

    def _show_ring():
        cards_seg.setStyleSheet(_seg_off)
        ring_seg.setStyleSheet(_seg_on)
        view_stack.slide_to(1)

    cards_seg.clicked.connect(_show_cards)
    ring_seg.clicked.connect(_show_ring)

    # map duel-ring slot clicks to full-stats dialogs. casterSelected
    # fires for ally slots, targetSelected for enemy slots. viewAlly /
    # viewEnemy fire when the user clicks the side-name "eye" - same
    # action, but on the currently selected slot
    def _open_ally_slot(idx: int) -> None:
        i = idx - 1
        if 0 <= i < len(ally_slot_owners):
            _open_full_stats(ally_slot_owners[i])

    def _open_enemy_slot(idx: int) -> None:
        i = idx - 1
        if 0 <= i < len(enemy_slot_owners):
            _open_full_stats(enemy_slot_owners[i])

    duel_circle.casterSelected.connect(_open_ally_slot)
    duel_circle.targetSelected.connect(_open_enemy_slot)
    duel_circle.viewAlly.connect(lambda: _open_ally_slot(duel_circle.selected_caster()))
    duel_circle.viewEnemy.connect(
        lambda: _open_enemy_slot(duel_circle.selected_target())
    )

    # state
    icon_cache = IconCache(fallback_size=36)
    cards_by_owner: dict[int, _CombatantCard] = {}
    # pip pixmaps, keyed by pip kind ("power"/"fire"/...). populated from
    # the first snapshot's ``pip_assets`` payload and reused thereafter
    pip_pixmaps: dict[str, "QPixmap"] = {}
    # School pixmaps, keyed by school name ("Fire"/...). populated from
    # the first snapshot's ``school_assets`` payload
    school_pixmaps: dict[str, "QPixmap"] = {}
    # latest snapshot row per owner_id - used to (re)populate full-stats
    # dialogs as new snapshots arrive
    latest_by_owner: dict[int, dict] = {}
    # open full-stats dialogs keyed by owner_id. we auto-refresh them
    # from each snapshot and drop them when the user closes the window
    open_dialogs: dict[int, _FullStatsDialog] = {}
    # 1-based slot → owner_id mappings for the duel ring. re-derived on
    # every snapshot from the same ally/enemy grouping the cards use
    ally_slot_owners: list[int] = []
    enemy_slot_owners: list[int] = []

    def _open_full_stats(oid: int) -> None:
        data = latest_by_owner.get(oid)
        if data is None:
            return
        dlg = open_dialogs.get(oid)
        if dlg is None:
            _theme = ctx.settings.get_theme() if ctx.settings else {}
            dlg = _FullStatsDialog(
                owner_id=oid,
                parent=ctx.window if hasattr(ctx, "window") else tab,
                icon_cache=icon_cache,
                pip_pixmaps=pip_pixmaps,
                school_pixmaps=school_pixmaps,
                bg_color=_theme.get("bg_color", "#1a1a1d"),
                text_color=_theme.get("text_color", "#ececec"),
            )
            open_dialogs[oid] = dlg
            dlg.finished.connect(lambda _r, o=oid: open_dialogs.pop(o, None))
        dlg.update_from(data)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _remove_card(card: _CombatantCard) -> None:
        # card lives in exactly one of the two columns - find which
        for col in (enemies_col, allies_col):
            idx = col.indexOf(card)
            if idx != -1:
                col.takeAt(idx)
                break
        card.setParent(None)
        card.deleteLater()

    def _ingest_snapshot(snap: dict) -> None:
        if not isinstance(snap, dict):
            return

        # status banner
        if snap.get("in_combat"):
            title = snap.get("client_title") or "current client"
            status_lbl.setText(f"IN COMBAT  ·  {title.upper()}")
        else:
            status_lbl.setText("NOT IN COMBAT")

        combatants = snap.get("combatants") or []

        # 1. decode any new icon bytes shipped in this snapshot. the bot
        #    ships bytes only the first time a given template id appears,
        #    so this loop is usually a no-op
        for c in combatants:
            tid = int(c.get("template_id", 0) or 0)
            ib = c.get("icon_bytes")
            if ib and tid and not icon_cache.has(tid):
                icon_cache.ingest(tid, ib)

        # 1b. pip + school icons ship once per session in the envelope;
        #     decode and cache them. after this, the bot omits the fields.
        def _decode_assets_into(target: dict, source: dict | None) -> None:
            if not source:
                return
            from PIL import Image
            import io

            for key, raw in source.items():
                if key in target:
                    continue
                try:
                    img = Image.open(io.BytesIO(raw))
                    if img.mode != "RGBA":
                        img = img.convert("RGBA")
                    qimg = QImage(
                        img.tobytes("raw", "RGBA"),
                        img.width,
                        img.height,
                        QImage.Format.Format_RGBA8888,
                    )
                    target[key] = QPixmap.fromImage(qimg.copy())
                except Exception:
                    logger.debug(f"[stats] decode failed for {key!r}")

        _decode_assets_into(pip_pixmaps, snap.get("pip_assets"))
        _decode_assets_into(school_pixmaps, snap.get("school_assets"))

        # 2. diff existing cards against the new snapshot, keyed by owner_id.
        wanted: dict[int, dict] = {}
        for c in combatants:
            oid = int(c.get("owner_id", 0) or 0)
            if oid:
                wanted[oid] = c
        for oid in list(cards_by_owner):
            if oid not in wanted:
                _remove_card(cards_by_owner.pop(oid))

        # 3. update existing / insert new cards.
        for oid, data in wanted.items():
            card = cards_by_owner.get(oid)
            if card is None:
                card = _CombatantCard()
                card.clicked.connect(_open_full_stats)
                cards_by_owner[oid] = card
                target = allies_col if data.get("is_player") else enemies_col
                # stretch is last item; insert just before it so cards
                # stack from the top
                target.insertWidget(target.count() - 1, card)
            card.update_from(data, icon_cache, pip_pixmaps)

        # latest data for each combatant, so open dialogs can refresh
        latest_by_owner.clear()
        latest_by_owner.update(wanted)
        for oid, dlg in list(open_dialogs.items()):
            d = wanted.get(oid)
            if d is not None:
                dlg.update_from(d)

        # duel-ring view
        # build ordered slot → owner_id lists for the ring; preserve the
        # game's slot_subcircle ordering when present so the ring layout
        # roughly matches the in-game positions
        def _ring_sort_key(d: dict) -> tuple:
            return (int(d.get("slot_subcircle", 0) or 0), d.get("name", ""))

        ally_rows = sorted(
            (d for d in wanted.values() if d.get("is_player")),
            key=_ring_sort_key,
        )
        enemy_rows = sorted(
            (d for d in wanted.values() if not d.get("is_player")),
            key=_ring_sort_key,
        )
        ally_slot_owners[:] = [int(d.get("owner_id", 0) or 0) for d in ally_rows]
        enemy_slot_owners[:] = [int(d.get("owner_id", 0) or 0) for d in enemy_rows]

        duel_circle.set_ally_count(len(ally_rows))
        duel_circle.set_enemy_count(len(enemy_rows))
        slot_info: dict[tuple[str, int], dict] = {}
        for i, d in enumerate(ally_rows, start=1):
            slot_info[("ally", i)] = {
                "is_friendly": True,
                "is_dead": bool(d.get("is_dead")),
                "is_stunned": bool(d.get("stunned")),
            }
        for i, d in enumerate(enemy_rows, start=1):
            slot_info[("enemy", i)] = {
                "is_friendly": False,
                "is_dead": bool(d.get("is_dead")),
                "is_stunned": bool(d.get("stunned")),
            }
        duel_circle.set_slot_info(slot_info)
        if ally_rows:
            duel_circle.set_ally_name(ally_rows[0].get("name", "—"))
        if enemy_rows:
            duel_circle.set_enemy_name(enemy_rows[0].get("name", "—"))
        if snap.get("in_combat"):
            duel_circle.set_status_message(snap.get("client_title", "") or "In combat")
        else:
            duel_circle.set_status_message(
                tl("not_in_combat") if hasattr(ctx, "tl") else "Not in combat"
            )

        # 4. placeholder visibility.
        any_enemy = any(not d.get("is_player") for d in wanted.values())
        any_ally = any(d.get("is_player") for d in wanted.values())
        enemies_empty.setVisible(not any_enemy)
        allies_empty.setVisible(not any_ally)

    # polling timer
    refresh_timer = QTimer(tab)
    refresh_timer.setInterval(1000)

    def _request_refresh():
        # don't burn the queue when this tab isn't on-screen - the bot's
        # tick is finite and someone else might want it
        if hasattr(ctx, "tabs") and ctx.tabs.currentWidget() != tab:
            return
        try:
            send_queue.put(GUICommand(GUICommandType.LiveCombatRefresh, None))
        except Exception:
            logger.error("Failed to request live combat refresh", exc_info=True)

    refresh_timer.timeout.connect(_request_refresh)
    refresh_timer.start()
    # fire once on first paint so the panel populates immediately when
    # the tab is opened after combat has already started
    QTimer.singleShot(0, _request_refresh)

    stats_layout.addSpacing(8)
    stats_layout.addWidget(ed.hairline())
    stats_layout.addSpacing(8)
    stats_layout.addWidget(ed.meta("AUTO-REFRESH   ·   EVERY 1 S"))

    # expose the duel circle for the global theme refresh hook
    ctx.duel_circle = duel_circle

    # exports
    def _retheme():
        nonlocal _seg_on
        _seg_on = _build_stats_seg_on()
        if cards_seg.styleSheet() != _seg_off:
            cards_seg.setStyleSheet(_seg_on)
        if ring_seg.styleSheet() != _seg_off:
            ring_seg.setStyleSheet(_seg_on)

    ctx.exports["stats"] = {
        "ingest_snapshot": _ingest_snapshot,
        "icon_cache": icon_cache,
        "duel_circle": duel_circle,
        "retheme": _retheme,
    }

    return tab


# settings tab
