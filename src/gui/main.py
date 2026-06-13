import ctypes

import os

import queue

import sys

import time


from loguru import logger

from PyQt6.QtCore import Qt, QTimer, QSize

from PyQt6.QtGui import QFont, QIcon, QPainter, QPixmap

from PyQt6.QtSvg import QSvgRenderer

from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


from src.gui.actions import ActionRegistry

from src.gui.editorial import StrokedButton
from src.gui.commands import GUICommand, GUICommandType, GUIKeys

from src.gui.helpers import (
    build_shared_svgs,
    copy_callback,
    copy_icon_btn,
    init_recent_imports,
    resource_path,
)

from src.gui.popups import (
    show_entity_list_popup,
    show_gates_list_popup,
    show_ui_tree_popup,
)

from src.gui.tabs import (
    build_dev_utils_tab,
    build_fishing_tab,
    build_hotkeys_tab,
    build_launcher_tab,
    build_scraper_tab,
    build_scripts_tab,
    build_settings_tab,
    build_stats_tab,
)

from src.gui.theme import compute_styles

from src.gui import editorial as ed

from src.gui.widgets import (
    ConsoleTextEdit,
    EspOverlay,
    HighlightOverlay,
    PyQtSink,
)

from src.locale import load_lang


class GUIContext:
    pass


