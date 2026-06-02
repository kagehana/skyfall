import os


from PyQt6.QtCore import Qt

from PyQt6.QtGui import QColor

from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


from src.gui.editorial import StrokedButton
from src.gui.commands import GUICommand, GUICommandType


def build_settings_tab(ctx) -> QWidget:

    from src.gui import editorial as ed
    from src.gui.dialog import (
        _CLIENT_OPTIONS,
        _THEME_KEYS,
        _NoScrollComboBox,
        _NoScrollDoubleSpinBox,
        _NoScrollSpinBox,
        _scan_locales,
    )
    from src.settings import DEFAULT_SETTINGS, DEFAULT_THEME, RESTART_REQUIRED_KEYS
    from PyQt6.QtWidgets import (
        QColorDialog,
    )

    tl = ctx.tl

    current = ctx.settings.get_settings()
    current_theme = ctx.settings.get_theme()
    original_theme = dict(current_theme)
    theme_edits = dict(current_theme)

    tab = QWidget()
    outer = ed.page_layout(tab)
    outer.setSpacing(0)

    # heading
    outer.addWidget(
        ed.heading(
            tl("settings_title")
            if tl("settings_title") != "settings_title"
            else "Settings"
        )
    )
    outer.addSpacing(4)
    outer.addWidget(ed.subtitle("Bot behaviour, theme, and appearance."))
    outer.addSpacing(20)

    # scroll area
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(
        "QScrollArea { background: transparent; border: none; }"
        "QScrollBar:vertical { width: 4px; background: transparent; }"
        "QScrollBar::handle:vertical { background: rgba(255,255,255,0.15);"
        " border-radius: 2px; min-height: 20px; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
    )

    scroll_w = QWidget()
    scroll_w.setStyleSheet("background: transparent;")
    form_layout = QVBoxLayout(scroll_w)
    form_layout.setContentsMargins(0, 0, 12, 0)
    form_layout.setSpacing(0)

    scroll.setWidget(scroll_w)
    outer.addWidget(scroll, 1)

    # helpers
    widgets: dict = {}
    swatches: dict = {}

    _ctrl_style = (
        "background-color: rgba(255,255,255,0.05);"
        " color: rgba(236,236,236,0.9);"
        " border: 1px solid rgba(255,255,255,0.08);"
        " border-radius: 7px;"
        " padding: 4px 8px;"
    )

    def _section(text: str):
        form_layout.addSpacing(14)
        form_layout.addLayout(ed.section_eyebrow_row(text))
        form_layout.addSpacing(10)

    def _sub_section(text: str):
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            "color: rgba(236,236,236,0.28);"
            " font-size: 7.5pt;"
            " font-weight: 600;"
            " letter-spacing: 1.5px;"
        )
        form_layout.addSpacing(12)
        form_layout.addWidget(lbl)
        form_layout.addSpacing(6)

    def _form_row(label_text: str, control: QWidget):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        lbl = ed.meta(label_text)
        lbl.setMinimumWidth(170)
        row.addWidget(lbl)
        row.addWidget(control, 1)
        form_layout.addLayout(row)
        form_layout.addSpacing(8)

    _accented_checkboxes: list[QCheckBox] = []

    def _checkbox_style():
        a = ed.accent_of(ctx)
        return (
            "QCheckBox { spacing: 7px; color: rgba(236,236,236,0.80); }"
            "QCheckBox::indicator { width: 16px; height: 16px;"
            " border: 1px solid rgba(255,255,255,0.18); border-radius: 4px;"
            " background: rgba(255,255,255,0.05); }"
            f"QCheckBox::indicator:checked {{ background: {a}; border-color: {a}; }}"
        )

    def _checkbox_row(key: str, label_key: str):
        cb = QCheckBox(tl(label_key))
        cb.setChecked(bool(current.get(key, DEFAULT_SETTINGS.get(key))))
        cb.setStyleSheet(_checkbox_style())
        form_layout.addWidget(cb)
        form_layout.addSpacing(6)
        widgets[key] = cb
        _accented_checkboxes.append(cb)

    def _client_combo_row(key: str, label_key: str):
        combo = _NoScrollComboBox()
        combo.addItems(_CLIENT_OPTIONS)
        val = current.get(key)
        combo.setCurrentText(str(val) if val else "None")
        combo.setStyleSheet(_ctrl_style)
        _form_row(tl(label_key), combo)
        widgets[key] = combo

    # GENERAL
    _section(
        tl("settings_general")
        if tl("settings_general") != "settings_general"
        else "GENERAL"
    )

    game_path_edit = QLineEdit(str(current.get("game_path", "") or ""))
    game_path_edit.setReadOnly(True)
    game_path_edit.setStyleSheet(_ctrl_style)
    widgets["game_path"] = game_path_edit
    gp_pick = StrokedButton("…")
    gp_pick.setFixedSize(28, 24)
    gp_pick.setCursor(Qt.CursorShape.PointingHandCursor)
    gp_pick.setStyleSheet(
        "QPushButton { background: rgba(255,255,255,0.06); color: rgba(236,236,236,0.8);"
        " border: 1px solid rgba(255,255,255,0.10); border-radius: 6px; font-size: 9pt; }"
        "QPushButton:hover { background: rgba(255,255,255,0.12); }"
    )

    def _pick_game_path():
        path = QFileDialog.getExistingDirectory(tab, tl("game_path"))
        if path:
            game_path_edit.setText(path)

    gp_pick.clicked.connect(_pick_game_path)
    gp_row = QHBoxLayout()
    gp_row.setContentsMargins(0, 0, 0, 0)
    gp_row.setSpacing(6)
    gp_row.addWidget(game_path_edit, 1)
    gp_row.addWidget(gp_pick)
    _form_row(tl("game_path"), _wrap_row(gp_row))

    _checkbox_row("use_potions", "setting_use_potions")
    _checkbox_row("buy_potions", "setting_buy_potions")
    _checkbox_row("use_anti_afk", "setting_use_anti_afk")

    # THEME
    _section(
        tl("settings_theme") if tl("settings_theme") != "settings_theme" else "THEME"
    )

    def _update_swatch(key: str):
        swatches[key].setStyleSheet(
            f"background-color: {theme_edits[key]};"
            f" border: 1px solid rgba(255,255,255,0.12);"
            f" border-radius: 5px;"
        )

    def _make_color_row(key: str, label_key: str):
        swatch = QWidget()
        swatch.setFixedSize(22, 22)
        swatches[key] = swatch
        _update_swatch(key)

        pick_btn = StrokedButton("…")
        pick_btn.setFixedSize(28, 24)
        pick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pick_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.06); color: rgba(236,236,236,0.8);"
            " border: 1px solid rgba(255,255,255,0.10); border-radius: 6px; font-size: 9pt; }"
            "QPushButton:hover { background: rgba(255,255,255,0.12); }"
        )

        def _pick(k=key, lk=label_key):
            color = QColorDialog.getColor(QColor(theme_edits[k]), tab, tl(lk))
            if color.isValid():
                theme_edits[k] = color.name()
                _update_swatch(k)

        pick_btn.clicked.connect(lambda _c, k=key, lk=label_key: _pick(k, lk))

        reset_btn = StrokedButton()
        reset_btn.setIcon(ctx.titlebar_svg_icon(ctx.svgs["reset"], 13))
        reset_btn.setFixedSize(22, 22)
        reset_btn.setStyleSheet(ctx.icon_btn_style)
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setToolTip(tl("reset_to_default").format(DEFAULT_THEME[key]))

        def _reset(k=key):
            theme_edits[k] = DEFAULT_THEME[k]
            _update_swatch(k)

        reset_btn.clicked.connect(lambda _c, k=key: _reset(k))

        row_h = QHBoxLayout()
        row_h.setContentsMargins(0, 0, 0, 0)
        row_h.setSpacing(6)
        row_h.addWidget(swatch)
        row_h.addWidget(pick_btn)
        row_h.addWidget(reset_btn)
        row_h.addStretch()

        lbl = ed.meta(tl(label_key))
        lbl.setMinimumWidth(170)
        full_row = QHBoxLayout()
        full_row.setContentsMargins(0, 0, 0, 0)
        full_row.setSpacing(10)
        full_row.addWidget(lbl)
        full_row.addLayout(row_h)
        form_layout.addLayout(full_row)
        form_layout.addSpacing(8)

    for key, label_key in _THEME_KEYS:
        _make_color_row(key, label_key)

    ie_row = QHBoxLayout()
    ie_row.setContentsMargins(0, 0, 0, 0)
    ie_row.setSpacing(8)

    _btn_minor = (
        "QPushButton { background: rgba(255,255,255,0.05); color: rgba(236,236,236,0.75);"
        " border: 1px solid rgba(255,255,255,0.10); border-radius: 8px;"
        " padding: 5px 12px; font-size: 8.5pt; }"
        "QPushButton:hover { background: rgba(255,255,255,0.10);"
        " color: rgba(236,236,236,0.95); }"
    )

    import_theme_btn = StrokedButton(tl("settings_import_theme"))
    import_theme_btn.setStyleSheet(_btn_minor)
    import_theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _import_theme():
        path, _ = QFileDialog.getOpenFileName(
            tab, tl("settings_import_theme"), "", "JSON files (*.json)"
        )
        if path:
            new_theme = ctx.settings.import_theme(path)
            theme_edits.update(new_theme)
            for k in swatches:
                _update_swatch(k)
            from src.gui.theme import apply_theme

            apply_theme(ctx, new_theme)

    import_theme_btn.clicked.connect(_import_theme)

    export_theme_btn = StrokedButton(tl("settings_export_theme"))
    export_theme_btn.setStyleSheet(_btn_minor)
    export_theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _export_theme():
        path, _ = QFileDialog.getSaveFileName(
            tab, tl("settings_export_theme"), "", "JSON files (*.json)"
        )
        if path:
            ctx.settings.export_theme(path)

    export_theme_btn.clicked.connect(_export_theme)

    ie_row.addWidget(import_theme_btn)
    ie_row.addWidget(export_theme_btn)
    ie_row.addStretch()
    form_layout.addLayout(ie_row)
    form_layout.addSpacing(8)

    # APPEARANCE
    _section(
        tl("settings_appearance")
        if tl("settings_appearance") != "settings_appearance"
        else "APPEARANCE"
    )

    locale_combo = _NoScrollComboBox()
    locale_combo.addItems(_scan_locales())
    locale_combo.setCurrentText(str(current.get("locale", "en")))
    locale_combo.setStyleSheet(_ctrl_style)
    widgets["locale"] = locale_combo

    import_lang_btn = StrokedButton()
    import_lang_btn.setIcon(ctx.titlebar_svg_icon(ctx.svgs["import"], 16))
    import_lang_btn.setFixedSize(24, 24)
    import_lang_btn.setStyleSheet(ctx.icon_btn_style)
    import_lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    import_lang_btn.setToolTip(tl("import_lang_file"))

    def _import_lang():
        import shutil

        path, _ = QFileDialog.getOpenFileName(
            tab, tl("import_lang_title"), "", "Language files (*.lang)"
        )
        if path:
            locale_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "locale"
            )
            dest = os.path.join(locale_dir, os.path.basename(path))
            if not os.path.abspath(dest).startswith(os.path.abspath(locale_dir)):
                return
            shutil.copy2(path, dest)
            code = os.path.splitext(os.path.basename(path))[0]
            codes = _scan_locales()
            locale_combo.clear()
            locale_combo.addItems(codes)
            locale_combo.setCurrentText(code)

    import_lang_btn.clicked.connect(_import_lang)

    locale_row = QHBoxLayout()
    locale_row.setContentsMargins(0, 0, 0, 0)
    locale_row.setSpacing(6)
    locale_row.addWidget(locale_combo, 1)
    locale_row.addWidget(import_lang_btn)
    lbl_locale = ed.meta(tl("setting_locale") + " *")
    lbl_locale.setMinimumWidth(170)
    full_locale = QHBoxLayout()
    full_locale.setContentsMargins(0, 0, 0, 0)
    full_locale.setSpacing(10)
    full_locale.addWidget(lbl_locale)
    full_locale.addLayout(locale_row)
    form_layout.addLayout(full_locale)
    form_layout.addSpacing(8)

    font_edit = QLineEdit(str(current.get("font", "Segoe UI")))
    font_edit.setStyleSheet(_ctrl_style)
    widgets["font"] = font_edit
    font_reset = StrokedButton()
    font_reset.setIcon(ctx.titlebar_svg_icon(ctx.svgs["reset"], 13))
    font_reset.setFixedSize(22, 22)
    font_reset.setStyleSheet(ctx.icon_btn_style)
    font_reset.setCursor(Qt.CursorShape.PointingHandCursor)
    font_reset.setToolTip(tl("reset_to_default").format(DEFAULT_SETTINGS["font"]))
    font_reset.clicked.connect(lambda _c: font_edit.setText(DEFAULT_SETTINGS["font"]))
    font_row = QHBoxLayout()
    font_row.setContentsMargins(0, 0, 0, 0)
    font_row.setSpacing(6)
    font_row.addWidget(font_edit, 1)
    font_row.addWidget(font_reset)
    _form_row(tl("setting_font"), _wrap_row(font_row))

    font_size_spin = _NoScrollSpinBox()
    font_size_spin.setRange(6, 24)
    font_size_spin.setValue(int(current.get("font_size", 9)))
    font_size_spin.setStyleSheet(_ctrl_style)
    widgets["font_size"] = font_size_spin
    fs_reset = StrokedButton()
    fs_reset.setIcon(ctx.titlebar_svg_icon(ctx.svgs["reset"], 13))
    fs_reset.setFixedSize(22, 22)
    fs_reset.setStyleSheet(ctx.icon_btn_style)
    fs_reset.setCursor(Qt.CursorShape.PointingHandCursor)
    fs_reset.setToolTip(tl("reset_to_default").format(DEFAULT_SETTINGS["font_size"]))
    fs_reset.clicked.connect(
        lambda _c: font_size_spin.setValue(DEFAULT_SETTINGS["font_size"])
    )
    fs_row = QHBoxLayout()
    fs_row.setContentsMargins(0, 0, 0, 0)
    fs_row.setSpacing(6)
    fs_row.addWidget(font_size_spin, 1)
    fs_row.addWidget(fs_reset)
    _form_row(tl("setting_font_size"), _wrap_row(fs_row))

    # GAMEPLAY
    _section("GAMEPLAY")

    _sub_section(
        tl("settings_combat")
        if tl("settings_combat") != "settings_combat"
        else "Combat"
    )
    _checkbox_row("kill_minions_first", "setting_kill_minions_first")
    _checkbox_row("automatic_team_based_combat", "setting_auto_team_combat")
    _checkbox_row("discard_duplicate_cards", "setting_discard_duplicates")

    form_layout.addStretch()

    # sticky footer
    outer.addSpacing(12)
    outer.addWidget(ed.hairline())
    outer.addSpacing(10)

    def _restart_lbl_style():
        return f"color: {ed.accent_of(ctx)}; font-style: italic; font-size: 8pt;"

    restart_lbl = QLabel("* " + tl("settings_restart_note"))
    restart_lbl.setStyleSheet(_restart_lbl_style())
    restart_lbl.setVisible(False)
    outer.addWidget(restart_lbl)

    footer_row = QHBoxLayout()
    footer_row.setContentsMargins(0, 0, 0, 0)
    footer_row.setSpacing(8)
    footer_row.addStretch()

    reset_btn = StrokedButton("Reset to defaults")
    reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    reset_btn.setStyleSheet(_btn_minor)

    save_btn = StrokedButton(
        tl("settings_save") if tl("settings_save") != "settings_save" else "Save"
    )
    save_btn.setStyleSheet(ctx.btn_style)
    save_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    footer_row.addWidget(reset_btn)
    footer_row.addWidget(save_btn)
    outer.addLayout(footer_row)

    # logic
    def _collect_values():
        values = {}
        for key, w in widgets.items():
            if isinstance(w, QCheckBox):
                values[key] = w.isChecked()
            elif isinstance(w, _NoScrollDoubleSpinBox):
                values[key] = w.value()
            elif isinstance(w, _NoScrollSpinBox):
                values[key] = w.value()
            elif isinstance(w, _NoScrollComboBox):
                text = w.currentText()
                if key in ("client_to_follow", "client_to_boost", "hitter_client"):
                    values[key] = None if text == "None" else text
                else:
                    values[key] = text
            elif isinstance(w, QLineEdit):
                values[key] = w.text()
        return values

    def _on_save():
        from src.gui.theme import apply_theme
        from PyQt6.QtWidgets import QApplication

        if theme_edits != original_theme:
            ctx.settings.set_theme(theme_edits)
            apply_theme(ctx, theme_edits)
            original_theme.update(theme_edits)

        new_font = font_edit.text()
        new_font_size = font_size_spin.value()
        old_font = current.get("font", "Segoe UI")
        old_font_size = current.get("font_size", 9)
        if new_font != old_font or new_font_size != old_font_size:
            ctx.gui_font = new_font
            ctx.gui_font_size = new_font_size
            from src.gui.theme import compute_styles

            styles = compute_styles(theme_edits, new_font, new_font_size)
            app = QApplication.instance()
            if app:
                app.setStyleSheet(styles["app_style"])

        new_values = _collect_values()
        changed = {}
        for key, new_val in new_values.items():
            old_val = current.get(key, DEFAULT_SETTINGS.get(key))
            if new_val != old_val:
                changed[key] = new_val
        if changed:
            ctx.settings.set_settings(changed)
            current.update(changed)
            ctx.send_queue.put(GUICommand(GUICommandType.UpdateSettings, changed))

        if changed.keys() & RESTART_REQUIRED_KEYS:
            restart_lbl.setVisible(True)
            save_btn.setEnabled(False)
        else:
            restart_lbl.setVisible(False)
            save_btn.setEnabled(True)

    def _on_reset_defaults():
        from src.gui.theme import apply_theme

        # reset all widget values to their defaults
        for key, w in widgets.items():
            default = DEFAULT_SETTINGS.get(key)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(default))
            elif isinstance(w, _NoScrollDoubleSpinBox):
                w.setValue(float(default))
            elif isinstance(w, _NoScrollSpinBox):
                w.setValue(int(default))
            elif isinstance(w, _NoScrollComboBox):
                if key in ("client_to_follow", "client_to_boost", "hitter_client"):
                    w.setCurrentText("None" if default is None else str(default))
                else:
                    w.setCurrentText(str(default) if default is not None else "")
            elif isinstance(w, QLineEdit):
                w.setText(str(default) if default is not None else "")
        # reset theme swatches to defaults (live preview)
        theme_edits.update(DEFAULT_THEME)
        for k in swatches:
            _update_swatch(k)
        apply_theme(ctx, DEFAULT_THEME)
        restart_lbl.setVisible(False)
        save_btn.setEnabled(True)

    save_btn.clicked.connect(_on_save)
    reset_btn.clicked.connect(_on_reset_defaults)

    def _retheme():
        cb_style = _checkbox_style()
        for cb in _accented_checkboxes:
            try:
                cb.setStyleSheet(cb_style)
            except RuntimeError:
                pass
        try:
            restart_lbl.setStyleSheet(_restart_lbl_style())
        except RuntimeError:
            pass

    ctx.exports["settings"] = {"retheme": _retheme}

    return tab


def _wrap_row(layout: QHBoxLayout) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    w.setLayout(layout)
    return w
