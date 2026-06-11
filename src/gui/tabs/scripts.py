import os


from PyQt6.QtCore import QRect, QRectF, QSize, Qt, QTimer, pyqtSignal

from PyQt6.QtGui import QColor, QPainter, QPainterPath, QRegion

from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)


from src.gui.editorial import StrokedButton
from src.gui.commands import GUICommand, GUICommandType

from src.gui.helpers import (
    add_recent,
    show_recent_menu,
)


class _LineGutter(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor._gutter_width(), 0)

    def paintEvent(self, event):
        self._editor._paint_gutter(event)


class _CodeEditor(QPlainTextEdit):
    _GUTTER_PAD_L = 8  # left of numbers
    _GUTTER_PAD_R = 8  # gap between number and text area
    _V_PAD = 14  # >= corner-mask radius so first/last numbers clear the rounded corners
    _H_PAD = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gutter = _LineGutter(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self._update_gutter_width()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Tab and not event.modifiers():
            self.insertPlainText("    ")
        else:
            super().keyPressEvent(event)

    def _gutter_width(self):
        digits = max(2, len(str(max(1, self.blockCount()))))
        return (
            self._GUTTER_PAD_L
            + self.fontMetrics().horizontalAdvance("9") * digits
            + self._GUTTER_PAD_R
        )

    def _update_gutter_width(self, _=None):
        self.setViewportMargins(
            self._gutter_width(), self._V_PAD, self._H_PAD, self._V_PAD
        )

    def _update_gutter(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        gw = self._gutter_width()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), gw, cr.height()))
        # clip gutter to the editor's left rounded corners (radius matches stylesheet)
        radius = 12
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(0, 0, gw + radius * 2, self._gutter.height()), radius, radius
        )
        self._gutter.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _paint_gutter(self, event):
        painter = QPainter(self._gutter)

        # same background as the text area so gutter and editor read as one card
        painter.fillRect(event.rect(), self.palette().base().color())

        # subtle right-edge separator
        painter.setPen(QColor(255, 255, 255, 18))
        painter.drawLine(
            self._gutter.width() - 1,
            event.rect().top(),
            self._gutter.width() - 1,
            event.rect().bottom(),
        )

        num_color = QColor(236, 236, 236, 140)
        block = self.firstVisibleBlock()
        num = block.blockNumber()

        # gutter font: slightly smaller than the editor font so digits fully fit
        # within the row height without bottom-cropping
        gutter_font = self.font()
        if gutter_font.pointSizeF() > 0:
            gutter_font.setPointSizeF(gutter_font.pointSizeF() * 0.85)
        else:
            gutter_font.setPixelSize(max(1, int(gutter_font.pixelSize() * 0.85)))
        painter.setFont(gutter_font)
        line_h = self.fontMetrics().height()

        # block coords are in viewport space; shift to gutter (editor) space
        vp_y = self.viewport().pos().y()
        top = (
            round(
                self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
            )
            + vp_y
            - 2
        )

        while block.isValid() and top <= event.rect().bottom():
            block_h = round(self.blockBoundingRect(block).height())
            if block.isVisible() and top + block_h >= event.rect().top():
                painter.setPen(num_color)
                painter.drawText(
                    self._GUTTER_PAD_L,
                    top,
                    self._gutter.width() - self._GUTTER_PAD_L - self._GUTTER_PAD_R,
                    line_h,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    str(num + 1),
                )
            block = block.next()
            top += block_h
            num += 1


