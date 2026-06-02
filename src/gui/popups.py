import pyperclip

from PyQt6.QtCore import Qt, QTimer, QSize

from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
)


from src.gui.commands import GUICommand, GUICommandType


def _lua_table_literal(items) -> str:
    parts = []
    for s in items:
        text = str(s).replace("\\", "\\\\").replace("'", "\\'")
        parts.append(f"'{text}'")
    return "{" + ", ".join(parts) + "}"


def show_ui_tree_popup(parent, send_queue, tl=None):
    dialog = QDialog(parent)
    dialog.setWindowTitle(tl("ui_tree") if tl else "UI Tree")
    dialog.resize(700, 500)

    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel(
            tl("ui_tree_hint")
            if tl
            else "Click a row to copy its window path. Right-click for text/options. Hover to highlight in-game."
        )
    )

    status_lbl = QLabel("Loading…")
    layout.addWidget(status_lbl)

    search_input = QLineEdit()
    search_input.setPlaceholderText(tl("search") if tl else "Search")
    layout.addWidget(search_input)

    listbox = QListWidget()
    listbox.setUniformItemSizes(True)
    listbox.setMouseTracking(True)
    listbox.setStyleSheet(
        "QListWidget {"
        " font-family: 'Cascadia Mono', 'Consolas', monospace;"
        " font-size: 9pt;"
        " }"
        "QListWidget::item { padding: 0px; margin: 0px; border: 0px; }"
    )

    # right-aligned 📋 column for rows that have copyable text. a delegate
    # paints the label on the left and the marker flush-right in a fixed
    # gutter so the markers form a clean vertical column regardless of the
    # label's indent depth. also shrinks the row height for density.
    class _UITreeDelegate(QStyledItemDelegate):
        _GUTTER = 22

        def sizeHint(self, option, index):
            base = super().sizeHint(option, index)
            fm = option.fontMetrics
            return QSize(base.width(), fm.height() + 1)

        def paint(self, painter, option, index):
            self.initStyleOption(option, index)
            data = index.data(Qt.ItemDataRole.UserRole) or {}
            has_text = data.get("text") is not None
            text = option.text
            option.text = ""
            widget = option.widget
            style = widget.style() if widget else option.styleObject.style()
            style.drawControl(
                QStyle.ControlElement.CE_ItemViewItem, option, painter, widget
            )
            rect = option.rect
            painter.save()
            painter.setPen(option.palette.text().color())
            painter.setFont(option.font)
            label_rect = rect.adjusted(4, 0, -self._GUTTER, 0)
            painter.drawText(
                label_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            if has_text:
                marker_rect = rect.adjusted(rect.width() - self._GUTTER, 0, -4, 0)
                painter.drawText(
                    marker_rect,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    "📋",
                )
            painter.restore()

    listbox.setItemDelegate(_UITreeDelegate(listbox))
    listbox.setSpacing(0)
    layout.addWidget(listbox)

    _INDENT = "  "
    _state = {"needle": "", "done": False}

    def _row_label(depth, display, has_text):
        return f"{_INDENT * depth}{display}"

    def _row_matches(label_lc, needle):
        return (not needle) or (needle in label_lc)

    def append_rows(rows):
        needle = _state["needle"]
        listbox.setUpdatesEnabled(False)
        for depth, display, path, text in rows:
            label = _row_label(depth, display, text is not None)
            item = QListWidgetItem(label)
            item.setData(
                Qt.ItemDataRole.UserRole,
                {"path": path, "text": text, "label_lc": label.lower()},
            )
            if not _row_matches(label.lower(), needle):
                item.setHidden(True)
            listbox.addItem(item)
        listbox.setUpdatesEnabled(True)
        status_lbl.setText(f"{listbox.count()} nodes loaded…")

    def mark_done():
        _state["done"] = True
        status_lbl.setText(f"{listbox.count()} nodes")
        # hide the status label once loading completes to free vertical space
        QTimer.singleShot(800, status_lbl.hide)

    dialog.append_ui_tree_rows = append_rows
    dialog.mark_ui_tree_done = mark_done

    def _refilter():
        needle = _state["needle"]
        listbox.setUpdatesEnabled(False)
        try:
            for i in range(listbox.count()):
                item = listbox.item(i)
                data = item.data(Qt.ItemDataRole.UserRole) or {}
                label_lc = data.get("label_lc", "")
                item.setHidden(not _row_matches(label_lc, needle))
        finally:
            listbox.setUpdatesEnabled(True)

    _search_timer = QTimer(dialog)
    _search_timer.setSingleShot(True)
    _search_timer.setInterval(120)
    _search_timer.timeout.connect(_refilter)

    def on_search(text):
        _state["needle"] = text.lower()
        _search_timer.start()

    def _clear_highlight():
        send_queue.put(GUICommand(GUICommandType.ClearHighlight))

    def on_hover(item):
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("path"):
                send_queue.put(
                    GUICommand(GUICommandType.HighlightUIWindow, data["path"])
                )

    def on_select(item):
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and data.get("path"):
            pyperclip.copy(_lua_table_literal(data["path"]))
        else:
            pyperclip.copy(item.text())
        _clear_highlight()
        dialog.close()

    def on_context_menu(pos):
        item = listbox.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        menu = QMenu(listbox)
        copy_path = menu.addAction("Copy Path")
        scroll_to = menu.addAction("Scroll To")
        copy_text_action = None
        if data.get("text") is not None:
            preview = data["text"][:40] + ("…" if len(data["text"]) > 40 else "")
            copy_text_action = menu.addAction(f"Copy Text  ({preview})")
        action = menu.exec(listbox.mapToGlobal(pos))
        if action == copy_path and data.get("path"):
            pyperclip.copy(_lua_table_literal(data["path"]))
        elif action == scroll_to:
            # clear filter, then re-center the unfiltered list on this row so
            # its parents/siblings become visible for context
            search_input.blockSignals(True)
            search_input.clear()
            search_input.blockSignals(False)
            _state["needle"] = ""
            _refilter()
            row = listbox.row(item)
            if row >= 0:
                listbox.setCurrentRow(row)
                listbox.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)
        elif action is not None and action == copy_text_action:
            pyperclip.copy(data["text"])

    listbox.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    listbox.customContextMenuRequested.connect(on_context_menu)
    search_input.textChanged.connect(on_search)
    listbox.itemEntered.connect(on_hover)
    listbox.itemClicked.connect(on_select)

    orig_leave = listbox.leaveEvent

    def _leave_event(event):
        _clear_highlight()
        orig_leave(event)

    listbox.leaveEvent = _leave_event

    orig_close = dialog.closeEvent

    def _close_event(event):
        _clear_highlight()
        # if the walk is still streaming rows when the user closes the popup,
        # tell the bot side to cancel - no point burning memory reads for a
        # view that's gone
        if not _state["done"]:
            send_queue.put(GUICommand(GUICommandType.CancelUITreeDump))
        orig_close(event)

    dialog.closeEvent = _close_event

    close_btn = QPushButton(tl("close") if tl else "Close")
    close_btn.clicked.connect(dialog.close)
    layout.addWidget(close_btn)

    dialog.show()
    return dialog