def manage_gui(
    send_queue: queue.Queue,
    recv_queue: queue.Queue,
    theme_dict,
    tool_name,
    tool_version,
    gui_on_top,
    langcode,
    gui_font="Segoe UI",
    gui_font_size=9,
    tool_author="SkyFall-Wizard101",
    settings=None,
):

    tl = load_lang(langcode)

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"skyfall.{tool_name}"
        )

    except Exception:
        pass

    app = QApplication(sys.argv)

    app.setFont(
        QFont(
            gui_font if gui_font else "Segoe UI", gui_font_size if gui_font_size else 9
        )
    )

    _vp_height = 520

    styles = compute_styles(theme_dict, gui_font, gui_font_size)

    _bg_color = theme_dict["bg_color"]

    _text_color = theme_dict["text_color"]

    _stroke_color = theme_dict["stroke_color"]

    _hex_bg = _bg_color.lstrip("#")

    _r, _g, _b = int(_hex_bg[0:2], 16), int(_hex_bg[2:4], 16), int(_hex_bg[4:6], 16)

    _theme = "dark" if (_r + _g + _b) < 384 else "light"

    btn_style = styles["btn_style"]

    icon_btn_style = styles["icon_btn_style"]

    app.setStyleSheet(styles["app_style"])

    window = QMainWindow()

    _window_flags = Qt.WindowType.FramelessWindowHint

    if gui_on_top:
        _window_flags |= Qt.WindowType.WindowStaysOnTopHint

    window.setWindowFlags(_window_flags)

    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

    try:
        import ctypes

        import ctypes.wintypes

        _hwnd = ctypes.wintypes.HWND(int(window.winId()))

        DWMWA_WINDOW_CORNER_PREFERENCE = 33

        DWMWCP_ROUND = ctypes.c_int(2)

        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            _hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(DWMWCP_ROUND),
            ctypes.sizeof(DWMWCP_ROUND),
        )

    except Exception:
        pass

    window.setStyleSheet(styles["groupbox_style"])

    window.setFixedHeight(_vp_height)

    _ico_path = resource_path("skyfall.ico")

    if os.path.exists(_ico_path):
        window.setWindowIcon(QIcon(_ico_path))

    central = QWidget()

    window.setCentralWidget(central)

    main_layout = QVBoxLayout(central)

    main_layout.setContentsMargins(0, 0, 0, 0)

    main_layout.setSpacing(0)

    _tc = _text_color

    _sc = _stroke_color

    svgs = build_shared_svgs(_stroke_color)

    _close_svg = svgs["close"]

    _minimize_svg = svgs["minimize"]

    _pin_svg = svgs["pin"]

    _unpin_svg = svgs["unpin"]

    def _titlebar_svg_icon(svg_str, size=24):

        dpr = window.devicePixelRatioF()

        real_size = int(size * dpr)

        renderer = QSvgRenderer(svg_str.encode())

        pixmap = QPixmap(real_size, real_size)

        pixmap.fill(Qt.GlobalColor.transparent)

        p = QPainter(pixmap)

        renderer.render(p)

        p.end()

        pixmap.setDevicePixelRatio(dpr)

        return QIcon(pixmap)

    titlebar = QWidget()

    titlebar.setFixedHeight(34)

    titlebar.setStyleSheet(styles["titlebar_style"])

    titlebar_layout = QHBoxLayout(titlebar)

    titlebar_layout.setContentsMargins(6, 0, 6, 0)

    titlebar_layout.setSpacing(2)

    titlebar_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    _titlebar_btn_style = (
        "QPushButton {"
        "  background-color: transparent;"
        "  border: none;"
        "  padding: 5px;"
        "  border-radius: 7px;"
        "}"
        "QPushButton:hover {"
        "  background-color: rgba(255,255,255,0.07);"
        "}"
        "QPushButton:pressed {"
        "  background-color: rgba(255,255,255,0.12);"
        "}"
    )

    _close_btn_style = (
        "QPushButton {"
        "  background-color: transparent;"
        "  border: none;"
        "  padding: 5px;"
        "  border-radius: 7px;"
        "}"
        "QPushButton:hover {"
        "  background-color: rgba(220,60,50,0.75);"
        "}"
        "QPushButton:pressed {"
        "  background-color: rgba(180,40,30,0.9);"
        "}"
    )

    _is_pinned = [gui_on_top]

    _pin_icon = _titlebar_svg_icon(_pin_svg)

    _unpin_icon = _titlebar_svg_icon(_unpin_svg)

    pin_btn = StrokedButton()

    pin_btn.setIcon(_pin_icon if _is_pinned[0] else _unpin_icon)

    pin_btn.setToolTip(tl("always_on_top") if _is_pinned[0] else tl("not_on_top"))

    pin_btn.setFixedSize(26, 26)

    pin_btn.setStyleSheet(_titlebar_btn_style)

    pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _toggle_pin():

        _is_pinned[0] = not _is_pinned[0]

        if settings:
            settings.set_setting("on_top", _is_pinned[0])

        if hasattr(ctx, "pin_svgs"):
            _cur_pin, _cur_unpin = ctx.pin_svgs

            pin_btn.setIcon(
                _titlebar_svg_icon(_cur_pin if _is_pinned[0] else _cur_unpin)
            )

        else:
            pin_btn.setIcon(_pin_icon if _is_pinned[0] else _unpin_icon)

        pin_btn.setToolTip(tl("always_on_top") if _is_pinned[0] else tl("not_on_top"))

        import ctypes.wintypes

        _SetWindowPos = ctypes.windll.user32.SetWindowPos

        _SetWindowPos.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]

        _SetWindowPos.restype = ctypes.wintypes.BOOL

        hwnd = ctypes.wintypes.HWND(int(window.winId()))

        HWND_TOPMOST = ctypes.wintypes.HWND(-1)

        HWND_NOTOPMOST = ctypes.wintypes.HWND(-2)

        SWP_NOMOVE = 0x0002

        SWP_NOSIZE = 0x0001

        SWP_NOACTIVATE = 0x0010

        insert_after = HWND_TOPMOST if _is_pinned[0] else HWND_NOTOPMOST

        _SetWindowPos(
            hwnd, insert_after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        )

    pin_btn.clicked.connect(_toggle_pin)

    titlebar_layout.addWidget(pin_btn)

    _status_svg = svgs["locate"]

    status_btn = StrokedButton()

    status_btn.setIcon(_titlebar_svg_icon(_status_svg))

    status_btn.setFixedSize(26, 26)

    status_btn.setStyleSheet(_titlebar_btn_style)

    status_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    status_btn.setToolTip(tl("client") if tl("client") != "client" else "Client status")

    titlebar_layout.addWidget(status_btn)

    titlebar_layout.addStretch()

    title_label = QLabel(f"{tool_name}")

    title_label.setStyleSheet(
        f"QLabel {{ color: {_tc}; font-weight: 600; font-size: 10pt; background: transparent; letter-spacing: 0.5px; }} "
    )

    titlebar_layout.addWidget(title_label)

    titlebar_layout.addStretch()

    minimize_btn = StrokedButton()

    minimize_btn.setIcon(_titlebar_svg_icon(_minimize_svg))

    minimize_btn.setFixedSize(26, 26)

    minimize_btn.setStyleSheet(_titlebar_btn_style)

    minimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    minimize_btn.clicked.connect(window.showMinimized)

    titlebar_layout.addWidget(minimize_btn)

    close_btn = StrokedButton()

    close_btn.setIcon(_titlebar_svg_icon(_close_svg))

    close_btn.setFixedSize(26, 26)

    close_btn.setStyleSheet(_close_btn_style)

    close_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    close_btn.clicked.connect(window.close)

    titlebar_layout.addWidget(close_btn)

    _drag_pos = [None]

    def _titlebar_mouse_press(event):

        if event.button() == Qt.MouseButton.LeftButton:
            _drag_pos[0] = (
                event.globalPosition().toPoint() - window.frameGeometry().topLeft()
            )

    def _titlebar_mouse_move(event):

        if _drag_pos[0] is not None and event.buttons() & Qt.MouseButton.LeftButton:
            window.move(event.globalPosition().toPoint() - _drag_pos[0])

    def _titlebar_mouse_release(event):

        _drag_pos[0] = None

    titlebar.mousePressEvent = _titlebar_mouse_press

    titlebar.mouseMoveEvent = _titlebar_mouse_move

    titlebar.mouseReleaseEvent = _titlebar_mouse_release

    main_layout.addWidget(titlebar)

    content_widget = QWidget()

    content_layout = QVBoxLayout(content_widget)

    content_layout.setContentsMargins(0, 0, 0, 0)

    content_layout.setSpacing(0)

    main_layout.addWidget(content_widget)

    nav_widget = QWidget()

    nav_layout = QHBoxLayout(nav_widget)

    nav_layout.setContentsMargins(0, 0, 0, 0)

    nav_layout.setSpacing(0)

    sidebar = QWidget()

    sidebar.setFixedWidth(58)

    sidebar_layout = QVBoxLayout(sidebar)

    sidebar_layout.setContentsMargins(8, 8, 8, 8)

    sidebar_layout.setSpacing(2)

    content_stack = QStackedWidget()

    tabs = content_stack

    _vsep = QFrame()

    _vsep.setFrameShape(QFrame.Shape.VLine)

    _vsep.setStyleSheet(
        "background-color: rgba(255,255,255,0.06); max-width: 1px; border: none;"
    )

    nav_layout.addWidget(sidebar)

    nav_layout.addWidget(_vsep)

    _stack_wrapper = QWidget()
    _stack_wrapper_layout = QVBoxLayout(_stack_wrapper)
    _stack_wrapper_layout.setContentsMargins(8, 6, 8, 6)
    _stack_wrapper_layout.setSpacing(0)
    _stack_wrapper_layout.addWidget(content_stack)

    nav_layout.addWidget(_stack_wrapper, 1)

    content_layout.addWidget(nav_widget, 1)

    _nav_btn_style = (
        "QPushButton {"
        "  background-color: transparent;"
        "  border: none;"
        "  border-radius: 9px;"
        "  padding: 0;"
        "}"
        "QPushButton:hover:!checked {"
        "  background-color: rgba(255,255,255,0.07);"
        "}"
        "QPushButton:checked {"
        "  background-color: rgba(255,255,255,0.1);"
        "}"
    )

    _nav_btn_group = QButtonGroup()

    _nav_btn_group.setExclusive(True)

    _nav_buttons = []

    def _add_nav_tab(svg_str, tooltip, widget):

        btn = StrokedButton()

        btn.setCheckable(True)

        btn.setFixedSize(38, 38)

        btn.setIcon(_titlebar_svg_icon(svg_str, 22))

        btn.setToolTip(tooltip)

        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        btn.setStyleSheet(_nav_btn_style)

        idx = content_stack.count()

        content_stack.addWidget(widget)

        _nav_btn_group.addButton(btn, idx)

        sidebar_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        btn.clicked.connect(lambda _c, i=idx: content_stack.setCurrentIndex(i))

        _nav_buttons.append(btn)

        ctx.tracked_icon_buttons.append((btn, svg_str, 22))

        return btn

    widget_tags = {}

    registry = ActionRegistry(
        settings, tl, send_queue, btn_style, icon_btn_style, _titlebar_svg_icon
    )

    ctx = GUIContext()

    ctx.send_queue = send_queue

    ctx.widget_tags = widget_tags

    ctx.tl = tl

    ctx.settings = settings

    ctx.window = window

    ctx.app = app

    ctx.titlebar = titlebar

    ctx.stroke_color = _stroke_color

    ctx.text_color = _text_color

    ctx.bg_color = _bg_color

    ctx.theme = _theme

    ctx.btn_style = btn_style

    ctx.btn_color_hex = theme_dict["button_color"]

    ctx.gui_font = gui_font

    ctx.gui_font_size = gui_font_size

    ctx.icon_btn_style = icon_btn_style

    ctx.tool_name = tool_name

    ctx.tool_version = tool_version

    ctx.tool_author = tool_author

    ctx.registry = registry

    ctx.exports = {}

    ctx.svgs = svgs

    ctx.titlebar_svg_icon = _titlebar_svg_icon

    ctx.repo_base = f"https://github.com/{tool_author}/{tool_name}-Wizard101"

    ctx.wiki_base = f"{ctx.repo_base}/wiki"

    ctx.tabs = content_stack

    ctx.tracked_icon_buttons = []

    ctx.tracked_svg_labels = []

    ctx.tracked_toggle_btns = []

    ctx.toggle_switches = []

    ctx.titlebar_buttons = [
        (pin_btn, _pin_svg),
        (status_btn, _status_svg),
        (minimize_btn, _minimize_svg),
        (close_btn, _close_svg),
    ]

    ctx.pin_svgs = (_pin_svg, _unpin_svg)

    ctx.is_pinned = _is_pinned

    ctx.title_label = title_label

    init_recent_imports(settings)

    registry._ctx = ctx

    ctx.current_tab_name = ""

    ctx.current_tab_name = tl("launcher")

    launcher_tab = build_launcher_tab(ctx)

    _add_nav_tab(svgs["play"], tl("launcher"), launcher_tab)

    ctx.current_tab_name = tl("hotkeys")

    hotkeys_tab = build_hotkeys_tab(ctx)

    _add_nav_tab(svgs["keyboard"], tl("hotkeys"), hotkeys_tab)

    ctx.current_tab_name = tl("dev_utils")

    dev_tab = build_dev_utils_tab(ctx)

    _add_nav_tab(svgs["brain"], tl("dev_utils"), dev_tab)

    camera_tab = dev_tab  # camera merged into dev_utils tab

    ctx.current_tab_name = tl("stats")

    stats_tab = build_stats_tab(ctx)

    _add_nav_tab(svgs["gauge"], tl("stats"), stats_tab)

    ctx.current_tab_name = "Fishing"

    fishing_tab = build_fishing_tab(ctx)

    _add_nav_tab(svgs["fish"], "Fishing", fishing_tab)

    ctx.current_tab_name = "Scripts"

    scripts_tab = build_scripts_tab(ctx)

    _add_nav_tab(svgs["pencil"], "Scripts", scripts_tab)

    ctx.current_tab_name = "Scraper"

    scraper_tab = build_scraper_tab(ctx)

    _add_nav_tab(svgs.get("brain", svgs["source"]), "Scraper", scraper_tab)

    ctx.current_tab_name = (
        tl("settings_title") if tl("settings_title") != "settings_title" else "Settings"
    )

    settings_tab = build_settings_tab(ctx)

    _add_nav_tab(
        svgs["gear"],
        tl("settings_title")
        if tl("settings_title") != "settings_title"
        else "Settings",
        settings_tab,
    )

    ctx.current_tab_name = ""

    console_tab = QWidget()

    console_layout = ed.page_layout(console_tab)

    console_layout.addWidget(ed.heading(tl("console")))

    console_layout.addSpacing(6)

    console_layout.addWidget(
        ed.subtitle("Live log stream — timestamps left, levels colored.")
    )

    console_layout.addSpacing(20)

    console_text = ConsoleTextEdit()

    console_text.setReadOnly(True)

    console_text.setStyleSheet(
        "ConsoleTextEdit {"
        "  border-radius: 12px;"
        "  font-family: 'Cascadia Mono', 'Consolas', monospace;"
        "  font-size: 7.6pt;"
        "}"
    )

    console_text.setViewportMargins(14, 12, 14, 12)

    console_text.setFrameShape(QFrame.Shape.NoFrame)

    widget_tags["-CONSOLE-"] = console_text

    console_layout.addWidget(console_text, 1)

    console_psg = PyQtSink(console_text)

    console_layout.addSpacing(12)

    console_layout.addWidget(ed.hairline())

    console_layout.addSpacing(8)

    console_btn_row = QHBoxLayout()

    console_btn_row.setContentsMargins(0, 0, 0, 0)

    console_btn_row.setSpacing(6)

    full_logs_cb = QCheckBox("Full messages")

    full_logs_cb.setToolTip("Show timestamps, module names, and raw log details.")

    full_logs_cb.stateChanged.connect(
        lambda state: console_psg.toggle_show_expanded_logs(
            state == Qt.CheckState.Checked.value
        )
    )

    verbose_combat_cb = QCheckBox("Combat debug")

    verbose_combat_cb.setToolTip("Show raw combat packet details for troubleshooting.")

    _combat_verbose_initial = (
        bool(settings.get_setting("verbose_combat_logs")) if settings else False
    )

    verbose_combat_cb.setChecked(_combat_verbose_initial)

    def _set_combat_verbose(state):

        enabled = state == Qt.CheckState.Checked.value

        if settings:
            settings.set_setting("verbose_combat_logs", enabled)

        send_queue.put(GUICommand(GUICommandType.SetCombatVerboseLogs, enabled))

    verbose_combat_cb.stateChanged.connect(_set_combat_verbose)

    console_btn_row.addWidget(full_logs_cb)

    console_btn_row.addWidget(verbose_combat_cb)

    console_btn_row.addStretch(1)

    clear_console_btn = registry.action_icon_btn(
        svgs["trash"],
        "Clear console",
        lambda: console_psg.clear(),
    )

    console_btn_row.addWidget(clear_console_btn)

    console_btn_row.addWidget(
        registry.action_icon_btn(
            svgs["copy_logs"],
            tl("copy_logs"),
            copy_callback(send_queue, GUIKeys.copy_logs),
        )
    )

    console_layout.addLayout(console_btn_row)

    _add_nav_tab(svgs["chat"], tl("console"), console_tab)

    sidebar_layout.addStretch()

    _nav_buttons[0].setChecked(True)

    # status popover (anchored to the titlebar status button)
    status_popover = QDialog(window)

    status_popover.setWindowFlags(
        Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
    )

    status_popover.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    _pop_outer = QVBoxLayout(status_popover)

    _pop_outer.setContentsMargins(0, 0, 0, 0)

    _pop_outer.setSpacing(0)

    _pop_card = ed.RoundedCard(_bg_color, radius=12, parent=status_popover)

    _pop_outer.addWidget(_pop_card)

    _pop_layout = QVBoxLayout(_pop_card)

    _pop_layout.setContentsMargins(0, 0, 0, 0)

    _pop_layout.setSpacing(0)

    # custom titlebar - hidden in popup mode, shown when detached so the
    # window keeps the SkyFall look instead of falling back to the OS chrome
    _pop_titlebar = QWidget()
    _pop_titlebar.setFixedHeight(28)
    _pop_titlebar.setStyleSheet(styles["titlebar_style"])
    _pop_titlebar_layout = QHBoxLayout(_pop_titlebar)
    _pop_titlebar_layout.setContentsMargins(10, 0, 4, 0)
    _pop_titlebar_layout.setSpacing(2)

    _pop_title_label = QLabel("Client Info")
    _pop_title_label.setStyleSheet(
        f"QLabel {{ color: {_tc}; font-weight: 600; font-size: 9pt;"
        " background: transparent; letter-spacing: 0.4px; }"
    )
    _pop_titlebar_layout.addWidget(_pop_title_label)
    _pop_titlebar_layout.addStretch()

    _pop_close_btn = StrokedButton()
    _pop_close_btn.setIcon(_titlebar_svg_icon(_close_svg, 18))
    _pop_close_btn.setIconSize(QSize(14, 14))
    _pop_close_btn.setFixedSize(22, 22)
    _pop_close_btn.setStyleSheet(_close_btn_style)
    _pop_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    ctx.tracked_icon_buttons.append((_pop_close_btn, _close_svg, 14))
    _pop_titlebar_layout.addWidget(_pop_close_btn)

    _pop_titlebar.hide()

    # drag-to-move on the custom titlebar
    _pop_drag_pos = [None]

    def _pop_tb_press(event):
        if event.button() == Qt.MouseButton.LeftButton:
            _pop_drag_pos[0] = (
                event.globalPosition().toPoint()
                - status_popover.frameGeometry().topLeft()
            )

    def _pop_tb_move(event):
        if _pop_drag_pos[0] is not None and event.buttons() & Qt.MouseButton.LeftButton:
            status_popover.move(event.globalPosition().toPoint() - _pop_drag_pos[0])

    def _pop_tb_release(event):
        _pop_drag_pos[0] = None

    _pop_titlebar.mousePressEvent = _pop_tb_press
    _pop_titlebar.mouseMoveEvent = _pop_tb_move
    _pop_titlebar.mouseReleaseEvent = _pop_tb_release

    _pop_layout.addWidget(_pop_titlebar)

    _pop_body = QWidget()
    _pop_body.setStyleSheet("background: transparent;")
    _pop_body_layout = QVBoxLayout(_pop_body)
    _pop_body_layout.setContentsMargins(16, 14, 16, 14)
    _pop_body_layout.setSpacing(8)
    _pop_layout.addWidget(_pop_body)

    # all subsequent _pop_layout.addX go into the body layout
    _pop_layout = _pop_body_layout

    _eyebrow_row = QHBoxLayout()
    _eyebrow_row.setContentsMargins(0, 0, 0, 0)
    _eyebrow_row.setSpacing(4)
    _eyebrow_row.addWidget(ed.eyebrow(tl("client")), 1)

    detach_btn = StrokedButton()
    detach_btn.setFixedSize(22, 22)
    detach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    detach_btn.setToolTip("Detach (always-on-top)")
    detach_btn.setIconSize(QSize(13, 13))
    detach_btn.setIcon(_titlebar_svg_icon(_unpin_svg, 13))
    detach_btn.setStyleSheet(
        "QPushButton {"
        "  background-color: transparent;"
        "  border: none;"
        "  padding: 0px;"
        "}"
        "QPushButton:hover { background-color: rgba(255,255,255,0.06); border-radius: 4px; }"
        "QPushButton:checked { background-color: rgba(255,255,255,0.10); border-radius: 4px; }"
    )
    detach_btn.setCheckable(True)
    ctx.tracked_icon_buttons.append((detach_btn, _unpin_svg, 13))

    def _toggle_detach():
        detached = detach_btn.isChecked()
        try:
            origin = status_popover.frameGeometry().topLeft()
        except Exception:
            origin = None
        status_popover.hide()
        if detached:
            status_popover.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            _pop_titlebar.show()
            detach_btn.setIcon(_titlebar_svg_icon(_pin_svg, 13))
            detach_btn.setToolTip("Re-attach to status button")
            for i, (btn, _svg, _sz) in enumerate(ctx.tracked_icon_buttons):
                if btn is detach_btn:
                    ctx.tracked_icon_buttons[i] = (detach_btn, _pin_svg, 13)
                    break
        else:
            status_popover.setWindowFlags(
                Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
            )
            _pop_titlebar.hide()
            detach_btn.setIcon(_titlebar_svg_icon(_unpin_svg, 13))
            detach_btn.setToolTip("Detach (always-on-top)")
            for i, (btn, _svg, _sz) in enumerate(ctx.tracked_icon_buttons):
                if btn is detach_btn:
                    ctx.tracked_icon_buttons[i] = (detach_btn, _unpin_svg, 13)
                    break
        # force consistent geometry across the flag change so the window
        # doesn't snap-resize on first interaction
        status_popover.setFixedWidth(320)
        status_popover.adjustSize()
        if origin is not None:
            status_popover.move(origin)
        status_popover.show()

    detach_btn.clicked.connect(_toggle_detach)
    _eyebrow_row.addWidget(detach_btn)

    def _close_pop_to_attached():
        # re-attach (un-detach) when user clicks close on the custom titlebar
        detach_btn.setChecked(False)
        _toggle_detach()
        status_popover.hide()

    _pop_close_btn.clicked.connect(_close_pop_to_attached)

    _pop_layout.addLayout(_eyebrow_row)

    client_label = QLabel("—")

    client_label.setStyleSheet(
        "color: rgba(236,236,236,0.95); font-size: 10pt; font-weight: 600;"
    )

    client_label.setWordWrap(True)

    widget_tags["Title"] = client_label

    _pop_layout.addWidget(client_label)

    _pop_layout.addWidget(ed.hairline())

    def _pop_row(label_text, tag, copy_cb):

        row = QHBoxLayout()

        row.setContentsMargins(0, 0, 0, 0)

        row.setSpacing(8)

        lbl = QLabel(label_text)

        lbl.setStyleSheet(
            f"color: {ed.MUTED_TEXT}; font-size: 7.6pt;"
            f" font-family: 'Cascadia Mono', 'Consolas', monospace;"
        )

        widget_tags[tag] = lbl

        row.addWidget(lbl, 1)

        row.addWidget(copy_icon_btn(ctx, copy_cb))

        return row

    zone_label = QLabel(tl("zone") + ": ")

    zone_label.setStyleSheet(
        f"color: {ed.MUTED_TEXT}; font-size: 7.6pt;"
        f" font-family: 'Cascadia Mono', 'Consolas', monospace;"
    )

    widget_tags["Zone"] = zone_label

    _zone_row = QHBoxLayout()

    _zone_row.setContentsMargins(0, 0, 0, 0)

    _zone_row.setSpacing(8)

    _zone_row.addWidget(zone_label, 1)

    _zone_row.addWidget(
        copy_icon_btn(ctx, copy_callback(send_queue, GUIKeys.copy_zone))
    )

    _pop_layout.addLayout(_zone_row)

    _pop_layout.addLayout(
        _pop_row(
            tl("position_xyz") + " ",
            "xyz",
            copy_callback(send_queue, GUIKeys.copy_position),
        )
    )

    _pop_layout.addLayout(
        _pop_row(
            tl("orientation_pry") + " ",
            "pry",
            copy_callback(send_queue, GUIKeys.copy_rotation),
        )
    )

    _pop_layout.addWidget(ed.hairline())

    _actions_row = QHBoxLayout()

    _actions_row.setContentsMargins(0, 0, 0, 0)

    _actions_row.setSpacing(6)

    _entity_svg = svgs["entity"]

    entities_btn = StrokedButton(tl("available_entities"))

    entities_btn.setIcon(_titlebar_svg_icon(_entity_svg, 14))

    entities_btn.setStyleSheet(
        "QPushButton {"
        "  background-color: transparent;"
        f"  color: {ed.MUTED_TEXT};"
        "  border: 1px solid rgba(255,255,255,0.08);"
        "  border-radius: 8px;"
        "  padding: 5px 10px;"
        "  font-size: 7.6pt;"
        "  text-align: left;"
        "}"
        "QPushButton:hover { color: rgba(236,236,236,0.95);"
        " background-color: rgba(255,255,255,0.04); }"
    )

    entities_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    entities_btn.clicked.connect(copy_callback(send_queue, GUIKeys.copy_entity_list))

    ctx.tracked_icon_buttons.append((entities_btn, _entity_svg, 14))

    _window_svg = svgs["window"]

    paths_btn = StrokedButton(tl("available_paths"))

    paths_btn.setIcon(_titlebar_svg_icon(_window_svg, 14))

    paths_btn.setStyleSheet(entities_btn.styleSheet())

    paths_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    paths_btn.clicked.connect(copy_callback(send_queue, GUIKeys.copy_ui_tree))

    ctx.tracked_icon_buttons.append((paths_btn, _window_svg, 14))

    gates_btn = StrokedButton("Zone Gates")

    gates_btn.setIcon(_titlebar_svg_icon(_window_svg, 14))

    gates_btn.setStyleSheet(entities_btn.styleSheet())

    gates_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    gates_btn.clicked.connect(copy_callback(send_queue, GUIKeys.copy_gates_list))

    ctx.tracked_icon_buttons.append((gates_btn, _window_svg, 14))

    _actions_row.addWidget(entities_btn, 1)

    _actions_row.addWidget(paths_btn, 1)

    _actions_row.addWidget(gates_btn, 1)

    _pop_layout.addLayout(_actions_row)

    status_popover.setFixedWidth(320)

    def _open_status_popover():

        _bottom_left = status_btn.mapToGlobal(status_btn.rect().bottomLeft())

        status_popover.adjustSize()

        _x = _bottom_left.x()

        _y = _bottom_left.y() + 4

        status_popover.move(_x, _y)

        status_popover.show()

    status_btn.clicked.connect(_open_status_popover)

    global console_sink

    console_sink = logger.add(console_psg, colorize=True)

    if not (settings and settings.get_setting("license_accepted")):
        license_dialog = QDialog(window)

        license_dialog.setWindowTitle(tl("license_title"))

        license_dialog.setModal(True)

        license_dialog.setWindowFlags(
            license_dialog.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint
        )

        ld_layout = QVBoxLayout(license_dialog)

        ld_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        license_label = QLabel(f"<b>{tl('license_text')}</b>")

        license_label.setTextFormat(Qt.TextFormat.RichText)

        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        license_label.setWordWrap(True)

        ld_layout.addWidget(license_label)

        ok_btn = StrokedButton(tl("ok"))

        def _accept_license():
            if settings:
                settings.set_setting("license_accepted", True)
            license_dialog.close()

        ok_btn.clicked.connect(_accept_license)

        ld_layout.addWidget(ok_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        license_dialog.adjustSize()

        hint = license_dialog.sizeHint()

        license_dialog.setFixedSize(max(int(hint.width() * 1.5), 350), hint.height())

        license_dialog.show()

    close_accepted = [False]

    def close_event(event):

        if close_accepted[0]:
            event.accept()

            return

        event.ignore()

        send_queue.put(GUICommand(GUICommandType.AttemptedClose))

    window.closeEvent = close_event

    entity_popup_ref = [None]

    gates_popup_ref = [None]

    ui_tree_popup_ref = [None]

    stats = ctx.exports.get("stats", {})

    launcher = ctx.exports.get("launcher", {})

    hotkeys_exports = ctx.exports.get("hotkeys", {})

    dev_utils_exports = ctx.exports.get("dev_utils", {})

    flythrough_exports = ctx.exports.get("flythrough", {})

    bot_exports = ctx.exports.get("bot", {})

    static_ids = hotkeys_exports.get("static_ids", set())

    add_dynamic_hk_row = hotkeys_exports.get("add_dynamic_hk_row")

    if settings and add_dynamic_hk_row:
        for aid, binding in settings.get_hotkeys().items():
            if aid not in static_ids and binding is not None and aid in registry.meta:
                add_dynamic_hk_row(aid)

    highlight_overlay = [None]

    esp_overlay_ref = [None]

    # stats tab exposes a live-combat snapshot ingestor; we route the bot's
    # ``UpdateWindow("live_combat", ...)`` pushes to it. older callers that
    # expected duel_circle/damage-sim plumbing here have all been removed
    # alongside that UI
    _ingest_combat_snapshot = stats.get("ingest_snapshot", lambda s: None)

    _ingest_fishing = ctx.exports.get("fishing", {}).get("ingest", lambda s: None)

    _populate_account_list = launcher.get("populate_account_list", lambda v: None)

    _rebuild_hooked_clients_list = launcher.get(
        "rebuild_hooked_clients_list", lambda: None
    )

    _refresh_account_eligibility = launcher.get(
        "refresh_account_eligibility", lambda v: None
    )

    _hooking_handles = launcher.get("hooking_handles", set())

    _last_hooked_data = launcher.get("last_hooked_data", {})

    account_list = launcher.get("account_list")

    def poll_queue():

        try:
            while True:
                com = recv_queue.get_nowait()

                match com.com_type:
                    case GUICommandType.Close:
                        close_accepted[0] = True

                        window.close()

                        app.quit()

                        return

                    case GUICommandType.CloseFromBackend:
                        send_queue.put(GUICommand(GUICommandType.AttemptedClose))

                    case GUICommandType.UpdateWindow:
                        tag = com.data[0]

                        value = com.data[1]

                        # per-client toggle status carries a 3rd element (the
                        # client title); route it to the hotkeys tab's mirror so
                        # the shared label reflects the selected target only
                        client_title = com.data[2] if len(com.data) > 2 else None

                        _pc_status = (
                            hotkeys_exports.get("on_per_client_status")
                            if (client_title is not None and hotkeys_exports)
                            else None
                        )

                        if _pc_status is not None:
                            _pc_status(tag, value, client_title)

                        elif tag == "live_combat":
                            _ingest_combat_snapshot(value)

                        elif tag == "fishing":
                            _ingest_fishing(value)

                        elif tag == "FlythroughStatus":
                            flythrough_exports.get("set_running", lambda v: None)(
                                value == "Enabled"
                            )

                        elif tag == "BotStatus":
                            bot_exports.get("set_running", lambda v: None)(
                                value == "Enabled"
                            )

                        elif tag == "BotSlotStatus":
                            # ``value`` is (slot_id, "Enabled"/"Disabled")
                            # routed to set_running with the slot_id so the
                            # right tab's indicator flips. falls back to the
                            # single-arg signature for older registrations
                            try:
                                slot_id, state = value
                            except Exception:
                                slot_id, state = None, value
                            fn = bot_exports.get("set_running")
                            if fn is not None:
                                try:
                                    fn(state == "Enabled", slot_id)
                                except TypeError:
                                    fn(state == "Enabled")

                        else:
                            widget = widget_tags.get(tag)

                            if widget is not None:
                                if isinstance(widget, QCheckBox):
                                    widget.setChecked(value == "Enabled")

                                elif isinstance(widget, QLabel) and hasattr(
                                    widget, "setChecked"
                                ):
                                    widget.setChecked(value == "Enabled")

                                elif isinstance(widget, QLabel):
                                    widget.setText(str(value))

                                elif isinstance(widget, QLineEdit):
                                    widget.setText(str(value))

                                elif isinstance(widget, QComboBox):
                                    widget.setCurrentText(str(value))

                                elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
                                    if isinstance(widget, QPlainTextEdit):
                                        widget.setPlainText(str(value))

                                    else:
                                        widget.setPlainText(str(value))

                    case GUICommandType.UpdateWindowValues:
                        tag = com.data[0]

                        values = com.data[1]

                        widget = widget_tags.get(tag)

                        if widget is not None and isinstance(widget, QComboBox):
                            widget.clear()

                            widget.addItems(values)

                    case GUICommandType.UpdateConsole:
                        override = com.data if isinstance(com.data, bool) else None
                        console_psg.toggle_show_expanded_logs(override)
                        full_logs_cb.blockSignals(True)
                        full_logs_cb.setChecked(console_psg.show_expanded_logs)
                        full_logs_cb.blockSignals(False)

                    case GUICommandType.ShowUITreePopup:
                        # reset any previous popup so a re-trigger doesn't
                        # stream into a stale window
                        if ui_tree_popup_ref[0] is not None:
                            try:
                                ui_tree_popup_ref[0].close()
                            except Exception:
                                pass
                        ui_tree_popup_ref[0] = show_ui_tree_popup(
                            window, send_queue, tl=tl
                        )

                    case GUICommandType.UITreeAppendRows:
                        popup = ui_tree_popup_ref[0]
                        if popup is not None and popup.isVisible():
                            popup.append_ui_tree_rows(com.data)
                        else:
                            ui_tree_popup_ref[0] = None

                    case GUICommandType.UITreeDone:
                        popup = ui_tree_popup_ref[0]
                        if popup is not None and popup.isVisible():
                            popup.mark_ui_tree_done()

                    case GUICommandType.ShowEntityListPopup:
                        if entity_popup_ref[0] is not None:
                            try:
                                entity_popup_ref[0].close()

                            except Exception:
                                pass

                        entity_popup_ref[0] = show_entity_list_popup(
                            window,
                            send_queue,
                            widget_tags,
                            tabs,
                            dev_tab,
                            camera_tab,
                            tl=tl,
                        )

                    case GUICommandType.UpdateEntityListData:
                        popup = entity_popup_ref[0]

                        if popup is not None and popup.isVisible():
                            popup.update_entities(com.data)

                        else:
                            entity_popup_ref[0] = None

                    case GUICommandType.ShowGatesListPopup:
                        if gates_popup_ref[0] is not None:
                            try:
                                gates_popup_ref[0].close()
                            except Exception:
                                pass

                        gates_popup_ref[0] = show_gates_list_popup(
                            window, send_queue, tl=tl
                        )

                    case GUICommandType.UpdateGatesListData:
                        popup = gates_popup_ref[0]

                        if popup is not None and popup.isVisible():
                            popup.update_gates(com.data)

                        else:
                            gates_popup_ref[0] = None

                    case GUICommandType.UpdateHighlightBox:
                        if com.data is not None:
                            if highlight_overlay[0] is None:
                                highlight_overlay[0] = HighlightOverlay()

                            game_hwnd, x1, y1, x2, y2 = com.data

                            highlight_overlay[0].update_box(game_hwnd, x1, y1, x2, y2)

                        else:
                            if highlight_overlay[0] is not None:
                                highlight_overlay[0].clear_box()

                    case GUICommandType.UpdateEspBoxes:
                        if com.data is not None:
                            if esp_overlay_ref[0] is None:
                                esp_overlay_ref[0] = EspOverlay()

                            game_hwnd, boxes = com.data

                            esp_overlay_ref[0].update_boxes(game_hwnd, boxes)

                        else:
                            if esp_overlay_ref[0] is not None:
                                esp_overlay_ref[0].hide_all()

                    case GUICommandType.CopyConsole:
                        console_psg.copy()

                    case GUICommandType.ClearConsole:
                        console_psg.clear()

                    case GUICommandType.InvokeAction:
                        action_cb = registry.callbacks.get(com.data)

                        if action_cb:
                            action_cb()

                    case GUICommandType.UpdateAccountList:
                        if com.data is not None:
                            _populate_account_list(com.data)

                    case GUICommandType.UpdateHookedClients:
                        if com.data:
                            managed_accounts = com.data.get("managed_accounts", [])

                            widget_tags["managed_accounts"] = set(managed_accounts)

                            _refresh_account_eligibility(managed_accounts)

                            _hooking_handles.intersection_update(
                                set(com.data.get("unmanaged", []))
                            )

                            _last_hooked_data.clear()

                            _last_hooked_data.update(com.data)

                        else:
                            _last_hooked_data.clear()

                            _hooking_handles.clear()

                        _rebuild_hooked_clients_list()

                        _update_mc = hotkeys_exports.get("update_multi_client_state")

                        hooked_count = len(_last_hooked_data.get("hooked", []))

                        if _update_mc:
                            _update_mc(hooked_count)

                        _update_dev_mass = dev_utils_exports.get("update_mass_state")

                        if _update_dev_mass:
                            _update_dev_mass(hooked_count)

                    case GUICommandType.ClearLaunchCheckboxes:
                        if account_list and not (
                            settings and settings.get_setting("remember_chosen_clients")
                        ):
                            for i in range(account_list.count()):
                                item = account_list.item(i)

                                w = account_list.itemWidget(item)

                                if w:
                                    cb = w.findChild(QCheckBox)

                                    if cb:
                                        cb.setChecked(False)

        except queue.Empty:
            pass

    timer = QTimer()

    timer.timeout.connect(poll_queue)

    timer.start(16)

    window.show()

    window.setFixedWidth(560)

    app.exec()

    if not close_accepted[0]:
        send_queue.put(GUICommand(GUICommandType.AttemptedClose))

        timeout = 30

        start = time.time()

        while time.time() - start < timeout:
            try:
                com = recv_queue.get_nowait()

                if com.com_type == GUICommandType.Close:
                    break

            except queue.Empty:
                pass

            time.sleep(0.1)


console_sink = None
