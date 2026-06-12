from time import time

from PyQt6.QtCore import Qt, QTimer

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.gui.commands import GUICommand, GUICommandType, GUIKeys
from src.gui.editorial import StrokedButton

_SCHOOLS = ["Any", "Fire", "Ice", "Storm", "Myth", "Life", "Death", "Balance"]

_SCROLL_STYLE = (
    "QScrollArea { background: transparent; border: none; }"
    "QScrollBar:vertical { width: 4px; background: transparent; }"
    "QScrollBar::handle:vertical { background: rgba(255,255,255,0.15);"
    " border-radius: 2px; min-height: 20px; }"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
)


def _input_style(accent: str) -> str:
    # mirrors the settings tab's control styling: no font-size / min-height
    # override, so dropdowns and spin boxes match the rest of the app
    return (
        "QComboBox, QSpinBox, QDoubleSpinBox {"
        " background-color: rgba(255,255,255,0.05); color: rgba(236,236,236,0.9);"
        " border: 1px solid rgba(255,255,255,0.08); border-radius: 7px;"
        " padding: 4px 8px; }"
        "QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {"
        " border: 1px solid rgba(255,255,255,0.18); }"
        "QComboBox::drop-down { border: none; width: 18px; }"
        "QComboBox QAbstractItemView {"
        " background: #1f1f23; color: rgba(236,236,236,0.92);"
        f" selection-background-color: {accent}; outline: none; }}"
        "QCheckBox { color: rgba(236,236,236,0.80); spacing: 7px; background: transparent; }"
        "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px;"
        " border: 1px solid rgba(255,255,255,0.18); background: rgba(255,255,255,0.05); }"
        f"QCheckBox::indicator:checked {{ background: {accent}; border: 1px solid {accent}; }}"
    )