def show_entity_list_popup(
    parent, send_queue, widget_tags, tabs, dev_tab, camera_tab, tl=None
):

    dialog = QDialog(parent)

    dialog.setWindowTitle(tl("entity_list") if tl else "Entity List")

    dialog.resize(450, 400)

    layout = QVBoxLayout(dialog)

    layout.addWidget(
        QLabel(
            tl("entity_list_hint")
            if tl
            else "Click to copy. Right-click for TP / Camera options."
        )
    )

    search_input = QLineEdit()

    search_input.setPlaceholderText(tl("search") if tl else "Search")

    layout.addWidget(search_input)

    listbox = QListWidget()

    listbox.setMouseTracking(True)

    listbox.setUniformItemSizes(True)

    listbox.setStyleSheet(
        "QListWidget {"
        " font-family: 'Cascadia Mono', 'Consolas', monospace;"
        " font-size: 9pt;"
        " }"
    )

    layout.addWidget(listbox)

    all_entities = []

    def _populate(entries):

        # reuse existing rows instead of clear()+rebuild - the entity stream
        # refreshes frequently, so reallocating every item per tick is wasteful
        # and causes flicker. only allocate when the list grows.
        listbox.setUpdatesEnabled(False)

        for i, entry in enumerate(entries):
            data = {
                "x": entry["x"],
                "y": entry["y"],
                "z": entry["z"],
                "height": entry.get("height", 170.0),
                "gid": entry.get("gid", 0),
                "distance": entry.get("distance", 0.0),
            }

            if i < listbox.count():
                item = listbox.item(i)

                item.setText(entry["display"])

                item.setData(Qt.ItemDataRole.UserRole, data)

            else:
                item = QListWidgetItem(entry["display"])

                item.setData(Qt.ItemDataRole.UserRole, data)

                listbox.addItem(item)

        while listbox.count() > len(entries):
            listbox.takeItem(listbox.count() - 1)

        listbox.setUpdatesEnabled(True)

    def update_entities(entity_data):

        nonlocal all_entities

        all_entities = entity_data

        search_text = search_input.text()

        if search_text:
            filtered = [
                e for e in all_entities if search_text.lower() in e["display"].lower()
            ]

            _populate(filtered)

        else:
            _populate(all_entities)

    dialog.update_entities = update_entities

    def on_search(text):

        if text:
            filtered = [e for e in all_entities if text.lower() in e["display"].lower()]

            _populate(filtered)

        else:
            _populate(all_entities)

    def on_hover(item):

        if item:
            data = item.data(Qt.ItemDataRole.UserRole)

            if data:
                send_queue.put(
                    GUICommand(
                        GUICommandType.HighlightEntity,
                        (data["x"], data["y"], data["z"], data["height"]),
                    )
                )

    def on_select(item):

        if item:
            pyperclip.copy(item.text())

            send_queue.put(GUICommand(GUICommandType.ClearHighlight))

            dialog.close()

    def _clear_highlight():

        send_queue.put(GUICommand(GUICommandType.ClearHighlight))

    listbox.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def on_context_menu(pos):

        item = listbox.itemAt(pos)

        if not item:
            return

        data = item.data(Qt.ItemDataRole.UserRole)

        if not data:
            return

        gid_str = str(data.get("gid", ""))

        menu = QMenu(listbox)

        tp_action = menu.addAction(tl("tp_to_entity") if tl else "Teleport to Entity")

        tp_near_action = menu.addAction("Teleport Near")

        anchor_action = menu.addAction(
            tl("anchor_cam_to_entity") if tl else "Anchor Camera to Entity"
        )

        copy_coords_action = menu.addAction("Copy Coordinates")

        copy_gid_action = menu.addAction("Copy Game ID")

        action = menu.exec(listbox.mapToGlobal(pos))

        if action == copy_coords_action:
            pyperclip.copy(f"{data['x']}, {data['y']}, {data['z']}")

        elif action == copy_gid_action:
            pyperclip.copy(gid_str)

        elif action == tp_action:
            send_queue.put(
                GUICommand(GUICommandType.EntityTeleport, {"name": "", "gid": gid_str})
            )

            send_queue.put(GUICommand(GUICommandType.ClearHighlight))

            dialog.close()

        elif action == tp_near_action:
            send_queue.put(
                GUICommand(GUICommandType.EntityTeleportNear, {"gid": gid_str})
            )

            send_queue.put(GUICommand(GUICommandType.ClearHighlight))

            dialog.close()

        elif action == anchor_action:
            gid_widget = widget_tags.get("CamEntityGIDInput")

            if gid_widget:
                gid_widget.setText(gid_str)

            tabs.setCurrentWidget(camera_tab)

            send_queue.put(GUICommand(GUICommandType.ClearHighlight))

            dialog.close()

    listbox.customContextMenuRequested.connect(on_context_menu)

    search_input.textChanged.connect(on_search)

    listbox.itemEntered.connect(on_hover)

    listbox.itemClicked.connect(on_select)

    orig_leave = listbox.leaveEvent

    def _leave_event(event):

        _clear_highlight()

        orig_leave(event)

    listbox.leaveEvent = _leave_event

    orig_close = dialog.closeEvent

    def _close_event(event):

        _clear_highlight()

        send_queue.put(GUICommand(GUICommandType.StopEntityStream))

        orig_close(event)

    dialog.closeEvent = _close_event

    close_btn = QPushButton(tl("close") if tl else "Close")

    close_btn.clicked.connect(dialog.close)

    layout.addWidget(close_btn)

    send_queue.put(GUICommand(GUICommandType.StartEntityStream))

    dialog.show()

    return dialog


