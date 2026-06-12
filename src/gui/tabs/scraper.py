from loguru import logger

from PyQt6.QtCore import QSize, Qt


from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


from src.gui.editorial import StrokedButton
from src.gui.commands import GUICommand, GUICommandType


def build_scraper_tab(ctx) -> QWidget:
    from src.gui import editorial as ed

    tab = QWidget()
    outer = ed.page_layout(tab)

    outer.addWidget(ed.heading("Scraper"))
    outer.addSpacing(4)
    outer.addWidget(
        ed.subtitle(
            "Pulls zone data from memory. Output shows in the console."
        )
    )
    outer.addSpacing(20)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet(
        "QScrollArea { background: transparent; border: none; }"
        "QScrollBar:vertical { width: 4px; background: transparent; }"
        "QScrollBar::handle:vertical { background: rgba(255,255,255,0.15);"
        " border-radius: 2px; min-height: 20px; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
    )
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 12, 10)
    body_layout.setSpacing(0)
    scroll.setWidget(body)
    outer.addWidget(scroll, 1)
    lay = body_layout

    _primary_btns: list = []

    def _build_btn_style():
        a = ed.accent_of(ctx)
        h = a.lstrip("#") if isinstance(a, str) else "ff557f"
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (
            f"QPushButton {{"
            f"  background-color: rgb({r},{g},{b});"
            f"  color: #ffffff;"
            f"  border: none;"
            f"  border-radius: 8px;"
            f"  padding: 8px 16px;"
            f"  font-weight: 600;"
            f"  text-align: left;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: rgb({min(r + 20, 255)},{min(g + 20, 255)},{min(b + 20, 255)});"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background-color: rgb({max(r - 15, 0)},{max(g - 15, 0)},{max(b - 15, 0)});"
            f"}}"
            f"QPushButton:disabled {{"
            f"  background-color: rgba({r},{g},{b},0.35);"
            f"  color: rgba(255,255,255,0.4);"
            f"}}"
        )

    btn_style = _build_btn_style()
    ghost_style = (
        "QPushButton {"
        "  background: rgba(255,255,255,0.04);"
        "  color: rgba(236,236,236,0.60);"
        "  border: 1px solid rgba(255,255,255,0.08);"
        "  border-radius: 6px;"
        "  padding: 6px 12px;"
        "  font-size: 9pt;"
        "  text-align: left;"
        "}"
        "QPushButton:hover {"
        "  background: rgba(255,255,255,0.07);"
        "  color: rgba(236,236,236,0.85);"
        "}"
        "QPushButton:pressed { background: rgba(255,255,255,0.10); }"
    )

    def _section(title: str, description: str):
        lay.addSpacing(18)
        lay.addLayout(ed.section_eyebrow_row(title))
        lay.addSpacing(5)
        lay.addWidget(ed.meta(description))
        lay.addSpacing(10)

    def _primary(label: str, on_click, checkable: bool = False) -> QPushButton:
        btn = StrokedButton(label)
        btn.setStyleSheet(btn_style)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if checkable:
            btn.setCheckable(True)
        btn.clicked.connect(on_click)
        lay.addWidget(btn)
        lay.addSpacing(6)
        _primary_btns.append(btn)
        return btn

    from src.gui.icons import build_icons as _build_icons

    _REC_GREEN = ctx.titlebar_svg_icon(_build_icons("#4ade80")["record"], 14)
    _REC_RED = ctx.titlebar_svg_icon(_build_icons("#f87171")["record"], 14)

    # SCAN
    _section(
        "SCAN",
        "Snapshot the current zone — player position, health, and trigger volumes.",
    )

    def _on_scan():
        ctx.send_queue.put(GUICommand(GUICommandType.ScanGame))
        logger.info("scraper: scan_game command queued")

    _primary("Scan game", _on_scan)

    # RECORD
    _section(
        "RECORD", "Discover and write gate data for the current zone to zones.txt."
    )

    def _on_process():
        ctx.send_queue.put(GUICommand(GUICommandType.ProcessCurrentZone))
        logger.info("scraper: process_current_zone command queued")

    _primary("Scan this zone", _on_process)

    record_btn = StrokedButton("Start gate recording")
    record_btn.setStyleSheet(btn_style)
    _primary_btns.append(record_btn)
    record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    record_btn.setCheckable(True)
    record_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    _rec_icon_label = QLabel()
    _rec_icon_label.setPixmap(_REC_RED.pixmap(14, 14))
    _rec_icon_label.setFixedSize(14, 14)

    _record_row = QHBoxLayout()
    _record_row.setContentsMargins(0, 0, 0, 0)
    _record_row.setSpacing(8)
    _record_row.addWidget(record_btn)
    _record_row.addWidget(_rec_icon_label)
    _record_row.addStretch()
    lay.addLayout(_record_row)
    lay.addSpacing(6)

    def _on_record(checked: bool):
        ctx.send_queue.put(GUICommand(GUICommandType.ToggleGateRecorder, checked))
        record_btn.setText("Stop gate recording" if checked else "Start gate recording")
        _rec_icon_label.setPixmap((_REC_GREEN if checked else _REC_RED).pixmap(14, 14))

    record_btn.clicked.connect(_on_record)

    # MAINTENANCE
    _section(
        "MAINTENANCE",
        "Apply walk-through calibration and audit zones.txt for structural issues.",
    )

    maint_row = QHBoxLayout()
    maint_row.setContentsMargins(0, 0, 0, 0)
    maint_row.setSpacing(8)

    fix_btn = StrokedButton("Apply calibration fixes")
    fix_btn.setStyleSheet(btn_style)
    _primary_btns.append(fix_btn)
    fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _on_fix():
        ctx.send_queue.put(GUICommand(GUICommandType.ApplyCalibrationFixes))
        logger.info("scraper: apply_calibration_fixes command queued")

    fix_btn.clicked.connect(_on_fix)
    maint_row.addWidget(fix_btn)

    sweep_btn = StrokedButton("Audit zones.txt")
    sweep_btn.setStyleSheet(btn_style)
    _primary_btns.append(sweep_btn)
    sweep_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _on_sweep():
        ctx.send_queue.put(GUICommand(GUICommandType.SanitySweepZones))
        logger.info("scraper: sanity_sweep_zones command queued")

    sweep_btn.clicked.connect(_on_sweep)
    maint_row.addWidget(sweep_btn)

    lay.addLayout(maint_row)

    # DEBUG
    lay.addSpacing(24)
    lay.addLayout(ed.section_eyebrow_row("DEBUG"))
    lay.addSpacing(8)

    debug_toggle = StrokedButton("Show debug tools")
    debug_toggle.setStyleSheet(ghost_style)
    debug_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
    debug_toggle.setCheckable(True)
    debug_toggle.setIcon(ctx.titlebar_svg_icon(ctx.svgs["caret_right"], 14))
    debug_toggle.setIconSize(QSize(14, 14))
    lay.addWidget(debug_toggle)
    lay.addSpacing(6)

    debug_widget = QWidget()
    debug_layout = QVBoxLayout(debug_widget)
    debug_layout.setContentsMargins(0, 0, 0, 0)
    debug_layout.setSpacing(6)
    debug_widget.setVisible(False)
    lay.addWidget(debug_widget)

    def _on_debug_toggle(checked: bool):
        debug_toggle.setText("Hide debug tools" if checked else "Show debug tools")
        debug_toggle.setIcon(
            ctx.titlebar_svg_icon(
                ctx.svgs["caret_down"] if checked else ctx.svgs["caret_right"], 14
            )
        )
        debug_widget.setVisible(checked)

    debug_toggle.clicked.connect(_on_debug_toggle)

    for label, cmd, log_msg in [
        (
            "Enumerate zone gates",
            GUICommandType.EnumerateZoneGates,
            "scraper: enumerate_zone_gates command queued",
        ),
        (
            "Enumerate interactive teleporters",
            GUICommandType.EnumerateInteractiveTeleporters,
            "scraper: enumerate_interactive_teleporters command queued",
        ),
        (
            "Probe yaw offset",
            GUICommandType.ProbeYawOffset,
            "scraper: probe_yaw_offset command queued",
        ),
        (
            "Verify yaw (+0x074)",
            GUICommandType.VerifyYaw,
            "scraper: verify_yaw command queued",
        ),
        (
            "Correlate calibration offsets",
            GUICommandType.CorrelateCalibration,
            "scraper: correlate_calibration command queued",
        ),
    ]:
        btn = StrokedButton(label)
        btn.setStyleSheet(ghost_style)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def _make_handler(c=cmd, m=log_msg):
            def _h():
                ctx.send_queue.put(GUICommand(c))
                logger.info(m)

            return _h

        btn.clicked.connect(_make_handler())
        debug_layout.addWidget(btn)

    walk_btn = StrokedButton("Walk through gate…")
    walk_btn.setStyleSheet(ghost_style)
    walk_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _walk_handler():
        dlg = QInputDialog(walk_btn.window())
        dlg.setWindowTitle("Walk through gate")
        dlg.setLabelText("Trigger name substring (e.g. 'Ravenwood', 'Library'):")
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dlg.setModal(True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = dlg.textValue().strip()
        if not text:
            return
        ctx.send_queue.put(GUICommand(GUICommandType.WalkThroughGate, text))
        logger.info(f"scraper: walk_through_gate('{text}') queued")

    walk_btn.clicked.connect(_walk_handler)
    debug_layout.addWidget(walk_btn)

    lay.addStretch(1)

    def _retheme():
        new_style = _build_btn_style()
        for btn in _primary_btns:
            try:
                btn.setStyleSheet(new_style)
            except RuntimeError:
                pass

    ctx.exports["scraper"] = {"retheme": _retheme}

    return tab