class BotEditorTabs(QWidget):
    textChanged = pyqtSignal()
    tab_activated = pyqtSignal(int)  # current slot_id after a switch
    tab_closed = pyqtSignal(int)  # slot_id of tab just closed
    request_run = pyqtSignal(int)  # slot_id (right-click → Run This Tab)
    request_kill = pyqtSignal(int)  # slot_id

    def __init__(self, parent=None, editor_style: str = ""):
        super().__init__(parent)
        self._editor_style = editor_style
        self._tabs = []  # list of {"slot_id": int, "title": str, "editor": _CodeEditor}
        self._slot_counter = 0
        self._running_slots = set()

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # tab strip
        self._tab_bar = QTabBar()
        self._tab_bar.setTabsClosable(True)
        self._tab_bar.setMovable(True)
        self._tab_bar.setExpanding(False)
        self._tab_bar.setUsesScrollButtons(True)
        self._tab_bar.tabCloseRequested.connect(self._on_close_tab)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        self._tab_bar.tabBarDoubleClicked.connect(self._on_double_click)
        self._tab_bar.tabMoved.connect(self._on_tab_moved)
        self._tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tab_bar.customContextMenuRequested.connect(self._on_context_menu)

        # "+" button shown to the right of the tab bar
        new_btn = QPushButton("+")
        new_btn.setFixedSize(28, 24)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setToolTip("New script tab")
        new_btn.clicked.connect(lambda: self.new_tab())

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(2)
        tab_row.addWidget(self._tab_bar, 1)
        tab_row.addWidget(new_btn)
        tab_row_wrap = QWidget()
        tab_row_wrap.setLayout(tab_row)
        v.addWidget(tab_row_wrap)

        self._stack = QStackedWidget()
        v.addWidget(self._stack, 1)

    # tab management

    def _make_editor(self) -> "_CodeEditor":
        from src.gui.highlighter import LuaSyntaxHighlighter

        ed = _CodeEditor()
        ed.setObjectName("script_editor")
        if self._editor_style:
            ed.setStyleSheet(self._editor_style)
        ed.setFrameShape(QFrame.Shape.NoFrame)
        ed._highlighter = LuaSyntaxHighlighter(ed.document())
        ed.textChanged.connect(self.textChanged.emit)
        return ed

    def _next_default_title(self) -> str:
        taken = {t["title"] for t in self._tabs}
        i = 1
        while f"untitled {i}" in taken:
            i += 1
        return f"untitled {i}"

    def new_tab(
        self, title: str | None = None, content: str = "", activate: bool = True
    ) -> int:
        slot_id = self._slot_counter
        self._slot_counter += 1
        if not title:
            title = self._next_default_title()

        editor = self._make_editor()
        editor.setPlainText(content)

        self._tabs.append({"slot_id": slot_id, "title": title, "editor": editor})
        self._stack.addWidget(editor)
        idx = self._tab_bar.addTab(self._tab_display(title, slot_id))
        self._tab_bar.setTabToolTip(idx, f"slot {slot_id}")
        if activate:
            self._tab_bar.setCurrentIndex(idx)
        return slot_id

    def _on_close_tab(self, idx: int):
        if len(self._tabs) <= 1:
            return  # always keep at least one
        if not (0 <= idx < len(self._tabs)):
            return
        t = self._tabs.pop(idx)
        closed_slot = t["slot_id"]
        self._running_slots.discard(closed_slot)
        self._stack.removeWidget(t["editor"])
        t["editor"].deleteLater()
        self._tab_bar.removeTab(idx)
        # tell the parent so it can KillBot for this slot if it was running
        self.tab_closed.emit(closed_slot)

    def _on_tab_changed(self, idx: int):
        if 0 <= idx < len(self._tabs):
            self._stack.setCurrentWidget(self._tabs[idx]["editor"])
            self.tab_activated.emit(self._tabs[idx]["slot_id"])
            # re-emit textChanged so any meta/footer listener refreshes
            self.textChanged.emit()

    def _on_tab_moved(self, from_idx: int, to_idx: int):
        # user dragged a tab to a new position. keep self._tabs in sync
        # with the tab bar so index-based lookups (close/rename/current
        # editor) stay correct. the stacked widget's internal order is
        # irrelevant because we always switch by reference (setCurrentWidget)
        # not by index, so we don't need to reorder the stack
        if not (0 <= from_idx < len(self._tabs)) or not (0 <= to_idx < len(self._tabs)):
            return
        if from_idx == to_idx:
            return
        t = self._tabs.pop(from_idx)
        self._tabs.insert(to_idx, t)
        # order is part of the persisted state; trigger the debounced save
        self.textChanged.emit()

    def _on_double_click(self, idx: int):
        if not (0 <= idx < len(self._tabs)):
            return
        current = self._tabs[idx]["title"]
        new_title, ok = QInputDialog.getText(self, "Rename tab", "Title:", text=current)
        if ok:
            new_title = new_title.strip() or current
            if new_title != current:
                self._tabs[idx]["title"] = new_title
                self._tab_bar.setTabText(
                    idx, self._tab_display(new_title, self._tabs[idx]["slot_id"])
                )
                self.textChanged.emit()  # persists the new title

    def _on_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu

        idx = self._tab_bar.tabAt(pos)
        if idx < 0 or idx >= len(self._tabs):
            return
        slot_id = self._tabs[idx]["slot_id"]
        is_running = slot_id in self._running_slots

        menu = QMenu(self)
        run_act = menu.addAction(
            "Stop this script" if is_running else "Run this script"
        )
        rename_act = menu.addAction("Rename…")
        menu.addSeparator()
        close_act = menu.addAction("Close tab")
        if len(self._tabs) <= 1:
            close_act.setEnabled(False)

        chosen = menu.exec(self._tab_bar.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is run_act:
            (self.request_kill if is_running else self.request_run).emit(slot_id)
        elif chosen is rename_act:
            self._on_double_click(idx)
        elif chosen is close_act:
            self._on_close_tab(idx)

    # display

    def _tab_display(self, title: str, slot_id: int) -> str:
        return f"● {title}" if slot_id in self._running_slots else title

    def _refresh_tab_titles(self):
        for i, t in enumerate(self._tabs):
            self._tab_bar.setTabText(i, self._tab_display(t["title"], t["slot_id"]))

    def set_slot_running(self, slot_id: int, running: bool):
        before = slot_id in self._running_slots
        if running:
            self._running_slots.add(slot_id)
        else:
            self._running_slots.discard(slot_id)
        if before != running:
            self._refresh_tab_titles()

    def is_slot_running(self, slot_id: int) -> bool:
        return slot_id in self._running_slots

    def has_any_running(self) -> bool:
        return bool(self._running_slots)

    def running_slots(self) -> list[int]:
        return list(self._running_slots)

    # active-tab accessors (duck-types a single editor)

    def current_editor(self):
        idx = self._tab_bar.currentIndex()
        if 0 <= idx < len(self._tabs):
            return self._tabs[idx]["editor"]
        return None

    def current_slot_id(self) -> int:
        idx = self._tab_bar.currentIndex()
        if 0 <= idx < len(self._tabs):
            return self._tabs[idx]["slot_id"]
        return 0

    def current_title(self) -> str:
        idx = self._tab_bar.currentIndex()
        if 0 <= idx < len(self._tabs):
            return self._tabs[idx]["title"]
        return ""

    def get_content_for_slot(self, slot_id: int) -> str | None:
        for t in self._tabs:
            if t["slot_id"] == slot_id:
                return t["editor"].toPlainText()
        return None

    def rename_current_tab(self, new_title: str):
        new_title = (new_title or "").strip()
        if not new_title:
            return
        idx = self._tab_bar.currentIndex()
        if 0 <= idx < len(self._tabs):
            self._tabs[idx]["title"] = new_title
            self._tab_bar.setTabText(
                idx, self._tab_display(new_title, self._tabs[idx]["slot_id"])
            )

    def toPlainText(self) -> str:
        ed = self.current_editor()
        return ed.toPlainText() if ed else ""

    def setPlainText(self, text: str):
        ed = self.current_editor()
        if ed:
            ed.setPlainText(text)

    def document(self):
        ed = self.current_editor()
        return ed.document() if ed else None

    # persistence

    def serialize(self) -> list[dict]:
        return [
            {"title": t["title"], "content": t["editor"].toPlainText()}
            for t in self._tabs
        ]

    def restore(self, entries: list[dict]):
        # wipe existing tabs
        for t in list(self._tabs):
            self._stack.removeWidget(t["editor"])
            t["editor"].deleteLater()
        self._tabs.clear()
        self._running_slots.clear()
        # removeTab decreases indices; iterate from the end
        while self._tab_bar.count() > 0:
            self._tab_bar.removeTab(self._tab_bar.count() - 1)
        self._slot_counter = 0

        if not entries:
            self.new_tab()
            return
        for entry in entries:
            self.new_tab(
                title=entry.get("title") or None,
                content=entry.get("content") or "",
                activate=False,
            )
        self._tab_bar.setCurrentIndex(0)


def _make_toggle_btn(ctx, play_tooltip, kill_tooltip, execute_cb, kill_cb, action_id):

    _running = [False]

    btn = StrokedButton()

    btn.setIcon(ctx.titlebar_svg_icon(ctx.svgs["play"], 32))

    btn.setFixedSize(40, 40)

    btn.setStyleSheet(ctx.icon_btn_style)

    btn.setToolTip(play_tooltip)

    btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _toggle():

        if _running[0]:
            kill_cb()

        else:
            execute_cb()

    btn.clicked.connect(_toggle)

    ctx.registry.register(
        action_id, play_tooltip, getattr(ctx, "current_tab_name", ""), _toggle
    )

    ctx.registry.make_bindable(btn, action_id)

    def set_running(running):

        _running[0] = running

        svg = ctx.svgs["kill"] if running else ctx.svgs["play"]

        btn.setIcon(ctx.titlebar_svg_icon(svg, 32))

        btn.setToolTip(kill_tooltip if running else play_tooltip)

    ctx.tracked_toggle_btns.append((btn, _running, 32))

    return btn, set_running


def build_scripts_tab(ctx):

    tab = QWidget()

    layout = QVBoxLayout(tab)

    layout.setContentsMargins(28, 22, 28, 16)

    layout.setSpacing(0)

    # mode switcher (typographic)
    _modes = [
        ("Bot", "Lua scripts that run on the questing bridge."),
        ("Flythrough", "Recorded path navigation, replayed step by step."),
        ("Combat", "Playstyle priority list — pipe-separated card rules."),
    ]

    _mode_btns = []

    def _build_active_style():
        return (
            "QPushButton {"
            "  background: transparent;"
            "  color: rgba(236,236,236,0.95);"
            "  border: none;"
            f"  border-bottom: 2px solid {getattr(ctx, 'btn_color_hex', '#ff557f')};"
            "  padding: 8px 0 6px 0;"
            "  margin: 0 22px 0 0;"
            "  font-size: 9pt;"
            "  font-weight: 700;"
            "  letter-spacing: 2px;"
            "  text-align: left;"
            "}"
        )

    _active_style = _build_active_style()

    _inactive_style = (
        "QPushButton {"
        "  background: transparent;"
        "  color: rgba(236,236,236,0.38);"
        "  border: none;"
        "  border-bottom: 2px solid transparent;"
        "  padding: 8px 0 6px 0;"
        "  margin: 0 22px 0 0;"
        "  font-size: 9pt;"
        "  font-weight: 500;"
        "  letter-spacing: 2px;"
        "  text-align: left;"
        "}"
        "QPushButton:hover {"
        "  color: rgba(236,236,236,0.85);"
        "}"
    )

    switcher_row = QHBoxLayout()

    switcher_row.setContentsMargins(0, 0, 0, 0)

    switcher_row.setSpacing(0)

    for label, _ in _modes:
        btn = StrokedButton(label.upper())

        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        btn.setFlat(True)

        btn.setFixedHeight(30)

        btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        _mode_btns.append(btn)

        switcher_row.addWidget(btn)

    switcher_row.addStretch()

    layout.addLayout(switcher_row)

    layout.addSpacing(14)

    # mode subtitle
    subtitle = QLabel("")

    subtitle.setStyleSheet(
        "color: rgba(236,236,236,0.55); font-size: 9pt; font-style: italic;"
    )

    subtitle.setWordWrap(True)

    layout.addWidget(subtitle)

    layout.addSpacing(18)

    # editor stack
    editor_stack = QStackedWidget()

    _editor_card_style = (
        "QPlainTextEdit#script_editor {"
        "  border-radius: 12px;"
        "  font-family: 'Cascadia Mono', 'Consolas', monospace;"
        "  font-size: 7.5pt;"
        "}"
    )

    def _dress(editor):

        editor.setStyleSheet(_editor_card_style)

        editor.setFrameShape(QFrame.Shape.NoFrame)

    # bot mode now hosts multiple script tabs; each can run independently
    # with its own bot task on the backend
    bot_editor = BotEditorTabs(editor_style=_editor_card_style)
    ctx.widget_tags["bot_creator"] = bot_editor

    flythrough_editor = _CodeEditor()
    flythrough_editor.setObjectName("script_editor")
    _dress(flythrough_editor)
    ctx.widget_tags["flythrough_creator"] = flythrough_editor

    combat_editor = _CodeEditor()
    combat_editor.setObjectName("script_editor")
    _dress(combat_editor)
    ctx.widget_tags["combat_config"] = combat_editor

    # restore last-session content
    import json as _json

    if ctx.settings:
        # bot: new multi-tab format
        bot_blob = ctx.settings.get_setting("editor_bot_tabs")
        bot_restored = False
        if bot_blob:
            try:
                parsed = _json.loads(bot_blob)
                if isinstance(parsed, list) and parsed:
                    bot_editor.restore(parsed)
                    bot_restored = True
            except Exception:
                pass
        if not bot_restored:
            # migration from old single-content key
            legacy = ctx.settings.get_setting("editor_bot_content")
            if legacy:
                bot_editor.restore([{"title": "untitled", "content": legacy}])
            else:
                bot_editor.restore([])  # single empty tab

        ft_saved = ctx.settings.get_setting("editor_flythrough_content")
        if ft_saved:
            flythrough_editor.setPlainText(ft_saved)

        ct_saved = ctx.settings.get_setting("editor_combat_content")
        if ct_saved:
            combat_editor.setPlainText(ct_saved)
    else:
        bot_editor.restore([])

    # debounced save - parented to tab so timers survive the function scope
    def _save_bot_tabs():
        if ctx.settings:
            ctx.settings.set_setting(
                "editor_bot_tabs", _json.dumps(bot_editor.serialize())
            )

    _bot_save_timer = QTimer(tab)
    _bot_save_timer.setSingleShot(True)
    _bot_save_timer.setInterval(800)
    _bot_save_timer.timeout.connect(_save_bot_tabs)
    bot_editor.textChanged.connect(_bot_save_timer.start)

    for _ed, _key in (
        (flythrough_editor, "editor_flythrough_content"),
        (combat_editor, "editor_combat_content"),
    ):
        _t = QTimer(tab)
        _t.setSingleShot(True)
        _t.setInterval(800)
        _t.timeout.connect(
            lambda ed=_ed, key=_key: (
                ctx.settings.set_setting(key, ed.toPlainText())
                if ctx.settings
                else None
            )
        )
        _ed.textChanged.connect(_t.start)

    editor_stack.addWidget(bot_editor)

    editor_stack.addWidget(flythrough_editor)

    editor_stack.addWidget(combat_editor)

    layout.addWidget(editor_stack, 1)

    layout.addSpacing(14)

    # hairline
    hairline = QFrame()

    hairline.setFixedHeight(1)

    hairline.setStyleSheet("background-color: rgba(255,255,255,0.06); border: none;")

    layout.addWidget(hairline)

    layout.addSpacing(8)

    # footer: meta on left, actions on right
    _editors = [bot_editor, flythrough_editor, combat_editor]

    _meta_filename = ["untitled", "untitled", "untitled"]

    meta_label = QLabel("")

    meta_label.setStyleSheet(
        "color: rgba(236,236,236,0.5); font-size: 8pt; letter-spacing: 0.4px;"
    )

    def _update_meta(idx=None):

        i = editor_stack.currentIndex() if idx is None else idx

        text = _editors[i].toPlainText()

        lines = (text.count("\n") + 1) if text else 0

        mode_label = _modes[i][0].upper()

        meta_label.setText(
            f"{mode_label}   ·   {_meta_filename[i]}   ·   {lines} lines"
        )

    for i, ed in enumerate(_editors):
        ed.textChanged.connect(lambda i=i: _update_meta(i))

    btn_stack = QStackedWidget()

    btn_stack.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    btn_stack.setFixedHeight(44)

    def _make_btn_page(btn_widgets):

        page = QWidget()

        row = QHBoxLayout(page)

        row.setContentsMargins(0, 0, 0, 0)

        row.setSpacing(4)

        for w in btn_widgets:
            row.addWidget(w)

        return page

    # -- bot buttons
    def bot_import():

        filepath, _ = QFileDialog.getOpenFileName(
            ctx.window, ctx.tl("import_bot"), "", "Lua/Text Files (*.lua *.txt)"
        )

        if filepath:
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()

                base = os.path.basename(filepath)

                # if the active tab is empty + still has its default title,
                # import in place. otherwise open the file in a new tab so
                # we don't clobber whatever the user was working on
                active_empty_default = (
                    not bot_editor.toPlainText().strip()
                    and bot_editor.current_title().startswith("untitled")
                )
                if active_empty_default:
                    bot_editor.setPlainText(content)
                    bot_editor.rename_current_tab(base)
                else:
                    bot_editor.new_tab(title=base, content=content)

                add_recent("bot", filepath)

                _meta_filename[0] = base

                _update_meta(0)

            except Exception:
                pass

    def bot_export():

        filepath, _ = QFileDialog.getSaveFileName(
            ctx.window,
            ctx.tl("export_bot"),
            "bot.lua",
            "Lua Files (*.lua);;Text Files (*.txt)",
        )

        if filepath:
            try:
                with open(filepath, "w") as f:
                    f.write(bot_editor.toPlainText())

                _meta_filename[0] = os.path.basename(filepath)

                _update_meta(0)

            except Exception:
                pass

    def bot_convert():
        # Translate Deimos DSL (the active tab) into SkyFall Lua and open the
        # result in a new tab. Errors surface verbatim so the user can fix the
        # offending source line.
        from src.deimos import translate, TranslationError

        src = bot_editor.toPlainText()
        if not src.strip():
            return
        try:
            lua = translate(src)
        except TranslationError as exc:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(
                ctx.window, "Convert Deimos to Lua", f"Could not convert:\n\n{exc}"
            )
            return
        title = bot_editor.current_title()
        base = title[:-4] if title.lower().endswith(".txt") else title
        bot_editor.new_tab(title=f"{base} (lua)", content=lua)

    def run_bot_callback():
        # send the active tab's text + slot_id so the backend keeps each
        # script's bot task independent and addressable
        slot_id = bot_editor.current_slot_id()
        ctx.send_queue.put(
            GUICommand(GUICommandType.ExecuteBot, (slot_id, bot_editor.toPlainText()))
        )

    def kill_bot_callback():
        slot_id = bot_editor.current_slot_id()
        ctx.send_queue.put(GUICommand(GUICommandType.KillBot, slot_id))

    bot_toggle_btn, _set_bot_btn_running = _make_toggle_btn(
        ctx,
        ctx.tl("run_bot"),
        ctx.tl("kill_bot"),
        run_bot_callback,
        kill_bot_callback,
        "toggle_bot",
    )

    # Run/Kill button reflects the *active tab*'s state. updated by:
    #   - tab switches (so the button matches the tab you're looking at)
    #   - backend BotSlotStatus updates (when the script you're viewing
    #     actually starts/stops on the backend)
    def _refresh_bot_btn_for_active_tab():
        _set_bot_btn_running(bot_editor.is_slot_running(bot_editor.current_slot_id()))

    bot_editor.tab_activated.connect(lambda _sid: _refresh_bot_btn_for_active_tab())

    # Right-click "Run / Stop this script" on a tab dispatches without
    # making the tab active first
    def _run_specific_tab(slot_id):
        text = bot_editor.get_content_for_slot(slot_id)
        if text is not None:
            ctx.send_queue.put(GUICommand(GUICommandType.ExecuteBot, (slot_id, text)))

    def _kill_specific_tab(slot_id):
        ctx.send_queue.put(GUICommand(GUICommandType.KillBot, slot_id))

    bot_editor.request_run.connect(_run_specific_tab)
    bot_editor.request_kill.connect(_kill_specific_tab)

    # closing a tab should also stop the bot it owns, otherwise a Lua loop
    # would keep running headless with no way to address it from the GUI
    bot_editor.tab_closed.connect(
        lambda sid: ctx.send_queue.put(GUICommand(GUICommandType.KillBot, sid))
    )

    # slot-aware setter exposed to main.py via ctx.exports["bot"]. the
    # single-arg call (slot_id None) is aggregate status ("is any bot
    # running?") and doesn't touch per-tab state, else it'd mislabel the active
    # tab. per-tab indicators come only from BotSlotStatus events with a slot_id
    def set_bot_running(running, slot_id=None):
        if slot_id is None:
            return
        bot_editor.set_slot_running(slot_id, running)
        if slot_id == bot_editor.current_slot_id():
            _set_bot_btn_running(running)

    bot_recent_btn = ctx.registry.action_icon_btn(
        ctx.svgs["recent"], ctx.tl("recent_imports"), lambda: None
    )

    bot_recent_btn.clicked.disconnect()

    bot_recent_btn.clicked.connect(
        lambda: show_recent_menu(ctx, "bot", bot_editor, bot_recent_btn)
    )

    bot_page = _make_btn_page(
        [
            bot_recent_btn,
            ctx.registry.action_icon_btn(
                ctx.svgs["swap"], "Convert Deimos to Lua", bot_convert
            ),
            ctx.registry.action_icon_btn(
                ctx.svgs["import"], ctx.tl("import_bot"), bot_import
            ),
            ctx.registry.action_icon_btn(
                ctx.svgs["export"], ctx.tl("export_bot"), bot_export
            ),
            bot_toggle_btn,
        ]
    )

    btn_stack.addWidget(bot_page)

    # -- flythrough buttons
    def flythrough_import():

        filepath, _ = QFileDialog.getOpenFileName(
            ctx.window, ctx.tl("import_flythrough"), "", "Text Files (*.txt)"
        )

        if filepath:
            try:
                with open(filepath) as f:
                    flythrough_editor.setPlainText(f.read())

                add_recent("flythrough", filepath)

                _meta_filename[1] = os.path.basename(filepath)

                _update_meta(1)

            except Exception:
                pass

    def flythrough_export():

        filepath, _ = QFileDialog.getSaveFileName(
            ctx.window,
            ctx.tl("export_flythrough"),
            "flythrough.txt",
            "Text Files (*.txt)",
        )

        if filepath:
            try:
                with open(filepath, "w") as f:
                    f.write(flythrough_editor.toPlainText())

                _meta_filename[1] = os.path.basename(filepath)

                _update_meta(1)

            except Exception:
                pass

    def execute_flythrough_callback():

        ctx.send_queue.put(
            GUICommand(
                GUICommandType.ExecuteFlythrough, flythrough_editor.toPlainText()
            )
        )

    def kill_flythrough_callback():

        ctx.send_queue.put(GUICommand(GUICommandType.KillFlythrough))

    flythrough_toggle_btn, set_flythrough_running = _make_toggle_btn(
        ctx,
        ctx.tl("execute_flythrough"),
        ctx.tl("kill_flythrough"),
        execute_flythrough_callback,
        kill_flythrough_callback,
        "toggle_flythrough",
    )

    ft_recent_btn = ctx.registry.action_icon_btn(
        ctx.svgs["recent"], ctx.tl("recent_imports"), lambda: None
    )

    ft_recent_btn.clicked.disconnect()

    ft_recent_btn.clicked.connect(
        lambda: show_recent_menu(ctx, "flythrough", flythrough_editor, ft_recent_btn)
    )

    flythrough_page = _make_btn_page(
        [
            ft_recent_btn,
            ctx.registry.action_icon_btn(
                ctx.svgs["import"], ctx.tl("import_flythrough"), flythrough_import
            ),
            ctx.registry.action_icon_btn(
                ctx.svgs["export"], ctx.tl("export_flythrough"), flythrough_export
            ),
            flythrough_toggle_btn,
        ]
    )

    btn_stack.addWidget(flythrough_page)

    # -- combat buttons
    def combat_import():

        filepath, _ = QFileDialog.getOpenFileName(
            ctx.window, ctx.tl("import_playstyle"), "", "Text Files (*.txt)"
        )

        if filepath:
            try:
                with open(filepath) as f:
                    combat_editor.setPlainText(f.read())

                add_recent("combat", filepath)

                _meta_filename[2] = os.path.basename(filepath)

                _update_meta(2)

            except Exception:
                pass

    def combat_export():

        filepath, _ = QFileDialog.getSaveFileName(
            ctx.window,
            ctx.tl("export_playstyle"),
            "playstyle.txt",
            "Text Files (*.txt)",
        )

        if filepath:
            try:
                with open(filepath, "w") as f:
                    f.write(combat_editor.toPlainText())

                _meta_filename[2] = os.path.basename(filepath)

                _update_meta(2)

            except Exception:
                pass

    def set_playstyles_callback():

        ctx.send_queue.put(
            GUICommand(GUICommandType.SetPlaystyles, combat_editor.toPlainText())
        )

    combat_recent_btn = ctx.registry.action_icon_btn(
        ctx.svgs["recent"], ctx.tl("recent_imports"), lambda: None
    )

    combat_recent_btn.clicked.disconnect()

    combat_recent_btn.clicked.connect(
        lambda: show_recent_menu(ctx, "combat", combat_editor, combat_recent_btn)
    )

    combat_page = _make_btn_page(
        [
            combat_recent_btn,
            ctx.registry.action_icon_btn(
                ctx.svgs["import"], ctx.tl("import_playstyle"), combat_import
            ),
            ctx.registry.action_icon_btn(
                ctx.svgs["export"], ctx.tl("export_playstyle"), combat_export
            ),
            ctx.registry.action_icon_btn(
                ctx.svgs["refresh"], ctx.tl("set_playstyles"), set_playstyles_callback
            ),
        ]
    )

    btn_stack.addWidget(combat_page)

    footer = QHBoxLayout()

    footer.setContentsMargins(0, 0, 0, 0)

    footer.setSpacing(12)

    footer.addWidget(meta_label)

    footer.addStretch(1)

    footer.addWidget(btn_stack)

    layout.addLayout(footer)

    # mode switch logic
    def _switch_mode(index):

        editor_stack.setCurrentIndex(index)

        btn_stack.setCurrentIndex(index)

        for i, btn in enumerate(_mode_btns):
            btn.setStyleSheet(_active_style if i == index else _inactive_style)

        subtitle.setText(_modes[index][1])

        _update_meta(index)

    for i, btn in enumerate(_mode_btns):
        btn.clicked.connect(lambda _checked, idx=i: _switch_mode(idx))

    _switch_mode(0)

    ctx.exports["bot"] = {"set_running": set_bot_running}

    ctx.exports["flythrough"] = {"set_running": set_flythrough_running}

    def _retheme():
        nonlocal _active_style
        _active_style = _build_active_style()
        current = btn_stack.currentIndex() if hasattr(btn_stack, "currentIndex") else 0
        for i, btn in enumerate(_mode_btns):
            btn.setStyleSheet(_active_style if i == current else _inactive_style)

    ctx.exports["scripts"] = {"retheme": _retheme}

    return tab
