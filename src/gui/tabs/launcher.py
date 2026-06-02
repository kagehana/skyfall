import os


from PyQt6.QtCore import QSize, Qt


from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


from src.gui.editorial import StrokedButton
from src.gui.commands import GUICommand, GUICommandType

from src.gui.helpers import (
    launcher_small_icon_btn,
    spinning_loader_widget,
)


def build_launcher_tab(ctx):

    from src.gui import editorial as ed

    tab = QWidget()

    launcher_layout = ed.page_layout(tab)

    tl = ctx.tl

    send_queue = ctx.send_queue

    svgs = ctx.svgs

    # header
    launcher_layout.addWidget(
        ed.heading(tl("launcher") if hasattr(ctx, "tl") else "Launcher")
    )

    launcher_layout.addSpacing(6)

    _subtitle = ed.subtitle(
        "Saved accounts and hooked clients — drag to reorder, check to launch."
    )

    launcher_layout.addWidget(_subtitle)

    launcher_layout.addSpacing(22)

    _hover_rgba = (
        "rgba(255,255,255,15)" if ctx.theme in ("black", "dark") else "rgba(0,0,0,15)"
    )

    _launcher_list_style = (
        "QListWidget {"
        "  background: transparent;"
        "  border: none;"
        "}"
        "QListWidget::item {"
        "  background: transparent;"
        "  border-radius: 4px;"
        "  padding: 2px;"
        "  margin: 1px 2px;"
        "}"
        "QListWidget::item:hover {"
        f"  background-color: {_hover_rgba};"
        "}"
        "QListWidget::item:disabled {"
        "  background: transparent;"
        "}"
        "QScrollBar:vertical { width: 6px; background: transparent; }"
        "QScrollBar::handle:vertical { background: rgba(255,255,255,40); border-radius: 3px; min-height: 20px; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
    )

    columns_layout = QHBoxLayout()

    columns_layout.setSpacing(28)

    left_col = QVBoxLayout()

    left_col.setSpacing(0)

    left_col.addLayout(ed.section_eyebrow_row(tl("saved_accounts")))

    left_col.addSpacing(8)

    account_list = QListWidget()

    account_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)

    account_list.setDefaultDropAction(Qt.DropAction.MoveAction)

    account_list.setStyleSheet(_launcher_list_style)

    account_list.setFrameShape(QFrame.Shape.NoFrame)

    ctx.widget_tags["AccountList"] = account_list

    def _on_account_rows_moved(*_args):

        nicknames = []

        for i in range(account_list.count()):
            item = account_list.item(i)

            w = account_list.itemWidget(item)

            if w:
                label = w.findChild(QLabel)

                if label:
                    nicknames.append(label.text())

        if nicknames:
            send_queue.put(GUICommand(GUICommandType.ReorderAccounts, nicknames))

    account_list.model().rowsMoved.connect(_on_account_rows_moved)

    left_col.addWidget(account_list, 1)

    columns_layout.addLayout(left_col, 1)

    right_col = QVBoxLayout()

    right_col.setSpacing(0)

    right_col.addLayout(ed.section_eyebrow_row(tl("hooked_clients")))

    right_col.addSpacing(8)

    hooked_clients_list = QListWidget()

    hooked_clients_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)

    hooked_clients_list.setDefaultDropAction(Qt.DropAction.MoveAction)

    hooked_clients_list.setStyleSheet(_launcher_list_style)

    hooked_clients_list.setFrameShape(QFrame.Shape.NoFrame)

    ctx.widget_tags["HookedClientsList"] = hooked_clients_list

    right_col.addWidget(hooked_clients_list, 1)

    _hooking_handles = set()

    _last_hooked_data = {}

    columns_layout.addLayout(right_col, 1)

    launcher_layout.addLayout(columns_layout, 1)

    def _show_add_account_dialog():
        from src.gui import editorial as ed

        dlg = QDialog(ctx.window)
        dlg.setModal(True)
        dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        card = ed.RoundedCard(ctx.bg_color, radius=12, parent=dlg)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        layout.addWidget(ed.eyebrow(tl("add_account")))
        layout.addWidget(ed.hairline())

        field_style = (
            "QLineEdit {"
            "  background-color: rgba(255,255,255,0.04);"
            "  color: rgba(236,236,236,0.95);"
            "  border: 1px solid rgba(255,255,255,0.08);"
            "  border-radius: 8px;"
            "  padding: 6px 10px;"
            "  font-size: 9pt;"
            "}"
            "QLineEdit:focus { border: 1px solid rgba(255,255,255,0.20); }"
        )

        nick_input = QLineEdit()
        nick_input.setPlaceholderText(tl("nickname"))
        nick_input.setStyleSheet(field_style)
        layout.addWidget(nick_input)

        user_input = QLineEdit()
        user_input.setPlaceholderText("Username")
        user_input.setStyleSheet(field_style)
        layout.addWidget(user_input)

        pwd_input = QLineEdit()
        pwd_input.setPlaceholderText("Password")
        pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_input.setStyleSheet(field_style)
        layout.addWidget(pwd_input)

        layout.addWidget(ed.hairline())

        actions_btn_style = (
            "QPushButton {"
            "  background-color: transparent;"
            f"  color: {ed.MUTED_TEXT};"
            "  border: 1px solid rgba(255,255,255,0.08);"
            "  border-radius: 8px;"
            "  padding: 5px 10px;"
            "  font-size: 7.6pt;"
            "}"
            "QPushButton:hover { color: rgba(236,236,236,0.95);"
            " background-color: rgba(255,255,255,0.04); }"
        )

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)

        cancel_btn = StrokedButton(tl("cancel"))
        cancel_btn.setStyleSheet(actions_btn_style)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(dlg.reject)

        save_btn = StrokedButton(tl("save_account"))
        save_btn.setStyleSheet(ctx.btn_style)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def _on_save():
            nick = nick_input.text().strip()
            user = user_input.text()
            pwd = pwd_input.text()
            if nick and user and pwd:
                send_queue.put(
                    GUICommand(GUICommandType.SaveAccount, (nick, user, pwd))
                )
                dlg.accept()

        save_btn.clicked.connect(_on_save)

        actions.addWidget(cancel_btn, 1)
        actions.addWidget(save_btn, 1)
        layout.addLayout(actions)

        dlg.setFixedWidth(320)
        dlg.adjustSize()

        parent = ctx.window
        if parent is not None:
            pg = parent.geometry()
            dlg.move(
                pg.x() + (pg.width() - dlg.width()) // 2,
                pg.y() + (pg.height() - dlg.height()) // 2,
            )

        dlg.exec()

    def _persist_chosen(nickname: str, checked: bool):
        if not ctx.settings:
            return
        if not ctx.settings.get_setting("remember_chosen_clients"):
            return
        chosen = list(ctx.settings.get_setting("chosen_clients") or [])
        if checked and nickname not in chosen:
            chosen.append(nickname)
        elif not checked and nickname in chosen:
            chosen.remove(nickname)
        else:
            return
        ctx.settings.set_setting("chosen_clients", chosen)

    def _build_account_item_widget(nickname: str, disabled: bool = False):

        row = QWidget(account_list)

        row.setStyleSheet("background: transparent;")

        row_layout = QHBoxLayout(row)

        row_layout.setContentsMargins(2, 0, 2, 0)

        row_layout.setSpacing(4)

        cb = QCheckBox()

        if (
            not disabled
            and ctx.settings
            and ctx.settings.get_setting("remember_chosen_clients")
            and nickname in (ctx.settings.get_setting("chosen_clients") or [])
        ):
            cb.setChecked(True)

        cb.stateChanged.connect(lambda s, n=nickname: _persist_chosen(n, bool(s)))

        row_layout.addWidget(cb)

        lbl = QLabel(nickname)

        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        row_layout.addWidget(lbl, 1)

        if disabled:
            cb.setEnabled(False)

            cb.setChecked(False)

            lbl.setStyleSheet(
                "color: rgba(255,255,255,80);"
                if ctx.theme in ("black", "dark")
                else "color: rgba(0,0,0,80);"
            )

            lbl.setToolTip(tl("already_active"))

        def _delete_this():

            send_queue.put(GUICommand(GUICommandType.DeleteAccount, nickname))

        trash_btn = launcher_small_icon_btn(
            ctx, svgs["trash"], tl("remove_account"), _delete_this
        )

        row_layout.addWidget(trash_btn)

        return row

    def _populate_account_list(nicknames: list[str]):

        remember = ctx.settings and ctx.settings.get_setting("remember_chosen_clients")

        managed = ctx.widget_tags.get("managed_accounts", set())

        account_list.setUpdatesEnabled(False)

        account_list.clear()

        for nick in nicknames:
            item = QListWidgetItem()

            item.setSizeHint(QSize(0, 28))

            row_widget = _build_account_item_widget(
                nick, disabled=(nick in managed and not remember)
            )

            account_list.addItem(item)

            account_list.setItemWidget(item, row_widget)

        account_list.setUpdatesEnabled(True)

    def _refresh_account_eligibility(managed_accounts):

        remember = ctx.settings and ctx.settings.get_setting("remember_chosen_clients")

        managed = set(managed_accounts)

        for i in range(account_list.count()):
            item = account_list.item(i)

            w = account_list.itemWidget(item)

            if not w:
                continue

            cb = w.findChild(QCheckBox)

            lbl = w.findChild(QLabel)

            if not cb or not lbl:
                continue

            nick = lbl.text()

            if nick in managed and not remember:
                cb.setEnabled(False)

                cb.setChecked(False)

                lbl.setStyleSheet(
                    "color: rgba(255,255,255,80);"
                    if ctx.theme in ("black", "dark")
                    else "color: rgba(0,0,0,80);"
                )

                lbl.setToolTip(tl("already_active"))

            else:
                cb.setEnabled(True)

                lbl.setStyleSheet("")

                lbl.setToolTip("")

    def _build_hooked_client_widget(info: dict):

        row = QWidget(hooked_clients_list)

        row.setStyleSheet("background: transparent;")

        row_layout = QHBoxLayout(row)

        row_layout.setContentsMargins(2, 0, 2, 0)

        row_layout.setSpacing(4)

        title = info["title"]

        nick = info.get("account_nick")

        display = f"{title} ({nick})" if nick else title

        lbl = QLabel(display)

        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        row_layout.addWidget(lbl, 1)

        handle = info["handle"]

        def _kill_this():

            send_queue.put(GUICommand(GUICommandType.KillClient, handle))

        kill_btn = launcher_small_icon_btn(
            ctx, svgs["kill_client"], tl("kill_client"), _kill_this
        )

        row_layout.addWidget(kill_btn)

        if nick:

            def _relaunch_this():

                send_queue.put(
                    GUICommand(GUICommandType.RelaunchClient, (handle, nick))
                )

            relaunch_btn = launcher_small_icon_btn(
                ctx, svgs["relaunch"], tl("relaunch_client"), _relaunch_this
            )

            row_layout.addWidget(relaunch_btn)

        def _eject_this():

            send_queue.put(GUICommand(GUICommandType.UnhookClient, handle))

        eject_btn = launcher_small_icon_btn(
            ctx, svgs["eject"], tl("unhook_client"), _eject_this
        )

        row_layout.addWidget(eject_btn)

        return row

    def _build_unmanaged_client_widget(handle: int):

        row = QWidget(hooked_clients_list)

        row.setStyleSheet("background: transparent;")

        row_layout = QHBoxLayout(row)

        row_layout.setContentsMargins(2, 0, 2, 0)

        row_layout.setSpacing(4)

        lbl = QLabel(f"Wizard101 ({handle})")

        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lbl.setStyleSheet(
            "color: rgba(255,255,255,120);"
            if ctx.theme in ("black", "dark")
            else "color: rgba(0,0,0,120);"
        )

        row_layout.addWidget(lbl, 1)

        def _kill_this():

            send_queue.put(GUICommand(GUICommandType.KillClient, handle))

        kill_btn = launcher_small_icon_btn(
            ctx, svgs["kill_client"], tl("kill_client"), _kill_this
        )

        row_layout.addWidget(kill_btn)

        def _hook_this():

            _hooking_handles.add(handle)

            _rebuild_hooked_clients_list()

            send_queue.put(GUICommand(GUICommandType.HookClient, handle))

        hook_btn = launcher_small_icon_btn(
            ctx, svgs["hook"], tl("hook_client"), _hook_this
        )

        row_layout.addWidget(hook_btn)

        return row

    def _build_hooking_client_widget(handle: int, nick: str = None):

        row = QWidget(hooked_clients_list)

        row.setStyleSheet("background: transparent;")

        row_layout = QHBoxLayout(row)

        row_layout.setContentsMargins(2, 0, 2, 0)

        row_layout.setSpacing(4)

        display = nick if nick else f"Wizard101 ({handle})"

        lbl = QLabel(display)

        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lbl.setStyleSheet(
            "color: rgba(255,255,255,120);"
            if ctx.theme in ("black", "dark")
            else "color: rgba(0,0,0,120);"
        )

        row_layout.addWidget(lbl, 1)

        row_layout.addWidget(spinning_loader_widget(ctx))

        return row

    def _rebuild_hooked_clients_list():

        hooked_clients_list.setUpdatesEnabled(False)

        hooked_clients_list.clear()

        hooked = _last_hooked_data.get("hooked", [])

        unmanaged = _last_hooked_data.get("unmanaged", [])

        hooking_backend = set(_last_hooked_data.get("hooking", []))

        hooked_handle_set = {info["handle"] for info in hooked}

        for info in hooked:
            item = QListWidgetItem()

            item.setSizeHint(QSize(0, 28))

            h = info["handle"]

            if h in hooking_backend:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)

                row_widget = _build_hooking_client_widget(h, info.get("account_nick"))

            else:
                item.setData(Qt.ItemDataRole.UserRole, h)

                row_widget = _build_hooked_client_widget(info)

            hooked_clients_list.addItem(item)

            hooked_clients_list.setItemWidget(item, row_widget)

        for h in list(_hooking_handles):
            if h not in hooked_handle_set:
                item = QListWidgetItem()

                item.setSizeHint(QSize(0, 28))

                item.setFlags(Qt.ItemFlag.ItemIsEnabled)

                row_widget = _build_hooking_client_widget(h)

                hooked_clients_list.addItem(item)

                hooked_clients_list.setItemWidget(item, row_widget)

        remaining = [h for h in unmanaged if h not in _hooking_handles]

        if remaining:
            sep_item = QListWidgetItem()

            sep_item.setSizeHint(QSize(0, 20))

            sep_item.setFlags(Qt.ItemFlag.NoItemFlags)

            sep_widget = QWidget(hooked_clients_list)

            sep_widget.setStyleSheet("background: transparent;")

            sep_layout = QHBoxLayout(sep_widget)

            sep_layout.setContentsMargins(4, 2, 4, 2)

            sep_lbl = QLabel(tl("unmanaged_clients"))

            sep_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            sep_lbl.setStyleSheet(
                "color: rgba(255,255,255,80); font-size: 10px;"
                if ctx.theme in ("black", "dark")
                else "color: rgba(0,0,0,80); font-size: 10px;"
            )

            sep_layout.addWidget(sep_lbl, 1)

            hooked_clients_list.addItem(sep_item)

            hooked_clients_list.setItemWidget(sep_item, sep_widget)

            for handle in remaining:
                u_item = QListWidgetItem()

                u_item.setSizeHint(QSize(0, 28))

                u_item.setFlags(Qt.ItemFlag.ItemIsEnabled)

                u_widget = _build_unmanaged_client_widget(handle)

                hooked_clients_list.addItem(u_item)

                hooked_clients_list.setItemWidget(u_item, u_widget)

        hooked_clients_list.setUpdatesEnabled(True)

    def _on_hooked_rows_moved(*_args):

        handles = []

        for i in range(hooked_clients_list.count()):
            item = hooked_clients_list.item(i)

            handle = item.data(Qt.ItemDataRole.UserRole)

            if handle is not None:
                handles.append(handle)

        if handles:
            send_queue.put(GUICommand(GUICommandType.ReorderClients, handles))

            old_hooked = _last_hooked_data.get("hooked", [])

            handle_to_info = {info["handle"]: info for info in old_hooked}

            _last_hooked_data["hooked"] = [
                handle_to_info[h] for h in handles if h in handle_to_info
            ]

            _rebuild_hooked_clients_list()

    hooked_clients_list.model().rowsMoved.connect(_on_hooked_rows_moved)

    def _launch_and_login():

        selected = []

        for i in range(account_list.count()):
            item = account_list.item(i)

            w = account_list.itemWidget(item)

            if w:
                cb = w.findChild(QCheckBox)

                lbl = w.findChild(QLabel)

                if cb and lbl and cb.isChecked():
                    selected.append(lbl.text())

        if selected:
            game_path = (
                ctx.settings.get_setting("game_path") if ctx.settings else ""
            ) or ""

            send_queue.put(
                GUICommand(GUICommandType.LaunchInstance, (selected, game_path.strip()))
            )

    _saved_path = ctx.settings.get_setting("game_path") if ctx.settings else None

    if not (_saved_path and os.path.isdir(_saved_path)):
        _steam_path = r"C:\Program Files (x86)\Steam\steamapps\common\Wizard101"

        _default_path = r"C:\ProgramData\KingsIsle Entertainment\Wizard101"

        _resolved_path = ""

        if os.path.isdir(_steam_path):
            _resolved_path = _steam_path

        elif os.path.isdir(_default_path):
            _resolved_path = _default_path

        if _resolved_path and ctx.settings:
            ctx.settings.set_setting("game_path", _resolved_path)

    launcher_layout.addSpacing(14)

    launcher_layout.addWidget(ed.hairline())

    launcher_layout.addSpacing(8)

    launcher_action_row = QHBoxLayout()

    launcher_action_row.setContentsMargins(0, 0, 0, 0)

    launcher_action_row.setSpacing(8)

    _launcher_meta = ed.meta("")

    launcher_action_row.addWidget(_launcher_meta)

    _remember_cb = QCheckBox("Remember selection")
    _remember_cb.setChecked(
        bool(ctx.settings and ctx.settings.get_setting("remember_chosen_clients"))
    )

    def _remember_cb_style():
        a = ed.accent_of(ctx)
        return (
            f"QCheckBox {{ spacing: 6px; color: {ed.DIM_TEXT}; font-size: 7.8pt; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px;"
            f" border: 1px solid rgba(255,255,255,0.15); border-radius: 3px;"
            f" background: rgba(255,255,255,0.04); }}"
            f"QCheckBox::indicator:checked {{ background: {a};"
            f" border-color: {a}; }}"
        )

    _remember_cb.setStyleSheet(_remember_cb_style())
    _remember_cb.setCursor(Qt.CursorShape.PointingHandCursor)
    _remember_cb.setToolTip("Remember which clients were checked when relaunching")

    def _on_remember_toggled(state):
        if ctx.settings:
            ctx.settings.set_setting("remember_chosen_clients", bool(state))
            if state:
                snapshot = []
                for i in range(account_list.count()):
                    item = account_list.item(i)
                    w = account_list.itemWidget(item)
                    if not w:
                        continue
                    cb = w.findChild(QCheckBox)
                    lbl = w.findChild(QLabel)
                    if cb and lbl and cb.isChecked():
                        snapshot.append(lbl.text())
                ctx.settings.set_setting("chosen_clients", snapshot)
            else:
                ctx.settings.set_setting("chosen_clients", [])
        _refresh_account_eligibility(ctx.widget_tags.get("managed_accounts", set()))

    _remember_cb.stateChanged.connect(_on_remember_toggled)

    launcher_action_row.addWidget(_remember_cb)

    launcher_action_row.addStretch(1)

    def _reboot():
        send_queue.put(GUICommand(GUICommandType.Reboot))

    actions_group = QHBoxLayout()
    actions_group.setContentsMargins(0, 0, 0, 0)
    actions_group.setSpacing(2)

    actions_group.addWidget(
        ctx.registry.action_icon_btn(
            svgs["add"], tl("add_account"), lambda: _show_add_account_dialog()
        )
    )

    actions_group.addWidget(
        ctx.registry.action_icon_btn(
            svgs["play"], tl("launch_login"), _launch_and_login
        )
    )

    actions_group.addWidget(
        ctx.registry.action_icon_btn(svgs["refresh"], tl("reboot"), _reboot)
    )

    launcher_action_row.addLayout(actions_group)

    launcher_layout.addLayout(launcher_action_row)

    def _refresh_launcher_meta():

        _accts = account_list.count()

        _launcher_meta.setText(f"{_accts} ACCOUNTS")

    account_list.model().rowsInserted.connect(lambda *_: _refresh_launcher_meta())

    account_list.model().rowsRemoved.connect(lambda *_: _refresh_launcher_meta())

    _refresh_launcher_meta()

    send_queue.put(GUICommand(GUICommandType.LoadAccounts))

    def _retheme():
        _remember_cb.setStyleSheet(_remember_cb_style())

    ctx.exports["launcher"] = {
        "populate_account_list": _populate_account_list,
        "rebuild_hooked_clients_list": _rebuild_hooked_clients_list,
        "refresh_account_eligibility": _refresh_account_eligibility,
        "hooking_handles": _hooking_handles,
        "last_hooked_data": _last_hooked_data,
        "account_list": account_list,
        "retheme": _retheme,
    }

    return tab


# stats-tab combatant card widgets
