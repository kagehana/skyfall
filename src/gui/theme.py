import os
import tempfile

from PyQt6.QtGui import QColor

from PyQt6.QtWidgets import QApplication


from src.gui.helpers import build_shared_svgs


def _check_indicator_url(color: str) -> str:
    safe = color.lstrip("#").lower() or "ffffff"
    path = os.path.join(tempfile.gettempdir(), f"skyfall_check_{safe}.svg")
    if not os.path.exists(path):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
            f'<path d="M3.5 8.4 L6.6 11.4 L12.5 4.8" fill="none" stroke="{color}"'
            ' stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
            "</svg>"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
    return path.replace("\\", "/")


def _contrast_on(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "#ffffff"
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return "#ffffff"
    return "#ffffff" if (r * 299 + g * 587 + b * 114) < 140 * 1000 else "#0a0a0a"


def compute_styles(theme: dict, font: str = None, font_size: int = None) -> dict:

    bg = theme["bg_color"]
    alt = theme["alt_bg"]
    tc = theme["text_color"]
    bc = theme["button_color"]
    tb = theme["titlebar_bg"]
    theme["stroke_color"]

    font_css = (f" font-family: '{font}';" if font else "") + (
        f" font-size: {font_size}pt;" if font_size else ""
    )

    _hex_bg = bg.lstrip("#")
    r, g, b = int(_hex_bg[0:2], 16), int(_hex_bg[2:4], 16), int(_hex_bg[4:6], 16)
    is_dark = (r + g + b) < 384

    border_subtle = "rgba(255,255,255,0.07)" if is_dark else "rgba(0,0,0,0.1)"
    border_focus = "rgba(255,255,255,0.2)" if is_dark else "rgba(0,0,0,0.25)"
    hover_overlay = "rgba(255,255,255,0.06)" if is_dark else "rgba(0,0,0,0.06)"
    selected_overlay = "rgba(255,255,255,0.1)" if is_dark else "rgba(0,0,0,0.1)"
    muted_text = (
        f"rgba({int(tc.lstrip('#')[0:2], 16)},{int(tc.lstrip('#')[2:4], 16)},{int(tc.lstrip('#')[4:6], 16)},0.45)"
        if tc.startswith("#") and len(tc) == 7
        else "rgba(236,236,236,0.45)"
    )

    app_style = (
        f"QWidget {{ background-color: {bg}; color: {tc};{font_css} }} "
        # inputs
        f"QComboBox {{ background-color: {alt}; color: {tc}; padding: 4px 8px; border: 1px solid {border_subtle}; border-radius: 8px; }} "
        f"QComboBox:focus {{ border-color: {border_focus}; }} "
        f"QComboBox::drop-down {{ border: none; width: 20px; padding-right: 4px; }} "
        f"QComboBox QAbstractItemView {{ background-color: {alt}; color: {tc}; border: 1px solid {border_subtle}; border-radius: 6px; selection-background-color: {selected_overlay}; outline: none; }} "
        f"QLineEdit {{ background-color: {alt}; color: {tc}; border: 1px solid {border_subtle}; border-radius: 8px; padding: 4px 8px; }} "
        f"QLineEdit:focus {{ border-color: {border_focus}; }} "
        f"QTextEdit {{ background-color: {alt}; color: {tc}; border: 1px solid {border_subtle}; border-radius: 8px; padding: 2px 4px; }} "
        f"QTextEdit:focus {{ border-color: {border_focus}; }} "
        f"QTextEdit#script_editor {{ font-family: 'Consolas'; font-size: 10pt; }} "
        f"QPlainTextEdit {{ background-color: {alt}; color: {tc}; border: 1px solid {border_subtle}; border-radius: 8px; padding: 2px 4px; }} "
        f"QPlainTextEdit:focus {{ border-color: {border_focus}; }} "
        f"QSpinBox {{ background-color: {alt}; color: {tc}; border: 1px solid {border_subtle}; border-radius: 8px; padding: 3px 6px; }} "
        f"QSpinBox:focus {{ border-color: {border_focus}; }} "
        f"QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }} "
        f"QDoubleSpinBox {{ background-color: {alt}; color: {tc}; border: 1px solid {border_subtle}; border-radius: 8px; padding: 3px 6px; }} "
        f"QDoubleSpinBox:focus {{ border-color: {border_focus}; }} "
        f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }} "
        # lists
        f"QListWidget {{ background-color: {alt}; color: {tc}; border: 1px solid {border_subtle}; border-radius: 8px; outline: none; padding: 2px; }} "
        f"QListWidget::item {{ padding: 3px 6px; border-radius: 5px; }} "
        f"QListWidget::item:selected {{ background-color: {selected_overlay}; color: {tc}; }} "
        f"QListWidget::item:hover {{ background-color: {hover_overlay}; }} "
        # scrollbars
        f"QScrollBar:vertical {{ width: 5px; background: transparent; margin: 0; }} "
        f"QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.18); border-radius: 2px; min-height: 24px; }} "
        f"QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.32); }} "
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }} "
        f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }} "
        f"QScrollBar:horizontal {{ height: 5px; background: transparent; margin: 0; }} "
        f"QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.18); border-radius: 2px; min-width: 24px; }} "
        f"QScrollBar::handle:horizontal:hover {{ background: rgba(255,255,255,0.32); }} "
        f"QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }} "
        f"QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }} "
        # tooltip
        f"QToolTip {{ background-color: {alt}; color: {tc}; border: 1px solid {border_subtle}; border-radius: 6px; padding: 5px 8px; }} "
        # frames / separators
        f"QFrame {{ border: none; }} "
        f"QFrame[frameShape='4'], QFrame[frameShape='5'] {{ background-color: {border_subtle}; max-height: 1px; }} "
        # tab widget
        f"QTabWidget::pane {{ border: none; background: transparent; }} "
        f"QTabWidget::tab-bar {{ alignment: center; }} "
        f"QTabBar {{ background: transparent; border: none; }} "
        f"QTabBar::tab {{ background: transparent; color: {muted_text}; border: none; border-bottom: 2px solid transparent; padding: 6px 18px; margin: 0 1px; }} "
        f"QTabBar::tab:selected {{ color: {tc}; border-bottom: 2px solid {bc}; }} "
        f"QTabBar::tab:hover:!selected {{ color: {tc}; background: {hover_overlay}; border-radius: 6px 6px 0 0; }} "
        # CheckBox
        f"QCheckBox {{ spacing: 6px; }} "
        f"QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {border_focus}; border-radius: 4px; background: {alt}; }} "
        f"QCheckBox::indicator:checked {{ background: {bc}; border-color: {bc}; image: url({_check_indicator_url(_contrast_on(bc))}); }} "
        f"QCheckBox::indicator:hover {{ border-color: {border_focus}; }} "
        # menu
        f"QMenu {{ background-color: {alt}; color: {tc}; border: 1px solid {border_subtle}; border-radius: 8px; padding: 4px; }} "
        f"QMenu::item {{ padding: 5px 24px 5px 12px; border-radius: 5px; }} "
        f"QMenu::item:selected {{ background-color: {selected_overlay}; }} "
        f"QMenu::separator {{ height: 1px; background: {border_subtle}; margin: 4px 8px; }} "
    )

    groupbox_style = (
        f"QGroupBox {{"
        f"  border: none;"
        f"  border-top: 1px solid {border_subtle};"
        f"  border-radius: 0;"
        f"  margin-top: 14px;"
        f"  padding-top: 6px;"
        f"}}"
        f"QGroupBox::title {{"
        f"  subcontrol-origin: margin;"
        f"  subcontrol-position: top left;"
        f"  padding: 0 4px;"
        f"  color: {muted_text};"
        f"  font-size: 8pt;"
        f"  font-weight: 600;"
        f"  letter-spacing: 0.5px;"
        f"  text-transform: uppercase;"
        f"}}"
    )

    _hex = bc.lstrip("#") if isinstance(bc, str) else "ff557f"
    btn_r, btn_g, btn_b = int(_hex[0:2], 16), int(_hex[2:4], 16), int(_hex[4:6], 16)

    btn_style = (
        f"QPushButton {{ "
        f"  background-color: rgb({btn_r},{btn_g},{btn_b});"
        f"  color: #ffffff;"
        f"  border: none;"
        f"  padding: 6px 14px;"
        f"  border-radius: 8px;"
        f"  font-weight: 600;"
        f"}} "
        f"QPushButton:hover {{ "
        f"  background-color: rgb({min(btn_r + 20, 255)},{min(btn_g + 20, 255)},{min(btn_b + 20, 255)});"
        f"}} "
        f"QPushButton:pressed {{ "
        f"  background-color: rgb({max(btn_r - 15, 0)},{max(btn_g - 15, 0)},{max(btn_b - 15, 0)});"
        f"}} "
        f"QPushButton:disabled {{ "
        f"  background-color: rgba({btn_r},{btn_g},{btn_b},0.35);"
        f"  color: rgba(255,255,255,0.4);"
        f"}} "
    )

    icon_btn_style = (
        f"QPushButton {{"
        f"  background-color: transparent;"
        f"  border: none;"
        f"  padding: 4px;"
        f"  border-radius: 7px;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background-color: {hover_overlay};"
        f"}}"
        f"QPushButton:pressed {{"
        f"  background-color: {selected_overlay};"
        f"}}"
    )

    titlebar_style = f"QWidget {{ background-color: {tb}; }} "

    return {
        "app_style": app_style,
        "groupbox_style": groupbox_style,
        "btn_style": btn_style,
        "icon_btn_style": icon_btn_style,
        "titlebar_style": titlebar_style,
    }