def build_fishing_tab(ctx):
    from src.gui import editorial as ed

    tab = QWidget()
    outer = ed.page_layout(tab)
    send_queue = ctx.send_queue
    accent = ed.accent_of(ctx)
    tl = getattr(ctx, "tl", lambda k: k)

    # ── header (stays pinned above the scroll) ──────────────────
    head_row = QHBoxLayout()
    head_row.setContentsMargins(0, 0, 0, 0)
    head_row.addWidget(ed.heading(tl("fishing") if hasattr(ctx, "tl") else "Fishing"))
    head_row.addStretch(1)
    outer.addLayout(head_row)
    outer.addSpacing(6)
    outer.addWidget(
        ed.subtitle(
            "Fishes for you on the main client."
        )
    )
    outer.addSpacing(18)

    # ── scroll body (everything else lives here so nothing squishes) ──
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(_SCROLL_STYLE)
    body_w = QWidget()
    body_w.setStyleSheet("background: transparent;")
    body = QVBoxLayout(body_w)
    body.setContentsMargins(0, 0, 12, 0)
    body.setSpacing(0)
    scroll.setWidget(body_w)
    outer.addWidget(scroll, 1)

    # ── config card ─────────────────────────────────────────────
    cfg_card = ed.RoundedCard(getattr(ctx, "bg_color", "#1a1a1d"))
    cfg_card.setStyleSheet(_input_style(accent))
    cfg_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    cfg_grid = QGridLayout(cfg_card)
    cfg_grid.setContentsMargins(16, 14, 16, 14)
    cfg_grid.setHorizontalSpacing(14)
    cfg_grid.setVerticalSpacing(12)

    def _cap(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: rgba(236,236,236,0.5); font-size: 8pt; font-weight: 700;"
            " letter-spacing: 0.6px; background: transparent;"
        )
        return lbl

    chest_cb = QCheckBox("Target chests only")
    school_combo = QComboBox()
    school_combo.addItems(_SCHOOLS)
    rank_spin = QSpinBox()
    rank_spin.setRange(0, 20)
    rank_spin.setSpecialValueText("Any")
    size_min_spin = QDoubleSpinBox()
    size_min_spin.setRange(0.0, 999.0)
    size_min_spin.setDecimals(1)
    size_max_spin = QDoubleSpinBox()
    size_max_spin.setRange(0.0, 999.0)
    size_max_spin.setDecimals(1)
    size_max_spin.setValue(999.0)

    # two columns of labelled controls: chest/school up top, then the numeric filters
    cfg_grid.addWidget(chest_cb, 0, 0, 1, 2)
    cfg_grid.addWidget(_cap("SCHOOL"), 0, 2)
    cfg_grid.addWidget(school_combo, 0, 3)

    cfg_grid.addWidget(_cap("RANK"), 1, 0)
    cfg_grid.addWidget(rank_spin, 1, 1)
    cfg_grid.addWidget(_cap("SIZE MIN"), 1, 2)
    cfg_grid.addWidget(size_min_spin, 1, 3)

    cfg_grid.addWidget(_cap("SIZE MAX"), 2, 2)
    cfg_grid.addWidget(size_max_spin, 2, 3)
    cfg_grid.setColumnStretch(1, 1)
    cfg_grid.setColumnStretch(3, 1)

    body.addWidget(cfg_card)
    body.addSpacing(14)

    def _current_config() -> dict:
        return {
            "chest": chest_cb.isChecked(),
            "school": school_combo.currentText(),
            "rank": rank_spin.value(),
            "template_id": 0,
            "size_min": size_min_spin.value(),
            "size_max": size_max_spin.value(),
            "amount": 0,
        }

    def _send_config():
        send_queue.put(GUICommand(GUICommandType.SetFishConfig, _current_config()))

    chest_cb.toggled.connect(lambda _checked: _send_config())
    school_combo.currentTextChanged.connect(lambda _t: _send_config())
    for sp in (rank_spin, size_min_spin, size_max_spin):
        sp.valueChanged.connect(lambda _v: _send_config())

    # ── start / stop ────────────────────────────────────────────
    running = [False]
    start_epoch = [0.0]

    start_btn = StrokedButton("Start Fishing")
    start_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _btn_style(active: bool) -> str:
        # mirrors ctx.btn_style (padding/radius/weight, app default font size),
        # swapping the fill to a stop-red while a session is live
        bg = "#c0563f" if active else accent
        return (
            f"QPushButton {{ background-color: {bg}; color: #ffffff; border: none;"
            " padding: 6px 14px; border-radius: 8px; font-weight: 600; }"
            f"QPushButton:hover {{ background-color: {bg}; }}"
        )

    start_btn.setStyleSheet(_btn_style(False))

    def _on_start_clicked():
        _send_config()
        send_queue.put(
            GUICommand(GUICommandType.ToggleOption, (GUIKeys.toggle_fishing, "All"))
        )

    start_btn.clicked.connect(_on_start_clicked)
    body.addWidget(start_btn)
    body.addSpacing(20)

    # ── session stats ───────────────────────────────────────────
    body.addLayout(ed.section_eyebrow_row("Session"))
    body.addSpacing(12)

    caught_lbl = ed.stat_value("0", size_pt=30)
    caught_cap = QLabel("FISH CAUGHT")
    caught_cap.setStyleSheet(
        "color: rgba(236,236,236,0.45); font-size: 8pt; font-weight: 700;"
        " letter-spacing: 1px;"
    )
    caught_col = QVBoxLayout()
    caught_col.setSpacing(0)
    caught_col.addWidget(caught_lbl)
    caught_col.addWidget(caught_cap)

    metrics = {}

    def _metric(key: str, cap: str):
        box = QVBoxLayout()
        box.setSpacing(2)
        val = ed.stat_value("—", size_pt=13)
        c = QLabel(cap)
        c.setStyleSheet(
            "color: rgba(236,236,236,0.4); font-size: 7.5pt; font-weight: 700;"
            " letter-spacing: 0.8px;"
        )
        box.addWidget(val)
        box.addWidget(c)
        metrics[key] = val
        return box

    metrics_grid = QGridLayout()
    metrics_grid.setHorizontalSpacing(26)
    metrics_grid.setVerticalSpacing(12)
    metrics_grid.addLayout(_metric("elapsed", "RUNTIME"), 0, 0)
    metrics_grid.addLayout(_metric("sec_per_fish", "SEC / FISH"), 0, 1)
    metrics_grid.addLayout(_metric("pool_size", "POOL"), 0, 2)
    metrics_grid.addLayout(_metric("baskets_sold", "BASKETS"), 1, 0)
    metrics_grid.addLayout(_metric("energy_spent", "ENERGY"), 1, 1)

    top_row = QHBoxLayout()
    top_row.addLayout(caught_col)
    top_row.addStretch(1)
    top_row.addLayout(metrics_grid)
    body.addLayout(top_row)

    body.addSpacing(20)
    body.addLayout(ed.section_eyebrow_row("Recent catches"))
    body.addSpacing(10)

    recent_host = QWidget()
    recent_host.setStyleSheet("background: transparent;")
    recent_col = QVBoxLayout(recent_host)
    recent_col.setContentsMargins(0, 0, 0, 0)
    recent_col.setSpacing(4)
    recent_empty = QLabel("No catches yet.")
    recent_empty.setStyleSheet(
        "color: rgba(236,236,236,0.35); font-size: 9pt; font-style: italic; padding: 8px;"
    )
    recent_col.addWidget(recent_empty)
    recent_col.addStretch(1)
    body.addWidget(recent_host)
    body.addStretch(1)

    _school_colors = {
        "Fire": "#e76b6b", "Ice": "#7aa9e0", "Storm": "#b86bd9", "Myth": "#d4b35a",
        "Life": "#80c47d", "Death": "#9d8ab5", "Balance": "#c89a64",
    }

    recent_chips = []

    def _set_recent(rows):
        for w in recent_chips:
            recent_col.removeWidget(w)
            w.deleteLater()
        recent_chips.clear()
        if not rows:
            recent_empty.show()
            return
        recent_empty.hide()
        for r in rows:
            chip = QFrame()
            chip.setStyleSheet(
                "QFrame { background: rgba(255,255,255,0.04); border-radius: 6px; }"
                "QLabel { background: transparent; }"
            )
            row = QHBoxLayout(chip)
            row.setContentsMargins(10, 5, 10, 5)
            school = r.get("school", "?")
            color = _school_colors.get(school, "#9c9c9c")
            tag = "Chest" if r.get("chest") else "Fish"
            name = QLabel(f"<span style='color:{color}'>{school}</span>  ·  {tag}")
            name.setTextFormat(Qt.TextFormat.RichText)
            name.setStyleSheet("font-size: 9pt; font-weight: 600;")
            size = QLabel(f"size {r.get('size', 0)}")
            size.setStyleSheet("color: rgba(236,236,236,0.5); font-size: 8.5pt;")
            row.addWidget(name)
            row.addStretch(1)
            row.addWidget(size)
            recent_col.insertWidget(recent_col.count() - 1, chip)
            recent_chips.append(chip)

    # ── live updates ────────────────────────────────────────────
    def _fmt_time(secs: float) -> str:
        secs = int(secs)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _apply_running(is_on: bool):
        running[0] = is_on
        start_btn.setText("Stop Fishing" if is_on else "Start Fishing")
        start_btn.setStyleSheet(_btn_style(is_on))

    def _ingest(stats: dict):
        if not isinstance(stats, dict):
            return
        is_on = bool(stats.get("running"))
        if is_on and not running[0]:
            start_epoch[0] = time() - float(stats.get("elapsed", 0.0) or 0.0)
        _apply_running(is_on)
        caught_lbl.setText(str(stats.get("fish_caught", 0)))
        metrics["elapsed"].setText(_fmt_time(stats.get("elapsed", 0.0) or 0.0))
        spf = stats.get("sec_per_fish", 0.0) or 0.0
        metrics["sec_per_fish"].setText(f"{spf:.1f}s" if spf else "—")
        metrics["pool_size"].setText(str(stats.get("pool_size", 0)))
        metrics["baskets_sold"].setText(str(stats.get("baskets_sold", 0)))
        metrics["energy_spent"].setText(str(stats.get("energy_spent", 0)))
        _set_recent(stats.get("recent") or [])

    runtime_timer = QTimer(tab)
    runtime_timer.setInterval(1000)

    def _tick():
        if running[0] and start_epoch[0]:
            metrics["elapsed"].setText(_fmt_time(time() - start_epoch[0]))

    runtime_timer.timeout.connect(_tick)
    runtime_timer.start()

    ctx.exports["fishing"] = {"ingest": _ingest}

    return tab
