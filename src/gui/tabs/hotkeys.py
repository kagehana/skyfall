from PyQt6.QtCore import Qt


from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


from src.gui.editorial import StrokedButton
from src.gui.commands import GUICommand, GUICommandType, GUIKeys

from src.gui.helpers import (
    repo_icon_btn,
    teleport_callback,
    toggle_callback_targeted,
)

from src.gui.widgets import (
    AnimatedStackedWidget,
    HotkeyCapture,
    ToggleNameLabel,
)


def build_hotkeys_tab(ctx):

    from src.gui import editorial as ed

    tab = QWidget()

    hotkeys_layout = ed.page_layout(tab)

    registry = ctx.registry

    tl = ctx.tl

    send_queue = ctx.send_queue

    settings = ctx.settings

    accent = ed.accent_of(ctx)

    # header: heading + per-client target chip on the right (dev-utils style)
    head_row = QHBoxLayout()
    head_row.setContentsMargins(0, 0, 0, 0)
    head_row.setSpacing(12)
    head_row.addWidget(ed.heading(tl("hotkeys") if hasattr(ctx, "tl") else "Hotkeys"))
    head_row.addStretch(1)

    # segmented selector container, populated later once the repaint logic exists
    _target_bar = QWidget()
    _target_bar.setFixedHeight(28)
    _target_bar.setStyleSheet(
        "QWidget { background: rgba(255,255,255,0.04); border-radius: 6px; }"
    )
    _target_bar_layout = QHBoxLayout(_target_bar)
    _target_bar_layout.setContentsMargins(2, 2, 2, 2)
    _target_bar_layout.setSpacing(0)
    _target_group = QButtonGroup()
    _target_group.setExclusive(True)
    _target_seg_btns: list = []  # (button, title)
    head_row.addWidget(_target_bar)

    hotkeys_layout.addLayout(head_row)

    hotkeys_layout.addSpacing(6)

    hotkeys_layout.addWidget(
        ed.subtitle("Click any keycap to rebind. Bindings are grouped by category.")
    )

    hotkeys_layout.addSpacing(20)

    def xyz_sync_callback():

        send_queue.put(GUICommand(GUICommandType.XYZSync))

    def x_press_callback():

        send_queue.put(GUICommand(GUICommandType.XPress))

    def friend_tp_callback():

        send_queue.put(GUICommand(GUICommandType.FriendTeleport))

    _toggle_icons = ctx.svgs

    def _esp_toggle_callback():
        send_queue.put(GUICommand(GUICommandType.ToggleEsp))

    # active-client target for the per-client toggles. "All" applies a press to
    # every hooked client (legacy behaviour); a "pN" title targets one client
    # the dropdown (built below) writes into this list; get_target reads it
    _toggle_target = ["All"]

    def get_target():
        return _toggle_target[0]

    def _tc(event_key):
        return toggle_callback_targeted(send_queue, event_key, get_target)

    _hk_categories = [
        (
            tl("cat_toggles"),
            [
                (
                    "toggle_speed",
                    tl("speedhack"),
                    _tc(GUIKeys.toggle_speedhack),
                    True,
                    tl("speedhack"),
                    _toggle_icons["gauge"],
                ),
                (
                    "toggle_combat",
                    tl("combat_toggle"),
                    _tc(GUIKeys.toggle_combat),
                    True,
                    tl("combat_toggle"),
                    _toggle_icons["combat"],
                ),
                (
                    "toggle_dialogue",
                    tl("dialogue"),
                    _tc(GUIKeys.toggle_dialogue),
                    True,
                    tl("dialogue"),
                    _toggle_icons["chat"],
                ),
                (
                    "toggle_sigil",
                    tl("sigil"),
                    _tc(GUIKeys.toggle_sigil),
                    True,
                    tl("sigil"),
                    _toggle_icons["bot"],
                ),
                (
                    "toggle_questing",
                    tl("questing"),
                    _tc(GUIKeys.toggle_questing),
                    True,
                    tl("questing"),
                    _toggle_icons["brain"],
                ),
                (
                    "toggle_auto_pet",
                    tl("auto_pet"),
                    _tc(GUIKeys.toggle_auto_pet),
                    True,
                    tl("auto_pet"),
                    _toggle_icons["paw"],
                ),
                (
                    "toggle_auto_potion",
                    tl("auto_potion"),
                    _tc(GUIKeys.toggle_auto_potion),
                    True,
                    tl("auto_potion"),
                    _toggle_icons["flask"],
                ),
                (
                    "toggle_freecam",
                    tl("freecam"),
                    _tc(GUIKeys.toggle_freecam),
                    True,
                    tl("freecam"),
                    _toggle_icons["videocam"],
                ),
                (
                    "toggle_esp",
                    "ESP",
                    _esp_toggle_callback,
                    True,
                    "Esp",
                    _toggle_icons["eye"],
                ),
            ],
        ),
        (
            tl("cat_teleports"),
            [
                (
                    "quest_tp",
                    tl("quest_tp"),
                    teleport_callback(send_queue, GUIKeys.hotkey_quest_tp),
                    False,
                    None,
                    _toggle_icons["goal"],
                ),
                (
                    "freecam_tp",
                    tl("freecam_tp"),
                    teleport_callback(send_queue, GUIKeys.hotkey_freecam_tp),
                    False,
                    None,
                    _toggle_icons["view"],
                ),
                (
                    "friend_tp",
                    tl("friend_tp"),
                    friend_tp_callback,
                    False,
                    None,
                    _toggle_icons["contact"],
                ),
            ],
        ),
        (
            tl("cat_multi_client"),
            [
                (
                    "mass_tp",
                    tl("mass_tp"),
                    teleport_callback(send_queue, GUIKeys.mass_hotkey_mass_tp),
                    False,
                    None,
                    _toggle_icons["mass"],
                ),
                (
                    "xyz_sync",
                    tl("xyz_sync"),
                    xyz_sync_callback,
                    False,
                    None,
                    _toggle_icons["locate"],
                ),
                (
                    "x_press",
                    tl("x_press"),
                    x_press_callback,
                    False,
                    None,
                    _toggle_icons["keyboard"],
                ),
            ],
        ),
        (
            tl("cat_system"),
            [
                (
                    "kill_tool",
                    tl("kill_tool"),
                    None,
                    False,
                    None,
                    _toggle_icons["exit"],
                ),
            ],
        ),
    ]

    # styles
    _cat_label_style = (
        "QLabel {"
        "  font-size: 8pt;"
        "  font-weight: 600;"
        "  color: rgba(236,236,236,0.45);"
        "  letter-spacing: 1.8px;"
        "  text-transform: uppercase;"
        "  padding: 14px 0 6px 0;"
        "}"
    )

    def _build_keycap_style():
        a = ed.accent_of(ctx)
        return (
            "QPushButton {"
            "  background-color: rgba(255,255,255,0.04);"
            "  color: rgba(236,236,236,0.85);"
            "  border: 1px solid rgba(255,255,255,0.10);"
            "  border-radius: 5px;"
            "  padding: 2px 10px;"
            "  font-family: 'Cascadia Mono', 'Consolas', monospace;"
            "  font-size: 8pt;"
            "  letter-spacing: 0.5px;"
            "  min-width: 70px;"
            "  max-width: 110px;"
            "}"
            "QPushButton:hover {"
            f"  border-color: {a};"
            "  color: rgba(255,255,255,0.95);"
            "  background-color: rgba(255,255,255,0.06);"
            "}"
            "QPushButton:disabled {"
            "  color: rgba(236,236,236,0.25);"
            "  border-color: rgba(255,255,255,0.05);"
            "}"
        )

    _keycap_style = _build_keycap_style()

    _row_style = (
        "QWidget#hkrow {"
        "  border-radius: 6px;"
        "}"
        "QWidget#hkrow:hover {"
        "  background-color: rgba(255,255,255,0.04);"
        "}"
    )

    # scroll area
    hk_scroll = QScrollArea()

    hk_scroll.setWidgetResizable(True)

    hk_scroll.setFrameShape(QFrame.Shape.NoFrame)

    hk_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    hk_scroll_widget = QWidget()

    hk_scroll_layout = QVBoxLayout(hk_scroll_widget)

    hk_scroll_layout.setContentsMargins(0, 0, 4, 0)

    hk_scroll_layout.setSpacing(1)

    _dynamic_header_added = [False]

    _dynamic_header_label = [None]

    _hk_stretch_index = [None]

    _dynamic_row_widgets = {}

    def _make_edit_handler(aid):

        def handler():

            meta = registry.meta.get(aid, {})

            all_bindings = settings.get_hotkeys() if settings else {}

            dlg = HotkeyCapture(
                meta.get("name", aid), all_bindings, aid, tl=tl, parent=tab.window()
            )

            def _on_captured(key, mods):

                if key == "":
                    registry.do_rebind(aid, None, None)

                else:
                    registry.do_rebind(aid, key, mods)

            dlg.captured.connect(_on_captured)

            dlg.exec()

        return handler

    def _make_clear_handler(aid):

        def handler():

            registry.do_rebind(aid, None, None)

            if aid in registry.row_widgets:
                registry.row_widgets[aid].setVisible(False)

            if _dynamic_header_label[0] is not None and all(
                not w.isVisible() for w in _dynamic_row_widgets.values()
            ):
                _dynamic_header_label[0].setVisible(False)

        return handler

    def _build_hk_row(
        action_id,
        display_name,
        callback,
        is_toggle=False,
        tag_name=None,
        icon_svg=None,
        removable=False,
        category=None,
        inline_widget=None,
    ):

        row_widget = QWidget()

        row_widget.setObjectName("hkrow")

        row_widget.setStyleSheet(_row_style)

        row_widget.setFixedHeight(30)

        row = QHBoxLayout(row_widget)

        row.setSpacing(6)

        row.setContentsMargins(4, 0, 4, 0)

        # icon
        if icon_svg:
            icon_label = QLabel()

            icon_label.setFixedSize(18, 18)

            icon_label.setPixmap(ctx.titlebar_svg_icon(icon_svg, 14).pixmap(14, 14))

            icon_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

            icon_label.setStyleSheet("background: transparent;")

            ctx.tracked_svg_labels.append([icon_label, icon_svg, 14, "pixmap"])

            row.addWidget(icon_label)

        # name label (left-aligned, expanding)
        if is_toggle and tag_name:
            name_label = ToggleNameLabel(display_name)

            ctx.widget_tags[f"{tag_name}Status"] = name_label

        else:
            name_label = QLabel(display_name)

        name_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        name_label.setStyleSheet("background: transparent;")

        name_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        row.addWidget(name_label)

        # key cap button (clicking = rebind)
        binding_text = registry.get_binding_display(action_id)

        key_btn = StrokedButton(binding_text)

        key_btn.setStyleSheet(_keycap_style)

        key_btn.setFixedHeight(22)

        key_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        key_btn.setToolTip(tl("bind_hotkey"))

        key_btn.clicked.connect(_make_edit_handler(action_id))

        registry.key_labels[action_id] = key_btn

        if inline_widget is not None:
            row.addWidget(inline_widget)

        row.addWidget(key_btn)

        # clear button for removable (dynamic) rows
        if removable:
            _x_svg = ctx.svgs["x"]

            clear_btn = StrokedButton()

            clear_btn.setIcon(ctx.titlebar_svg_icon(_x_svg, 12))

            clear_btn.setFixedSize(18, 18)

            clear_btn.setStyleSheet(ctx.icon_btn_style)

            clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            clear_btn.setToolTip(tl("unbind_hotkey"))

            clear_btn.clicked.connect(_make_clear_handler(action_id))

            ctx.tracked_svg_labels.append([clear_btn, _x_svg, 12, "icon"])

            registry.clear_btns[action_id] = clear_btn

            row.addWidget(clear_btn)

        if callback:

            def _on_release(event, cb=callback):
                if event.button() == Qt.MouseButton.LeftButton:
                    cb()

            row_widget.mouseReleaseEvent = _on_release
            row_widget.setCursor(Qt.CursorShape.PointingHandCursor)
            name_label.mouseReleaseEvent = _on_release
            name_label.setCursor(Qt.CursorShape.PointingHandCursor)
            if icon_svg:
                icon_label.mouseReleaseEvent = _on_release
                icon_label.setCursor(Qt.CursorShape.PointingHandCursor)

        return row_widget

    def _add_dynamic_hk_row(action_id):

        if action_id in _dynamic_row_widgets:
            _dynamic_row_widgets[action_id].setVisible(True)

            registry.row_widgets[action_id] = _dynamic_row_widgets[action_id]

            if _dynamic_header_label[0] is not None:
                _dynamic_header_label[0].setVisible(True)

            return

        meta = registry.meta.get(action_id, {})

        display_name = meta.get("name", action_id)

        cat = meta.get("category", "") or None

        callback = registry.callbacks.get(action_id)

        insert_idx = (
            _hk_stretch_index[0]
            if _hk_stretch_index[0] is not None
            else hk_scroll_layout.count()
        )

        if not _dynamic_header_added[0]:
            _dynamic_header_added[0] = True

            hdr = QLabel(tl("cat_other").upper())

            hdr.setStyleSheet(_cat_label_style)

            _dynamic_header_label[0] = hdr

            hk_scroll_layout.insertWidget(insert_idx, hdr)

            insert_idx += 1

            if _hk_stretch_index[0] is not None:
                _hk_stretch_index[0] += 1

        elif _dynamic_header_label[0] is not None:
            _dynamic_header_label[0].setVisible(True)

        row_widget = _build_hk_row(
            action_id,
            display_name,
            callback,
            icon_svg=_toggle_icons["custom"],
            removable=True,
            category=cat,
        )

        hk_scroll_layout.insertWidget(insert_idx, row_widget)

        _dynamic_row_widgets[action_id] = row_widget

        registry.row_widgets[action_id] = row_widget

        if _hk_stretch_index[0] is not None:
            _hk_stretch_index[0] += 1

    # controls wired as sub-rows under their parent toggles
    from src.gui.dialog import (
        _NoScrollDoubleSpinBox,
        _NoScrollComboBox,
        _CLIENT_OPTIONS,
    )
    from src.settings import DEFAULT_SETTINGS

    _ctrl_input_style = (
        "background-color: rgba(255,255,255,0.05);"
        " color: rgba(236,236,236,0.9);"
        " border: 1px solid rgba(255,255,255,0.08);"
        " border-radius: 6px;"
        " padding: 2px 6px;"
    )
    _ctrl_cb_style = (
        f"QCheckBox {{ spacing: 6px; color: rgba(236,236,236,0.65); font-size: 8.3pt; }}"
        f"QCheckBox::indicator {{ width: 14px; height: 14px;"
        f" border: 1px solid rgba(255,255,255,0.15); border-radius: 3px;"
        f" background: rgba(255,255,255,0.04); }}"
        f"QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}"
    )
    _sub_row_style = (
        "QWidget#subrow { border-radius: 4px; }"
        "QWidget#subrow:hover { background-color: rgba(255,255,255,0.03); }"
    )

    def _get_s(key):
        return settings.get_setting(key) if settings else DEFAULT_SETTINGS.get(key)

    def _set_s(key, val):
        if settings:
            settings.set_setting(key, val)
        send_queue.put(GUICommand(GUICommandType.UpdateSettings, {key: val}))

    _follow_row_refs: dict = {}

    def _build_sub_row(label_text, control_widget):
        rw = QWidget()
        rw.setObjectName("subrow")
        rw.setStyleSheet(_sub_row_style)
        rw.setFixedHeight(26)
        r = QHBoxLayout(rw)
        r.setSpacing(8)
        r.setContentsMargins(28, 0, 4, 0)  # indent aligns past icon column
        lbl = None
        if label_text:
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                "color: rgba(236,236,236,0.50); font-size: 8.3pt; background: transparent;"
            )
            lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            r.addWidget(lbl)
        control_widget.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        r.addWidget(control_widget)
        if getattr(control_widget, "_dim_with_team_up", False):
            _follow_row_refs["row"] = rw
            _follow_row_refs["label"] = lbl
        return rw

    def _make_checkbox(label_key, setting_key):
        cb = QCheckBox("")  # label lives in _build_sub_row, not on the widget
        cb.setChecked(bool(_get_s(setting_key)))
        cb.setStyleSheet(_ctrl_cb_style)
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.stateChanged.connect(lambda s, k=setting_key: _set_s(k, bool(s)))
        return cb

    # build all sub-controls upfront
    _speed_spin = _NoScrollDoubleSpinBox()
    _speed_spin.setRange(0.1, 20.0)
    _speed_spin.setSingleStep(0.5)
    _speed_spin.setDecimals(1)
    _speed_spin.setValue(float(_get_s("speed_multiplier") or 5.0))
    _speed_spin.setFixedWidth(80)
    _speed_spin.setFixedHeight(22)
    _speed_spin.setStyleSheet(_ctrl_input_style)

    # per-client speed multipliers. "All" edits the persisted default and every
    # client; a specific target stores/sends just that client's multiplier
    _default_speed = float(_get_s("speed_multiplier") or 5.0)
    _per_client_speed: dict = {}

    def _on_speed_changed(v):
        nonlocal _default_speed
        tgt = get_target()
        if tgt in (None, "All"):
            # backend applies an "All" change to every client, so drop the
            # per-client overrides - they all follow the new default now
            _default_speed = v
            _per_client_speed.clear()
            _set_s("speed_multiplier", v)
        else:
            _per_client_speed[tgt] = v
            send_queue.put(
                GUICommand(
                    GUICommandType.UpdateSettings,
                    {"speed_multiplier": v, "_speed_target": tgt},
                )
            )

    _speed_spin.valueChanged.connect(_on_speed_changed)

    _speed_ctrl = _speed_spin

    _hitter_combo = _NoScrollComboBox()
    _hitter_combo.addItems(_CLIENT_OPTIONS)
    _hv = _get_s("hitter_client")
    _hitter_combo.setCurrentText(str(_hv) if _hv else "None")
    _hitter_combo.setFixedWidth(80)
    _hitter_combo.setFixedHeight(22)
    _hitter_combo.setStyleSheet(_ctrl_input_style)
    _hitter_combo.currentTextChanged.connect(
        lambda t: _set_s("hitter_client", None if t == "None" else t)
    )

    # Per-client "Exclude from Questing" row: four small p1/p2/p3/p4
    # checkboxes packed into a single sub-row control widget. checked
    # clients are hidden from the leader's Quester (no own Quester
    # either) so a hooked-but-parked wizard doesn't get dragged through
    # sigils/team-ups/potion runs
    _excl_wrap = QWidget()
    _excl_wrap.setStyleSheet("background: transparent;")
    _excl_layout = QHBoxLayout(_excl_wrap)
    _excl_layout.setContentsMargins(0, 0, 0, 0)
    _excl_layout.setSpacing(10)
    _excluded_now = set(_get_s("quest_excluded_clients") or [])
    _excl_cbs: list[QCheckBox] = []
    for _slot in ("p1", "p2", "p3", "p4"):
        _cb = QCheckBox(_slot)
        _cb.setChecked(_slot in _excluded_now)
        _cb.setStyleSheet(_ctrl_cb_style)
        _cb.setCursor(Qt.CursorShape.PointingHandCursor)
        _excl_layout.addWidget(_cb)
        _excl_cbs.append(_cb)

    def _on_excl_toggled(_=None):
        _set_s(
            "quest_excluded_clients",
            [cb.text() for cb in _excl_cbs if cb.isChecked()],
        )

    for _cb in _excl_cbs:
        _cb.stateChanged.connect(_on_excl_toggled)

    _follow_combo = _NoScrollComboBox()
    _follow_combo.addItems(_CLIENT_OPTIONS)
    _fv = _get_s("client_to_follow")
    _follow_combo.setCurrentText(str(_fv) if _fv else "None")
    _follow_combo.setFixedWidth(80)
    _follow_combo.setFixedHeight(22)
    _follow_combo.setStyleSheet(_ctrl_input_style)
    _follow_combo.currentTextChanged.connect(
        lambda t: _set_s("client_to_follow", None if t == "None" else t)
    )
    _follow_combo._dim_with_team_up = True

    _team_up_cb = _make_checkbox("setting_use_team_up", "use_team_up")

    def _apply_team_up_lock(checked: bool):
        _follow_combo.setEnabled(not checked)
        if checked:
            _follow_combo.setCurrentText("None")
            _set_s("client_to_follow", None)
        row = _follow_row_refs.get("row")
        label = _follow_row_refs.get("label")
        for w in (row, label, _follow_combo):
            if w is None:
                continue
            if checked:
                eff = QGraphicsOpacityEffect(w)
                eff.setOpacity(0.35)
                w.setGraphicsEffect(eff)
            else:
                w.setGraphicsEffect(None)

    _team_up_cb.stateChanged.connect(lambda s: _apply_team_up_lock(bool(s)))

    _team_type_combo = _NoScrollComboBox()
    _team_type_combo.addItems(["Questing", "Farming"])
    _tv = (_get_s("team_up_type") or "questing").lower()
    _team_type_combo.setCurrentText("Farming" if _tv == "farming" else "Questing")
    _team_type_combo.setFixedWidth(100)
    _team_type_combo.setFixedHeight(22)
    _team_type_combo.setStyleSheet(_ctrl_input_style)
    _team_type_combo.currentTextChanged.connect(
        lambda t: _set_s("team_up_type", t.lower())
    )

    _team_size_combo = _NoScrollComboBox()
    _team_size_combo.addItems(["2", "3", "4"])
    _sv = str(_get_s("team_up_size") or "2")
    _team_size_combo.setCurrentText(_sv if _sv in ("2", "3", "4") else "2")
    _team_size_combo.setFixedWidth(100)
    _team_size_combo.setFixedHeight(22)
    _team_size_combo.setStyleSheet(_ctrl_input_style)
    _team_size_combo.currentTextChanged.connect(lambda t: _set_s("team_up_size", t))

    # map: action_id → list of (label_text, control_widget) sub-rows
    _sub_rows: dict[str, list] = {
        "toggle_sigil": [
            (
                tl("setting_use_team_up")
                if tl("setting_use_team_up") != "setting_use_team_up"
                else "Use Team Up",
                _team_up_cb,
            ),
            ("Team Type", _team_type_combo),
            ("Minimum Team Size", _team_size_combo),
            (
                tl("setting_client_to_follow")
                if tl("setting_client_to_follow") != "setting_client_to_follow"
                else "Client to follow",
                _follow_combo,
            ),
        ],
        "toggle_speed": [
            (
                tl("setting_speed_multiplier")
                if tl("setting_speed_multiplier") != "setting_speed_multiplier"
                else "Speed multiplier",
                _speed_ctrl,
            ),
        ],
        "toggle_auto_potion": [
            (
                tl("setting_use_potions")
                if tl("setting_use_potions") != "setting_use_potions"
                else "Use potions",
                _make_checkbox("setting_use_potions", "use_potions"),
            ),
            (
                tl("setting_buy_potions")
                if tl("setting_buy_potions") != "setting_buy_potions"
                else "Buy potions",
                _make_checkbox("setting_buy_potions", "buy_potions"),
            ),
        ],
        "toggle_auto_pet": [
            (
                tl("setting_ignore_pet_level_up")
                if tl("setting_ignore_pet_level_up") != "setting_ignore_pet_level_up"
                else "Ignore pet level-up",
                _make_checkbox("setting_ignore_pet_level_up", "ignore_pet_level_up"),
            ),
            (
                tl("setting_only_dance_game")
                if tl("setting_only_dance_game") != "setting_only_dance_game"
                else "Only play dance game",
                _make_checkbox("setting_only_dance_game", "only_play_dance_game"),
            ),
        ],
        "toggle_questing": [
            (
                tl("setting_quest_excluded")
                if tl("setting_quest_excluded") != "setting_quest_excluded"
                else "Exclude from Questing",
                _excl_wrap,
            ),
        ],
        "toggle_combat": [
            (
                tl("setting_kill_minions_first")
                if tl("setting_kill_minions_first") != "setting_kill_minions_first"
                else "Kill minions first",
                _make_checkbox("setting_kill_minions_first", "kill_minions_first"),
            ),
            (
                tl("setting_discard_duplicates")
                if tl("setting_discard_duplicates") != "setting_discard_duplicates"
                else "Discard duplicate cards",
                _make_checkbox("setting_discard_duplicates", "discard_duplicate_cards"),
            ),
            (
                tl("setting_hitter_client")
                if tl("setting_hitter_client") != "setting_hitter_client"
                else "Hitter client",
                _hitter_combo,
            ),
        ],
    }

    # per-client target selector + status mirroring
    _PER_CLIENT_TOGGLES = {
        "toggle_speed",
        "toggle_combat",
        "toggle_dialogue",
        "toggle_sigil",
        "toggle_questing",
        "toggle_auto_pet",
        "toggle_auto_potion",
        "toggle_freecam",
    }
    # status tags (e.g. "CombatStatus") for the per-client toggles, collected
    # while the rows are built below
    _per_client_status_tags: list = []
    # title → {status_tag: "Enabled"/"Disabled"} mirror of each client's state
    _per_client_state: dict = {}

    def _apply_status_to_widget(tag, state):
        w = ctx.widget_tags.get(tag)
        if w is not None and hasattr(w, "setChecked"):
            w.setChecked(state == "Enabled")

    def _repaint_toggles():
        tgt = get_target()
        for tag in _per_client_status_tags:
            if tgt in (None, "All"):
                # ambiguous across clients: light up if any client has it on
                state = (
                    "Enabled"
                    if any(
                        cs.get(tag) == "Enabled" for cs in _per_client_state.values()
                    )
                    else "Disabled"
                )
            else:
                state = _per_client_state.get(tgt, {}).get(tag, "Disabled")
            _apply_status_to_widget(tag, state)
        _speed_spin.blockSignals(True)
        if tgt in (None, "All"):
            _speed_spin.setValue(_default_speed)
        else:
            _speed_spin.setValue(float(_per_client_speed.get(tgt, _default_speed)))
        _speed_spin.blockSignals(False)

    def on_per_client_status(tag, state, title):
        _per_client_state.setdefault(title, {})[tag] = state
        tgt = get_target()
        if tgt == title:
            _apply_status_to_widget(tag, state)
        elif tgt in (None, "All"):
            # "all" shows the aggregate (on if any client has it on), so an
            # incremental per-client push must recompute rather than last-win
            agg = (
                "Enabled"
                if any(cs.get(tag) == "Enabled" for cs in _per_client_state.values())
                else "Disabled"
            )
            _apply_status_to_widget(tag, agg)

    # segmented left-to-right selector matching the dev-utils INDIVIDUAL/ALL bar:
    # one rounded button strip "ALL | P1 | P2 | …" rebuilt with the client count
    # both states keep font-weight 600 so selecting a segment never changes its
    # width (bold↔normal would resize the button and shift the right-aligned
    # bar). padding matches the dev-utils chip exactly.
    def _seg_on_style():
        a = ed.accent_of(ctx)
        return (
            f"QPushButton {{ background: {a}; color: #fff; border: none;"
            f" padding: 4px 14px; font-weight: 600; font-size: 8pt;"
            f" letter-spacing: 1px; }}"
            f"QPushButton:hover {{ background: {a}; }}"
        )

    _seg_off_style = (
        "QPushButton { background: transparent; color: rgba(236,236,236,0.45);"
        " border: none; padding: 4px 14px; font-weight: 600; font-size: 8pt;"
        " letter-spacing: 1px; }"
        "QPushButton:hover { color: rgba(236,236,236,0.85); }"
    )

    def _select_target(title, animate=False):
        prev = _toggle_target[0]
        _toggle_target[0] = title
        for b, t in _target_seg_btns:
            on = t == title
            b.setStyleSheet(_seg_on_style() if on else _seg_off_style)
            b.setChecked(on)
        # slide between client views (dev-utils style): snapshot the outgoing
        # list, repaint the live list for the new client, then slide it in
        if (
            animate
            and prev != title
            and _page_stack.currentIndex() == 0
            and not _page_stack._animating
        ):
            try:
                # slide toward the clicked segment: a client to the right of the
                # current one enters from the right (+1), one to the left (-1)
                order = [t for _b, t in _target_seg_btns]
                old_i = order.index(prev) if prev in order else 0
                new_i = order.index(title) if title in order else 0
                direction = 1 if new_i > old_i else -1
                _snapshot_label.setPixmap(hk_scroll.grab())
                _page_stack.setCurrentIndex(1)
                _repaint_toggles()
                _page_stack.slide_to(0, direction=direction)
                return
            except Exception:
                pass
        _repaint_toggles()

    def _rebuild_target_segments(titles):
        # drop mirror state for clients that no longer exist so "All"
        # aggregation and per-client repaint stay correct after a renumber
        keep = set(titles)
        for _d in (_per_client_state, _per_client_speed):
            for _k in [k for k in _d if k not in keep]:
                del _d[_k]
        for b, _t in _target_seg_btns:
            _target_group.removeButton(b)
            _target_bar_layout.removeWidget(b)
            b.deleteLater()
        _target_seg_btns.clear()
        for i, title in enumerate(titles):
            b = StrokedButton(title.upper())
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=title: _select_target(t, True))
            _target_group.addButton(b, i)
            _target_bar_layout.addWidget(b)
            _target_seg_btns.append((b, title))
        cur = _toggle_target[0] if _toggle_target[0] in titles else "All"
        _select_target(cur)

    _rebuild_target_segments(["All"])

    # hotkey categories
    _multi_client_widgets = []

    _multi_client_cat_name = tl("cat_multi_client")

    for cat_name, actions in _hk_categories:
        cat_label = QLabel(cat_name.upper())

        cat_label.setStyleSheet(_cat_label_style)

        hk_scroll_layout.addWidget(cat_label)

        if cat_name == _multi_client_cat_name:
            _multi_client_widgets.append(cat_label)

        for action_id, display_name, callback, is_toggle, tag_name, icon_svg in actions:
            registry.register(action_id, display_name, cat_name, callback)

            if is_toggle and tag_name and action_id in _PER_CLIENT_TOGGLES:
                _per_client_status_tags.append(f"{tag_name}Status")

            row_widget = _build_hk_row(
                action_id,
                display_name,
                callback,
                is_toggle,
                tag_name,
                icon_svg,
            )

            registry.row_widgets[action_id] = row_widget

            hk_scroll_layout.addWidget(row_widget)

            # sub-rows indented beneath their parent toggle
            for sub_label, sub_ctrl in _sub_rows.get(action_id, []):
                hk_scroll_layout.addWidget(_build_sub_row(sub_label, sub_ctrl))

            if cat_name == _multi_client_cat_name:
                _multi_client_widgets.append(row_widget)

    _apply_team_up_lock(bool(_get_s("use_team_up")))

    def _update_multi_client_state(client_count):

        enabled = client_count > 1

        for w in _multi_client_widgets:
            w.setEnabled(enabled)

            if enabled:
                w.setGraphicsEffect(None)

            else:
                effect = QGraphicsOpacityEffect(w)

                effect.setOpacity(0.35)

                w.setGraphicsEffect(effect)

        # rebuild the per-client target selector from the live client count
        # clients are titled p1..pN, matching the rest of the toggle plumbing.
        titles = ["All"] + [f"p{i}" for i in range(1, max(client_count, 0) + 1)]
        _rebuild_target_segments(titles)

    hk_scroll_layout.addStretch()

    _hk_stretch_index[0] = hk_scroll_layout.count() - 1

    hk_scroll.setWidget(hk_scroll_widget)

    # wrap the toggle list in a slide stack (same widget dev utils uses) so
    # switching the active client animates left/right. page 0 is the live list;
    # page 1 holds a snapshot of the outgoing client during the transition
    _page_stack = AnimatedStackedWidget(duration=180)
    _snapshot_label = QLabel()
    _snapshot_label.setStyleSheet("background: transparent;")
    _snapshot_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    # transient overlay only - geometry is set explicitly by slide_to, so keep
    # the snapshot from influencing the stack's layout size
    _snapshot_label.setSizePolicy(
        QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
    )
    _page_stack.addWidget(hk_scroll)
    _page_stack.addWidget(_snapshot_label)

    hotkeys_layout.addWidget(_page_stack, 1)

    # bottom bar
    hotkeys_layout.addSpacing(10)

    hotkeys_layout.addWidget(ed.hairline())

    hotkeys_layout.addSpacing(8)

    bottom_row = QHBoxLayout()

    bottom_row.setContentsMargins(0, 0, 0, 0)

    bottom_row.setSpacing(6)

    # repo link icons
    for svg_key, tooltip, url in [
        ("license", tl("tooltip_license"), f"{ctx.repo_base}/blob/main/LICENSE"),
        ("readme", tl("tooltip_wiki_hotkeys"), f"{ctx.wiki_base}/Hotkeys"),
        ("source", tl("tooltip_source_code"), ctx.repo_base),
        ("discord", tl("tooltip_discord"), "https://discord.gg/59UrPJwYDm"),
    ]:
        bottom_row.addWidget(repo_icon_btn(ctx, ctx.svgs[svg_key], tooltip, url))

    bottom_row.addStretch()

    def _reset_hotkeys():

        if settings:
            settings.reset_hotkeys()

            hotkeys = settings.get_hotkeys()

            for aid, btn in registry.key_labels.items():
                binding = hotkeys.get(aid)

                if binding:
                    from src.gui.commands import _format_binding

                    btn.setText(
                        _format_binding(binding.get("key"), binding.get("modifiers"))
                    )

                else:
                    btn.setText(tl("unbound"))

                if aid in registry.row_widgets:
                    registry.row_widgets[aid].setVisible(True)

                if aid not in hotkeys:
                    send_queue.put(
                        GUICommand(GUICommandType.RebindHotkey, (aid, None, None))
                    )

            for aid, binding in hotkeys.items():
                if binding:
                    send_queue.put(
                        GUICommand(
                            GUICommandType.RebindHotkey,
                            (aid, binding["key"], binding.get("modifiers", [])),
                        )
                    )

                else:
                    send_queue.put(
                        GUICommand(GUICommandType.RebindHotkey, (aid, None, None))
                    )

    _reset_btn = StrokedButton(tl("reset_defaults"))

    _reset_btn.setStyleSheet(
        "QPushButton {"
        "  background-color: transparent;"
        "  color: rgba(236,236,236,0.55);"
        "  border: 1px solid rgba(255,255,255,0.10);"
        "  border-radius: 6px;"
        "  padding: 4px 14px;"
        "  font-size: 8pt;"
        "  letter-spacing: 0.5px;"
        "}"
        "QPushButton:hover {"
        f"  border-color: {accent};"
        "  color: rgba(236,236,236,0.95);"
        "}"
    )

    _reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    _reset_btn.clicked.connect(_reset_hotkeys)

    bottom_row.addWidget(_reset_btn)

    hotkeys_layout.addLayout(bottom_row)

    static_ids = {aid for _, actions in _hk_categories for aid, *_ in actions}

    _update_multi_client_state(0)

    def _retheme():
        nonlocal _keycap_style
        _keycap_style = _build_keycap_style()
        for btn in registry.key_labels.values():
            btn.setStyleSheet(_keycap_style)
        # refresh the active target segment's accent (matches dev-utils retheme)
        for b, t in _target_seg_btns:
            b.setStyleSheet(_seg_on_style() if t == get_target() else _seg_off_style)

    ctx.exports["hotkeys"] = {
        "add_dynamic_hk_row": _add_dynamic_hk_row,
        "static_ids": static_ids,
        "update_multi_client_state": _update_multi_client_state,
        "on_per_client_status": on_per_client_status,
        "retheme": _retheme,
    }

    registry.add_dynamic_hk_row = _add_dynamic_hk_row

    return tab