def apply_theme(ctx, theme: dict):

    styles = compute_styles(theme, ctx.gui_font, ctx.gui_font_size)

    bg = theme["bg_color"]
    tc = theme["text_color"]
    sc = theme["stroke_color"]
    bc = theme["button_color"]

    _hex = bg.lstrip("#")
    r, g, b = int(_hex[0:2], 16), int(_hex[2:4], 16), int(_hex[4:6], 16)
    is_dark = (r + g + b) < 384

    old_stroke = ctx.stroke_color

    ctx.bg_color = bg
    ctx.text_color = tc
    ctx.stroke_color = sc
    ctx.btn_color_hex = bc
    ctx.theme = "dark" if is_dark else "light"
    ctx.btn_style = styles["btn_style"]
    ctx.icon_btn_style = styles["icon_btn_style"]

    app = QApplication.instance()
    if app:
        app.setStyleSheet(styles["app_style"])

    ctx.window.setStyleSheet(styles["groupbox_style"])
    ctx.titlebar.setStyleSheet(styles["titlebar_style"])

    ctx.title_label.setStyleSheet(
        f"QLabel {{ color: {tc}; font-weight: 600; background: transparent; letter-spacing: 0.5px; }} "
    )

    ctx.svgs = build_shared_svgs(sc)

    ctx.registry.restyle_all(
        styles["btn_style"],
        styles["icon_btn_style"],
        ctx.titlebar_svg_icon,
        old_stroke,
        sc,
    )

    from src.gui.helpers import restyle_tracked_buttons

    restyle_tracked_buttons(
        ctx, styles["icon_btn_style"], ctx.titlebar_svg_icon, old_stroke, sc
    )

    for btn, svg_str in ctx.titlebar_buttons:
        new_svg = svg_str.replace(old_stroke, sc)
        btn.setIcon(ctx.titlebar_svg_icon(new_svg))

    old_pin, old_unpin = ctx.pin_svgs
    new_pin = old_pin.replace(old_stroke, sc)
    new_unpin = old_unpin.replace(old_stroke, sc)
    ctx.pin_svgs = (new_pin, new_unpin)

    pin_btn = ctx.titlebar_buttons[0][0]
    pin_btn.setIcon(ctx.titlebar_svg_icon(new_pin if ctx.is_pinned[0] else new_unpin))

    new_buttons = [(ctx.titlebar_buttons[0][0], new_pin)]
    for btn, svg_str in ctx.titlebar_buttons[1:]:
        new_buttons.append((btn, svg_str.replace(old_stroke, sc)))
    ctx.titlebar_buttons = new_buttons

    updated_labels = []
    for entry in ctx.tracked_svg_labels:
        widget, svg_str, size, mode = entry
        try:
            new_svg = svg_str.replace(old_stroke, sc)
            rendered = ctx.titlebar_svg_icon(new_svg, size)
            if mode == "pixmap":
                widget.setPixmap(rendered.pixmap(size, size))
            else:
                widget.setIcon(rendered)
            updated_labels.append([widget, new_svg, size, mode])
        except RuntimeError:
            pass

    ctx.tracked_svg_labels = updated_labels

    for btn, running_ref, size in ctx.tracked_toggle_btns:
        try:
            svg = ctx.svgs["kill"] if running_ref[0] else ctx.svgs["play"]
            btn.setIcon(ctx.titlebar_svg_icon(svg, size))
        except RuntimeError:
            pass

    for export in ctx.exports.values():
        retheme = export.get("retheme") if isinstance(export, dict) else None
        if retheme:
            try:
                retheme()
            except Exception:
                pass

    duel_circle = getattr(ctx, "duel_circle", None)
    if duel_circle is not None:
        try:
            duel_circle.set_theme_colors(sc, tc, bg, bc)
        except Exception:
            pass

    btn_qcolor = QColor(bc)
    for ts in ctx.toggle_switches:
        ts.set_button_color(btn_qcolor)