def show_gates_list_popup(parent, send_queue, tl=None):

    dialog = QDialog(parent)

    dialog.setWindowTitle("Zone Gates")

    dialog.resize(520, 420)

    layout = QVBoxLayout(dialog)

    layout.addWidget(
        QLabel("Click to copy name. Right-click for Teleport / Copy options.")
    )

    search_input = QLineEdit()

    search_input.setPlaceholderText(tl("search") if tl else "Search")

    layout.addWidget(search_input)

    listbox = QListWidget()

    listbox.setUniformItemSizes(True)

    listbox.setStyleSheet(
        "QListWidget {"
        " font-family: 'Cascadia Mono', 'Consolas', monospace;"
        " font-size: 9pt;"
        " }"
    )

    layout.addWidget(listbox)

    all_gates = []

    def _format(entry, kind_w):
        kind = entry.get("kind", "?")
        # pad the bracketed kind to a fixed column so names line up across
        # rows regardless of whether the tag is [arrival], [exit], [other], …
        bracket = f"[{kind}]".ljust(kind_w + 2)
        partner = entry.get("partner")
        partner_str = f" → {partner}" if partner else ""
        return (
            f"{bracket} {entry['name']}{partner_str}  "
            f"({entry['x']}, {entry['y']}, {entry['z']})  "
            f"yaw {entry.get('yaw_deg', 0.0)}°"
        )

    def _populate(entries):

        # reuse existing rows instead of clear()+rebuild so streamed gate
        # refreshes don't reallocate every item or flicker
        listbox.setUpdatesEnabled(False)

        kind_w = max((len(e.get("kind", "?")) for e in entries), default=1)

        for i, entry in enumerate(entries):
            if i < listbox.count():
                item = listbox.item(i)

                item.setText(_format(entry, kind_w))

                item.setData(Qt.ItemDataRole.UserRole, entry)

            else:
                item = QListWidgetItem(_format(entry, kind_w))

                item.setData(Qt.ItemDataRole.UserRole, entry)

                listbox.addItem(item)

        while listbox.count() > len(entries):
            listbox.takeItem(listbox.count() - 1)

        listbox.setUpdatesEnabled(True)

    def update_gates(gate_data):

        nonlocal all_gates

        all_gates = gate_data or []

        text = search_input.text()

        if text:
            needle = text.lower()
            _populate(
                [
                    g
                    for g in all_gates
                    if needle in g.get("name", "").lower()
                    or needle in (g.get("partner") or "").lower()
                    or needle in g.get("kind", "").lower()
                ]
            )
        else:
            _populate(all_gates)

    dialog.update_gates = update_gates

    def on_search(text):
        update_gates(all_gates)

    search_input.textChanged.connect(on_search)

    def on_select(item):

        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            if data:
                pyperclip.copy(data.get("name", ""))

    listbox.itemClicked.connect(on_select)

    listbox.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def on_context_menu(pos):

        item = listbox.itemAt(pos)

        if not item:
            return

        data = item.data(Qt.ItemDataRole.UserRole)

        if not data:
            return

        menu = QMenu(listbox)

        tp_action = menu.addAction("Teleport Here")

        walk_action = menu.addAction("Go Through Gate")

        copy_coords_action = menu.addAction("Copy Coordinates")

        copy_name_action = menu.addAction("Copy Name")

        copy_lua_action = menu.addAction("Copy Function")

        action = menu.exec(listbox.mapToGlobal(pos))

        if action == tp_action:
            send_queue.put(
                GUICommand(
                    GUICommandType.CustomTeleport,
                    {
                        "X": str(data["x"]),
                        "Y": str(data["y"]),
                        "Z": str(data["z"]),
                        "Yaw": str(data.get("yaw", 0.0)),
                    },
                )
            )

        elif action == walk_action:
            send_queue.put(
                GUICommand(GUICommandType.WalkThroughGate, data.get("name", ""))
            )

        elif action == copy_coords_action:
            pyperclip.copy(f"{data['x']}, {data['y']}, {data['z']}")

        elif action == copy_name_action:
            pyperclip.copy(data.get("name", ""))

        elif action == copy_lua_action:
            name = data.get("name", "").replace("\\", "\\\\").replace("'", "\\'")
            pyperclip.copy(f"client:go_through_gate('{name}')")

    listbox.customContextMenuRequested.connect(on_context_menu)

    orig_close = dialog.closeEvent

    def _close_event(event):
        send_queue.put(GUICommand(GUICommandType.StopGatesStream))
        orig_close(event)

    dialog.closeEvent = _close_event

    close_btn = QPushButton(tl("close") if tl else "Close")

    close_btn.clicked.connect(dialog.close)

    layout.addWidget(close_btn)

    send_queue.put(GUICommand(GUICommandType.StartGatesStream))

    dialog.show()

    return dialog
