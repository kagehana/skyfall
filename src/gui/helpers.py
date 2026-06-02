import ctypes

import os

import sys

import webbrowser

from threading import Thread


from PyQt6.QtCore import Qt, QTimer

from PyQt6.QtGui import QIcon, QPainter, QPixmap

from PyQt6.QtSvg import QSvgRenderer

from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


from src.gui.commands import GUICommand, GUICommandType


def resource_path(filename: str) -> str:

    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)

    return filename


def terminate_thread(thread: Thread):

    if not thread.is_alive():
        return

    exc = ctypes.py_object(SystemExit)

    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread.ident), exc)

    if res == 0:
        raise ValueError("Invalid thread ID")

    elif res != 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(thread.ident, None)

        raise SystemError("PyThreadState_SetAsyncExc failed")


def titlebar_svg_icon(window, svg_str, size=24):

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


def svg_icon(svg_str):

    renderer = QSvgRenderer(svg_str.encode())

    pixmap = QPixmap(24, 24)

    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)

    renderer.render(painter)

    painter.end()

    return QIcon(pixmap)


def centered_label(text):

    lbl = QLabel(text)

    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

    return lbl


def repo_icon_btn(ctx, svg_str, tooltip, url):

    btn = QPushButton()

    btn.setToolTip(tooltip)

    btn.setStyleSheet(ctx.icon_btn_style)

    btn.setCursor(Qt.CursorShape.PointingHandCursor)

    btn.setFixedSize(24, 24)

    btn.setIcon(svg_icon(svg_str))

    btn.clicked.connect(lambda: webbrowser.open(url))

    if hasattr(ctx, "tracked_icon_buttons"):
        ctx.tracked_icon_buttons.append((btn, svg_str, 24))

    return btn


def section_group(ctx, title, tooltip_text=None):

    group = QGroupBox()

    group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    layout = QVBoxLayout(group)

    layout.setContentsMargins(6, 2, 6, 2)

    layout.setSpacing(1)

    header = QHBoxLayout()

    header.addWidget(QLabel(f"<b>{title}</b>"))

    header.addStretch()

    if tooltip_text:
        _svg = ctx.svgs["info"]

        info_btn = QPushButton()

        info_btn.setIcon(ctx.titlebar_svg_icon(_svg, 16))

        info_btn.setFixedSize(20, 20)

        info_btn.setStyleSheet(ctx.icon_btn_style)

        info_btn.setToolTip(tooltip_text)

        info_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        if hasattr(ctx, "tracked_icon_buttons"):
            ctx.tracked_icon_buttons.append((info_btn, _svg, 16))

        header.addWidget(info_btn)

    layout.addLayout(header)

    return group, layout


def _icon_btn(ctx, svg_str, tooltip, callback, icon_size, fixed_w, fixed_h):
    btn = QPushButton()
    btn.setIcon(ctx.titlebar_svg_icon(svg_str, icon_size))
    btn.setFixedSize(fixed_w, fixed_h)
    btn.setStyleSheet(ctx.icon_btn_style)
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.clicked.connect(callback)
    if hasattr(ctx, "tracked_icon_buttons"):
        ctx.tracked_icon_buttons.append((btn, svg_str, icon_size))
    return btn


def copy_icon_btn(ctx, callback):
    return _icon_btn(ctx, ctx.svgs["clipboard"], ctx.tl("copy"), callback, 16, 20, 20)


def launcher_icon_btn(ctx, svg_str, tooltip, callback, size=32):
    return _icon_btn(ctx, svg_str, tooltip, callback, 24, size, size)


def launcher_small_icon_btn(ctx, svg_str, tooltip, callback):
    return _icon_btn(ctx, svg_str, tooltip, callback, 16, 22, 22)


def spinning_loader_widget(ctx, size=22):

    lbl = QLabel()

    lbl.setFixedSize(size, size)

    dpr = ctx.window.devicePixelRatioF()

    real = int(size * dpr)

    renderer = QSvgRenderer(ctx.svgs["loader"].encode())

    angle = [0]

    def _tick():

        angle[0] = (angle[0] + 45) % 360

        pm = QPixmap(real, real)

        pm.fill(Qt.GlobalColor.transparent)

        p = QPainter(pm)

        p.translate(real / 2, real / 2)

        p.rotate(angle[0])

        p.translate(-real / 2, -real / 2)

        renderer.render(p)

        p.end()

        pm.setDevicePixelRatio(dpr)

        lbl.setPixmap(pm)

    _tick()

    timer = QTimer(lbl)

    timer.timeout.connect(_tick)

    timer.start(120)

    return lbl


def toggle_callback(send_queue, event_key):

    def cb():

        send_queue.put(GUICommand(GUICommandType.ToggleOption, event_key))

    return cb


def toggle_callback_targeted(send_queue, event_key, get_target):

    def cb():

        send_queue.put(
            GUICommand(GUICommandType.ToggleOption, (event_key, get_target()))
        )

    return cb


def copy_callback(send_queue, event_key):

    def cb():

        send_queue.put(GUICommand(GUICommandType.Copy, event_key))

    return cb


def teleport_callback(send_queue, event_key):

    def cb():

        send_queue.put(GUICommand(GUICommandType.Teleport, event_key))

    return cb


_recent_imports = {"flythrough": [], "bot": [], "combat": []}

_max_recent = 10

_settings_ref = None


def init_recent_imports(settings):

    global _settings_ref

    _settings_ref = settings

    if settings:
        for cat in _recent_imports:
            _recent_imports[cat] = settings.get_recent_imports(cat)


def add_recent(category, filepath):

    recent = _recent_imports[category]

    if filepath in recent:
        recent.remove(filepath)

    recent.insert(0, filepath)

    del recent[_max_recent:]

    if _settings_ref:
        _settings_ref.add_recent_import(category, filepath, _max_recent)


def show_recent_menu(ctx, category, editor, btn):

    recent = _recent_imports[category]

    menu = QMenu(ctx.window)

    if not recent:
        action = menu.addAction(ctx.tl("no_recent_imports"))

        action.setEnabled(False)

    else:
        for path in recent:
            display = os.path.basename(path)

            action = menu.addAction(display)

            action.setToolTip(path)

            action.triggered.connect(
                lambda checked, p=path: _load_recent(p, editor, category)
            )

    menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))


def _load_recent(filepath, editor, category):

    try:
        with open(filepath) as f:
            editor.setPlainText(f.read())

        add_recent(category, filepath)

    except Exception:
        pass


def restyle_tracked_buttons(ctx, icon_btn_style, svg_icon_fn, old_stroke, new_stroke):

    new_tracked = []

    for btn, svg_str, size in ctx.tracked_icon_buttons:
        try:
            new_svg = svg_str.replace(old_stroke, new_stroke)

            btn.setIcon(svg_icon_fn(new_svg, size))

            btn.setStyleSheet(icon_btn_style)

            new_tracked.append((btn, new_svg, size))

        except RuntimeError:
            pass

    ctx.tracked_icon_buttons = new_tracked


def build_shared_svgs(stroke_color):

    from src.gui.icons import build_icons

    return build_icons(stroke_color)
