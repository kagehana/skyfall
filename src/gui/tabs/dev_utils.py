from PyQt6.QtCore import Qt


from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


from src.gui.editorial import StrokedButton
from src.gui.commands import GUICommand, GUICommandType, GUIKeys

from src.gui.helpers import (
    copy_callback,
)

from src.gui.widgets import (
    AnimatedStackedWidget,
)

from src.paths import wizard_city_dance_game_path

from src.utils import assign_pet_level


def build_dev_utils_tab(ctx):

    from PyQt6.QtWidgets import QButtonGroup

    from src.gui import editorial as ed

    tab = QWidget()

    outer = ed.page_layout(tab)

    # Header: heading + small Indiv/Mass chip on the right
    head_row = QHBoxLayout()

    head_row.setContentsMargins(0, 0, 0, 0)

    head_row.setSpacing(12)

    head_row.addWidget(ed.heading("Dev Utils"))

    head_row.addStretch(1)

    def _build_seg_on():
        a = ed.accent_of(ctx)
        return (
            f"QPushButton {{"
            f"  background: {a};"
            f"  color: #fff;"
            f"  border: none;"
            f"  padding: 4px 14px;"
            f"  font-weight: 600;"
            f"  font-size: 8pt;"
            f"  letter-spacing: 1px;"
            f"}}"
            f"QPushButton:hover {{ background: {a}; }}"
        )

    _seg_on = _build_seg_on()

    _seg_off = (
        "QPushButton {"
        "  background: transparent;"
        "  color: rgba(236,236,236,0.45);"
        "  border: none;"
        "  padding: 4px 14px;"
        "  font-size: 8pt;"
        "  letter-spacing: 1px;"
        "}"
        "QPushButton:hover { color: rgba(236,236,236,0.85); }"
    )

    seg_bar = QWidget()

    seg_bar.setFixedHeight(28)

    seg_bar.setStyleSheet(
        "QWidget {  background: rgba(255,255,255,0.04);  border-radius: 6px;}"
    )

    seg_bar_layout = QHBoxLayout(seg_bar)

    seg_bar_layout.setContentsMargins(2, 2, 2, 2)

    seg_bar_layout.setSpacing(0)

    indiv_seg = StrokedButton("INDIVIDUAL")

    indiv_seg.setCheckable(True)

    indiv_seg.setChecked(True)

    indiv_seg.setCursor(Qt.CursorShape.PointingHandCursor)

    indiv_seg.setStyleSheet(_seg_on)

    mass_seg = StrokedButton("ALL CLIENTS")

    mass_seg.setCheckable(True)

    mass_seg.setCursor(Qt.CursorShape.PointingHandCursor)

    mass_seg.setStyleSheet(_seg_off)

    _seg_group = QButtonGroup()

    _seg_group.setExclusive(True)

    _seg_group.addButton(indiv_seg, 0)

    _seg_group.addButton(mass_seg, 1)

    seg_bar_layout.addWidget(indiv_seg)

    seg_bar_layout.addWidget(mass_seg)

    head_row.addWidget(seg_bar)

    outer.addLayout(head_row)

    outer.addSpacing(6)

    outer.addWidget(
        ed.subtitle(
            "Teleport, navigation, camera, and scale tools."
        )
    )

    outer.addSpacing(20)

    # scrollable body
    scroll = QScrollArea()

    scroll.setWidgetResizable(True)

    scroll.setFrameShape(QFrame.Shape.NoFrame)

    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    body = QWidget()

    body_layout = QVBoxLayout(body)

    body_layout.setContentsMargins(0, 0, 4, 10)

    body_layout.setSpacing(8)

    scroll.setWidget(body)

    outer.addWidget(scroll, 1)

    dev_inputs = {}

    def _inp(tag, ph=""):
        w = QLineEdit()
        w.setPlaceholderText(ph)
        dev_inputs[tag] = w
        ctx.widget_tags[tag] = w
        return w

    def _combo(tag, items, default=""):
        w = QComboBox()
        w.addItems(items)
        w.setCurrentText(default)
        dev_inputs[tag] = w
        ctx.widget_tags[tag] = w
        return w

    def _lbl(text):
        l = QLabel(text)
        l.setStyleSheet("color: rgba(236,236,236,0.5); font-size: 8pt;")
        l.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        return l

    def _section(text):
        # spacer + eyebrow + flex hairline; replaces the old _section_label + _hline pair
        body_layout.addSpacing(14)
        body_layout.addLayout(ed.section_eyebrow_row(text))
        body_layout.addSpacing(8)

    worlds = [
        "WizardCity",
        "Krokotopia",
        "Marleybone",
        "MooShu",
        "DragonSpire",
        "Grizzleheim",
        "Celestia",
        "Wysteria",
        "Zafaria",
        "Avalon",
        "Azteca",
        "Khrysalis",
        "Polaris",
        "Mirage",
        "Empyrea",
        "Karamelle",
        "Lemuria",
    ]

    pet_worlds = ["WizardCity", "Krokotopia", "Marleybone", "Mooshu", "Dragonspyre"]

    # TELEPORT
    _section(ctx.tl("tp_utils"))

    coord_row = QHBoxLayout()
    coord_row.setSpacing(4)
    coord_row.addWidget(_lbl("XYZ"))
    coord_row.addWidget(_inp("TPCoordsInput", "X, Y, Z  (or  X, Y, Z, Yaw)"), 1)
    body_layout.addLayout(coord_row)

    ent_row = QHBoxLayout()

    ent_row.setSpacing(4)

    ent_row.addWidget(_lbl(ctx.tl("entity_name")))

    ent_row.addWidget(_inp("EntityTPInput", ctx.tl("entity_name")), 2)

    ent_row.addWidget(_lbl("GID"))

    ent_row.addWidget(_inp("EntityTPGIDInput", "GID"), 1)

    body_layout.addLayout(ent_row)

    tp_btn_stack = AnimatedStackedWidget(duration=180)

    def custom_tp_callback():
        import re as _re

        gid = dev_inputs["EntityTPGIDInput"].text()
        name = dev_inputs["EntityTPInput"].text()
        raw = dev_inputs["TPCoordsInput"].text().strip()
        parts = [p for p in _re.split(r"[\s,;()]+", raw) if p] if raw else []
        # pad to 4 (X, Y, Z, Yaw) so downstream consumer sees blanks for missing
        parts = (parts + ["", "", "", ""])[:4]
        tp_vals = parts
        if gid:
            ctx.send_queue.put(
                GUICommand(GUICommandType.EntityTeleport, {"name": "", "gid": gid})
            )
        elif name:
            ctx.send_queue.put(
                GUICommand(GUICommandType.EntityTeleport, {"name": name, "gid": ""})
            )
        elif any(tp_vals):
            ctx.send_queue.put(
                GUICommand(
                    GUICommandType.CustomTeleport,
                    {
                        "X": tp_vals[0],
                        "Y": tp_vals[1],
                        "Z": tp_vals[2],
                        "Yaw": tp_vals[3],
                    },
                )
            )

    tp_indiv_page = QWidget()

    tp_indiv_row = QHBoxLayout(tp_indiv_page)

    tp_indiv_row.setContentsMargins(0, 0, 0, 0)

    tp_indiv_row.setSpacing(4)

    tp_indiv_row.addWidget(
        ctx.registry.styled_btn(ctx.tl("custom_tp"), custom_tp_callback)
    )

    tp_btn_stack.addWidget(tp_indiv_page)

    _mass_tp_widgets = []

    def mass_custom_tp_callback():
        import re as _re

        gid = dev_inputs["EntityTPGIDInput"].text()
        name = dev_inputs["EntityTPInput"].text()
        raw = dev_inputs["TPCoordsInput"].text().strip()
        parts = [p for p in _re.split(r"[\s,;()]+", raw) if p] if raw else []
        parts = (parts + ["", "", "", ""])[:4]
        if gid:
            ctx.send_queue.put(
                GUICommand(
                    GUICommandType.EntityTeleport,
                    {"name": "", "gid": gid, "mass": True},
                )
            )
        elif name:
            ctx.send_queue.put(
                GUICommand(
                    GUICommandType.EntityTeleport,
                    {"name": name, "gid": "", "mass": True},
                )
            )
        elif any(parts):
            ctx.send_queue.put(
                GUICommand(
                    GUICommandType.CustomTeleport,
                    {
                        "X": parts[0],
                        "Y": parts[1],
                        "Z": parts[2],
                        "Yaw": parts[3],
                        "mass": True,
                    },
                )
            )

    tp_mass_page = QWidget()

    tp_mass_row = QHBoxLayout(tp_mass_page)

    tp_mass_row.setContentsMargins(0, 0, 0, 0)

    tp_mass_row.setSpacing(4)

    _mass_tp_btn = ctx.registry.styled_btn(
        ctx.tl("mass_custom_tp"), mass_custom_tp_callback
    )

    _mass_tp_widgets.append(_mass_tp_btn)

    tp_mass_row.addWidget(_mass_tp_btn)

    tp_btn_stack.addWidget(tp_mass_page)

    body_layout.addWidget(tp_btn_stack)

    # NAVIGATION
    _section(ctx.tl("navigation"))

    zone_row = QHBoxLayout()

    zone_row.setSpacing(4)

    zone_row.addWidget(_lbl(ctx.tl("zone_name")))

    zone_row.addWidget(_inp("ZoneInput", ctx.tl("zone_name")), 1)

    body_layout.addLayout(zone_row)

    world_row = QHBoxLayout()

    world_row.setSpacing(4)

    world_row.addWidget(_lbl(ctx.tl("world_name")))

    world_row.addWidget(_combo("WorldInput", worlds, "WizardCity"), 1)

    body_layout.addLayout(world_row)

    nav_btn_stack = AnimatedStackedWidget(duration=180)

    _mass_nav_widgets = []

    def go_to_zone_callback():
        val = dev_inputs["ZoneInput"].text()
        if val:
            ctx.send_queue.put(GUICommand(GUICommandType.GoToZone, (False, val)))

    def go_to_world_callback():
        val = dev_inputs["WorldInput"].currentText()
        if val:
            ctx.send_queue.put(GUICommand(GUICommandType.GoToWorld, (False, val)))

    def go_to_bazaar_callback():
        ctx.send_queue.put(GUICommand(GUICommandType.GoToBazaar, False))

    def refill_potions_callback():
        ctx.send_queue.put(GUICommand(GUICommandType.RefillPotions, False))

    nav_indiv_page = QWidget()

    nav_indiv_layout = QVBoxLayout(nav_indiv_page)

    nav_indiv_layout.setContentsMargins(0, 0, 0, 0)

    nav_indiv_layout.setSpacing(4)

    nav_row1 = QHBoxLayout()

    nav_row1.setSpacing(4)

    nav_row1.addWidget(
        ctx.registry.styled_btn(ctx.tl("go_to_zone"), go_to_zone_callback)
    )

    nav_row1.addWidget(
        ctx.registry.styled_btn(ctx.tl("go_to_world"), go_to_world_callback)
    )

    nav_indiv_layout.addLayout(nav_row1)

    nav_row2 = QHBoxLayout()

    nav_row2.setSpacing(4)

    nav_row2.addWidget(
        ctx.registry.styled_btn(ctx.tl("go_to_bazaar"), go_to_bazaar_callback)
    )

    nav_row2.addWidget(
        ctx.registry.styled_btn(ctx.tl("refill_potions"), refill_potions_callback)
    )

    nav_indiv_layout.addLayout(nav_row2)

    nav_btn_stack.addWidget(nav_indiv_page)

    def mass_go_to_zone_callback():
        val = dev_inputs["ZoneInput"].text()
        if val:
            ctx.send_queue.put(GUICommand(GUICommandType.GoToZone, (True, val)))

    def mass_go_to_world_callback():
        val = dev_inputs["WorldInput"].currentText()
        if val:
            ctx.send_queue.put(GUICommand(GUICommandType.GoToWorld, (True, val)))

    def mass_go_to_bazaar_callback():
        ctx.send_queue.put(GUICommand(GUICommandType.GoToBazaar, True))

    def mass_refill_potions_callback():
        ctx.send_queue.put(GUICommand(GUICommandType.RefillPotions, True))

    nav_mass_page = QWidget()

    nav_mass_layout = QVBoxLayout(nav_mass_page)

    nav_mass_layout.setContentsMargins(0, 0, 0, 0)

    nav_mass_layout.setSpacing(4)

    nav_mass_row1 = QHBoxLayout()

    nav_mass_row1.setSpacing(4)

    for lbl_text, cb in [
        (ctx.tl("mass_go_to_zone"), mass_go_to_zone_callback),
        (ctx.tl("mass_go_to_world"), mass_go_to_world_callback),
    ]:
        b = ctx.registry.styled_btn(lbl_text, cb)
        _mass_nav_widgets.append(b)
        nav_mass_row1.addWidget(b)

    nav_mass_layout.addLayout(nav_mass_row1)

    nav_mass_row2 = QHBoxLayout()

    nav_mass_row2.setSpacing(4)

    for lbl_text, cb in [
        (ctx.tl("mass_go_to_bazaar"), mass_go_to_bazaar_callback),
        (ctx.tl("mass_refill_potions"), mass_refill_potions_callback),
    ]:
        b = ctx.registry.styled_btn(lbl_text, cb)
        _mass_nav_widgets.append(b)
        nav_mass_row2.addWidget(b)

    nav_mass_layout.addLayout(nav_mass_row2)

    nav_btn_stack.addWidget(nav_mass_page)

    body_layout.addWidget(nav_btn_stack)

    # MISC
    _section(ctx.tl("misc"))

    misc_row = QHBoxLayout()

    misc_row.setSpacing(4)

    misc_row.addWidget(_lbl(ctx.tl("scale")))

    misc_row.addWidget(_inp("scale", ctx.tl("scale")), 1)

    def set_scale_callback():
        ctx.send_queue.put(
            GUICommand(GUICommandType.SetScale, dev_inputs["scale"].text())
        )

    misc_row.addWidget(ctx.registry.styled_btn(ctx.tl("set_scale"), set_scale_callback))

    misc_row.addWidget(_lbl(ctx.tl("select_pet_world")))

    misc_row.addWidget(_combo("PetWorldInput", pet_worlds, "WizardCity"), 1)

    body_layout.addLayout(misc_row)

    pet_combo = dev_inputs["PetWorldInput"]

    def pet_world_callback(text):
        if text != wizard_city_dance_game_path[-1]:
            assign_pet_level(text)

    pet_combo.currentTextChanged.connect(pet_world_callback)

    # CAMERA
    _section("Camera")

    cam_row1 = QHBoxLayout()
    cam_row1.setSpacing(4)
    cam_row1.addWidget(_lbl("XYZ"))
    cam_row1.addWidget(_inp("CamCoordsInput", "X, Y, Z"), 1)
    body_layout.addLayout(cam_row1)

    cam_row2 = QHBoxLayout()

    cam_row2.setSpacing(4)

    for lbl, tag, default in [
        (ctx.tl("yaw"), "CamYawInput", None),
        (ctx.tl("pitch"), "CamPitchInput", None),
        (ctx.tl("roll"), "CamRollInput", "0"),
    ]:
        cam_row2.addWidget(_lbl(lbl))
        inp = _inp(tag, lbl)
        cam_row2.addWidget(inp, 1)
        if default is not None:
            rb = StrokedButton("↺")
            rb.setFixedSize(22, 22)
            rb.setStyleSheet(ctx.icon_btn_style)
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            rb.setToolTip(ctx.tl("reset_to_default").format(default))
            rb.clicked.connect(lambda _c, i=inp, d=default: i.setText(d))
            cam_row2.addWidget(rb)

    body_layout.addLayout(cam_row2)

    cam_ent_row = QHBoxLayout()

    cam_ent_row.setSpacing(4)

    cam_ent_row.addWidget(_lbl(ctx.tl("entity")))

    cam_ent_row.addWidget(_inp("CamEntityInput", "Player Object"), 2)

    cam_ent_row.addWidget(_lbl("GID"))

    cam_ent_row.addWidget(_inp("CamEntityGIDInput", "GID"), 1)

    cam_fetch_btn = StrokedButton(ctx.tl("fetch_player_gid"))

    cam_fetch_btn.setStyleSheet(ctx.icon_btn_style)

    cam_fetch_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    cam_fetch_btn.clicked.connect(
        lambda _c: ctx.send_queue.put(GUICommand(GUICommandType.PopulatePlayerGID))
    )

    cam_ent_row.addWidget(cam_fetch_btn)

    body_layout.addLayout(cam_ent_row)

    cam_dist_row = QHBoxLayout()

    cam_dist_row.setSpacing(4)

    for lbl, tag, default in [
        (ctx.tl("distance"), "CamDistanceInput", "300"),
        (ctx.tl("dist_min"), "CamMinInput", "150"),
        (ctx.tl("dist_max"), "CamMaxInput", "450"),
    ]:
        cam_dist_row.addWidget(_lbl(lbl))
        inp = _inp(tag, lbl)
        cam_dist_row.addWidget(inp, 1)
        rb = StrokedButton("↺")
        rb.setFixedSize(22, 22)
        rb.setStyleSheet(ctx.icon_btn_style)
        rb.setCursor(Qt.CursorShape.PointingHandCursor)
        rb.setToolTip(ctx.tl("reset_to_default").format(default))
        rb.clicked.connect(lambda _c, i=inp, d=default: i.setText(d))
        cam_dist_row.addWidget(rb)

    body_layout.addLayout(cam_dist_row)

    def update_camera_callback():
        import re as _re

        raw = dev_inputs["CamCoordsInput"].text().strip()
        xyz = [p for p in _re.split(r"[\s,;()]+", raw) if p] if raw else []
        xyz = (xyz + ["", "", ""])[:3]
        pos_vals = {
            "X": xyz[0],
            "Y": xyz[1],
            "Z": xyz[2],
            "Yaw": dev_inputs["CamYawInput"].text(),
            "Roll": dev_inputs["CamRollInput"].text(),
            "Pitch": dev_inputs["CamPitchInput"].text(),
        }
        if any(pos_vals.values()):
            ctx.send_queue.put(GUICommand(GUICommandType.SetCamPosition, pos_vals))
        anchor_name = dev_inputs["CamEntityInput"].text()
        anchor_gid = dev_inputs["CamEntityGIDInput"].text()
        if anchor_name or anchor_gid:
            ctx.send_queue.put(
                GUICommand(
                    GUICommandType.AnchorCam, {"name": anchor_name, "gid": anchor_gid}
                )
            )
        dist_vals = {
            "Distance": dev_inputs["CamDistanceInput"].text(),
            "Min": dev_inputs["CamMinInput"].text(),
            "Max": dev_inputs["CamMaxInput"].text(),
        }
        if any(dist_vals.values()):
            ctx.send_queue.put(GUICommand(GUICommandType.SetCamDistance, dist_vals))

    cam_action_row = QHBoxLayout()

    cam_action_row.setSpacing(4)

    cam_action_row.addWidget(
        ctx.registry.styled_btn(ctx.tl("set_camera_position"), update_camera_callback)
    )

    cam_action_row.addWidget(
        ctx.registry.styled_btn(
            ctx.tl("populate_camera"),
            lambda: ctx.send_queue.put(GUICommand(GUICommandType.PopulateCamera)),
        )
    )

    cam_action_row.addWidget(
        ctx.registry.styled_btn(
            ctx.tl("copy_camera_position"),
            copy_callback(ctx.send_queue, GUIKeys.copy_camera_position),
        )
    )

    cam_action_row.addWidget(
        ctx.registry.styled_btn(
            ctx.tl("toggle_camera_collision"),
            lambda: ctx.send_queue.put(
                GUICommand(GUICommandType.ToggleOption, GUIKeys.toggle_camera_collision)
            ),
        )
    )

    body_layout.addLayout(cam_action_row)

    body_layout.addStretch()

    # individual / Mass toggle wiring
    _mass_active = [False]

    def _apply_seg_styles():
        if _mass_active[0]:
            indiv_seg.setStyleSheet(_seg_off)
            mass_seg.setStyleSheet(_seg_on)
        else:
            indiv_seg.setStyleSheet(_seg_on)
            mass_seg.setStyleSheet(_seg_off)

    def _show_individual():
        _mass_active[0] = False
        tp_btn_stack.slide_to(0)
        nav_btn_stack.slide_to(0)
        _apply_seg_styles()

    def _show_mass():
        _mass_active[0] = True
        tp_btn_stack.slide_to(1)
        nav_btn_stack.slide_to(1)
        _apply_seg_styles()

    indiv_seg.clicked.connect(_show_individual)

    mass_seg.clicked.connect(_show_mass)

    def _update_mass_state(client_count):
        enabled = client_count > 1
        for w in _mass_nav_widgets + _mass_tp_widgets:
            w.setEnabled(enabled)
            if enabled:
                w.setGraphicsEffect(None)
            else:
                eff = QGraphicsOpacityEffect(w)
                eff.setOpacity(0.35)
                w.setGraphicsEffect(eff)

    _update_mass_state(0)

    def _retheme():
        nonlocal _seg_on
        _seg_on = _build_seg_on()
        _apply_seg_styles()

    ctx.exports["dev_utils"] = {
        "update_mass_state": _update_mass_state,
        "retheme": _retheme,
    }

    return tab
