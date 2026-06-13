import asyncio
import atexit
import ctypes
import ctypes.wintypes

import wizwalker
from wizwalker import user32
from wizwalker.memory.hooks import MouselessCursorMoveHook


# Track every hwnd we've disabled so we can re-enable on interpreter shutdown.
# Mitigates the "hard-crash leaves W101 disabled" caveat: if SkyFall exits
# uncleanly, atexit still fires for normal Python termination (SystemExit,
# unhandled exceptions, KeyboardInterrupt). Won't help on taskkill/BSOD —
# in that case the user has to restart W101.
_disabled_hwnds: "set[int]" = set()


def _restore_all_disabled_windows():
    for hwnd in list(_disabled_hwnds):
        try:
            user32.EnableWindow(hwnd, True)
        except Exception:
            pass
    _disabled_hwnds.clear()


atexit.register(_restore_all_disabled_windows)


class MouseHandler:
    """
    Handles clicking/moving the mouse position
    """

    def __init__(self, client: "wizwalker.Client"):
        self.client = client
        self.click_lock = None
        # Pre-button-down settle. set_mouse_position sends the WM_MOUSEMOVE via
        # blocking SendMessageW, so the move is already processed by the time we
        # get here — this is just a small safety margin, not a full move/click
        # gap. Kept low to maximize click throughput.
        self.click_predelay = 0.005
        # only for context managing
        self._ref_lock = None
        self._ref_count = 0
        # Tracks whether *we* currently have the W101 window disabled, so
        # enable/disable stays paired regardless of hook state.
        self._window_disabled = False
        # Saved foreground hwnd so we can restore focus if our disable call
        # was what stole it (W101 was foreground when we disabled it).
        self._saved_foreground = 0
        # External "sticky" lock — when >0, the window stays disabled even
        # after a click sequence ends. Used to keep input blocked for the
        # entire duration of bot execution.
        self._external_lock = 0
        # Make our app dpi aware so scaling works for free
        ctypes.windll.shcore.SetProcessDpiAwareness(2)

    def _disable_window(self):
        # Disable the W101 window so the user's physical input (mouse clicks,
        # scroll, keyboard) cannot reach it while the bot is mid-click.
        # SendMessage/PostMessage from our process still work on a disabled
        # window. Always wrapped in try/except so we never trap the user.
        if self._window_disabled:
            return
        try:
            hwnd = self.client.window_handle
            if not hwnd:
                return
            # Save foreground so we can restore focus on re-enable if
            # disabling W101 is what dropped it.
            try:
                self._saved_foreground = int(user32.GetForegroundWindow() or 0)
            except Exception:
                self._saved_foreground = 0
            user32.EnableWindow(hwnd, False)
            self._window_disabled = True
            _disabled_hwnds.add(int(hwnd))
        except Exception:
            pass

    def _enable_window(self):
        if not self._window_disabled:
            # Idempotent safety: even if our flag says we didn't disable,
            # try once in case the flag is out of sync (e.g. force-release
            # path). Cheap call.
            try:
                hwnd = self.client.window_handle
                if hwnd:
                    user32.EnableWindow(hwnd, True)
                    _disabled_hwnds.discard(int(hwnd))
            except Exception:
                pass
            return
        try:
            hwnd = self.client.window_handle
            if hwnd:
                user32.EnableWindow(hwnd, True)
                _disabled_hwnds.discard(int(hwnd))
        except Exception:
            pass
        self._window_disabled = False
        # If the W101 hwnd was the foreground when we disabled, Windows
        # dropped focus to nowhere. Restore only when the current foreground
        # is *not* something the user actively switched to — i.e. it's
        # still desktop/null or it's W101 itself. Never steal focus from
        # another app the user picked while we were mid-click.
        try:
            saved = self._saved_foreground
            self._saved_foreground = 0
            if not saved or not hwnd:
                return
            if int(saved) != int(hwnd):
                return  # user wasn't on W101 to begin with
            current = int(user32.GetForegroundWindow() or 0)
            if current == 0 or current == int(hwnd):
                # Foreground was lost or already returned; safe to nudge.
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    async def __aenter__(self):
        if self._ref_lock is None:
            self._ref_lock = asyncio.Lock()

        async with self._ref_lock:
            if (
                self._ref_count == 0
                and not self.client.hook_handler._check_if_hook_active(
                    MouselessCursorMoveHook
                )
            ):
                await self._activate_mouseless()
            # Always disable on entry into a fresh ref-count, even if the
            # hook was already active (e.g. stale from a prior crash) —
            # decoupled from hook state so protection isn't skipped.
            if self._ref_count == 0:
                self._disable_window()
            self._ref_count += 1

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._ref_lock is None:  # may god have mercy if this happens during exit
            self._ref_lock = asyncio.Lock()

        async with self._ref_lock:
            self._ref_count -= 1
            if self._ref_count == 0:
                if self.client.hook_handler._check_if_hook_active(
                    MouselessCursorMoveHook
                ):
                    await self._deactivate_mouseless()
                # Skip re-enable while a sticky lock is held — bot wants
                # the window blocked across the entire run, not just per
                # click sequence.
                if self._external_lock == 0:
                    self._enable_window()

    def lock_window_input(self):
        """
        Hold the W101 window disabled across the entire bot run. Survives
        across multiple click sequences. Counted — pair every call with
        ``unlock_window_input()``.
        """
        self._external_lock += 1
        self._disable_window()

    def unlock_window_input(self):
        """
        Release one sticky lock. When the count hits zero and no click is
        in flight, re-enables the window.
        """
        if self._external_lock > 0:
            self._external_lock -= 1
        if self._external_lock == 0 and self._ref_count == 0:
            self._enable_window()

    async def _activate_mouseless(self):
        try:
            from loguru import logger as _lg

            _lg.debug(f"mouseless: ACTIVATE (ref_count={self._ref_count})")
        except Exception:
            pass
        await self.client.hook_handler.activate_mouseless_cursor_hook()

    async def _deactivate_mouseless(self):
        try:
            from loguru import logger as _lg

            _lg.debug(f"mouseless: DEACTIVATE (ref_count={self._ref_count})")
        except Exception:
            pass
        await self.client.hook_handler.deactivate_mouseless_cursor_hook()

    async def release_mouse(self, *, post_button_up: bool = False):
        """
        Idempotently force-release the in-game cursor: deactivates the
        mouseless hook if active and resets the ref-count state so the
        next ``async with`` reactivates cleanly. Safe to call any time.

        If ``post_button_up`` is True, also posts WM_LBUTTONUP and
        WM_RBUTTONUP to clear any "held button" state. Only safe when
        the bot is NOT currently in the middle of a click sequence —
        racing a stray UP into the game while ``click()`` has DOWN
        pending will cancel the bot's own click.
        """
        try:
            from loguru import logger as _lg

            _lg.debug(
                f"release_mouse(post_button_up={post_button_up}) "
                f"ref_count={self._ref_count}"
            )
        except Exception:
            pass
        if post_button_up:
            try:
                hwnd = self.client.window_handle
                user32.PostMessageW(hwnd, 0x202, 0, 0)
                user32.PostMessageW(hwnd, 0x205, 0, 0)
            except Exception:
                pass
        try:
            if self.client.hook_handler._check_if_hook_active(MouselessCursorMoveHook):
                await self._deactivate_mouseless()
        except Exception:
            pass
        self._ref_count = 0
        # Force-release also clears the sticky lock — this is the panic
        # path; user-lockout prevention beats keeping the bot's lock.
        self._external_lock = 0
        self._enable_window()

    async def activate_mouseless(self):
        """
        Activates the mouseless hook
        """
        if self._ref_lock is not None or self._ref_count > 0:
            raise RuntimeError(
                "You can't mix managed mouseless with unmanaged mouseless"
            )
        await self._activate_mouseless()

    async def deactivate_mouseless(self):
        """
        Deactivates the mouseless hook
        """
        if self._ref_lock is not None or self._ref_count > 0:
            raise RuntimeError(
                "You can't mix managed mouseless with unmanaged mouseless"
            )
        await self._deactivate_mouseless()

    async def set_mouse_position_to_window(
        self, window: "wizwalker.memory.window.DynamicWindow", **kwargs
    ):
        """
        Set the mouse position to a window
        kwargs are passed to set_mouse_position

        Args:
            window: The window to set the mouse position to
        """
        scaled_rect = await window.scale_to_client()
        center = scaled_rect.center()

        await self.set_mouse_position(*center, **kwargs)

    async def click_window(
        self, window: "wizwalker.memory.window.DynamicWindow", **kwargs
    ):
        """
        Click a window
        kwargs are passed to .click

        Args:
            window: The window to click
        """
        scaled_rect = await window.scale_to_client()
        center = scaled_rect.center()

        await self.click(*center, **kwargs)

    async def click_window_with_name(self, name: str, **kwargs):
        """
        Click a window with a name
        kwargs are passed to .click

        Args:
            name: The name of the window to click

        Raises:
            ValueError: If no or too many windows where found
        """
        possible_window = await self.client.root_window.get_windows_with_name(name)

        if not possible_window:
            raise ValueError(f"Window with name {name} not found.")

        elif len(possible_window) > 1:
            raise ValueError(f"Multiple windows with name {name}.")

        await self.click_window(possible_window[0], **kwargs)

    # TODO: add errors (HookNotActive)
    async def click(
        self,
        x: int,
        y: int,
        *,
        right_click: bool = False,
        sleep_duration: float = 0.0,
        use_post: bool = False,
    ):
        """
        Send a click to a certain x and y
        x and y positions are relative to the top left corner of the screen

        Args:
            x: x to click at
            y: y to click at
            right_click: If the click should be a right click
            sleep_duration: How long to sleep between messages
            use_post: If PostMessage should be used instead of SendMessage
        """
        # We don't have to check if the hook is active since it will just error
        if right_click:
            button_down_message = 0x204
        else:
            button_down_message = 0x201

        if use_post:
            send_method = user32.PostMessageW
        else:
            send_method = user32.SendMessageW

        # so MouseHandler can be inited in sync funcs like other __init__s
        if self.click_lock is None:
            self.click_lock = asyncio.Lock()

        # prevent multiple clicks from happening at the same time
        async with self.click_lock:
            try:
                from loguru import logger as _lg

                _lg.debug(f"click: enter ({x},{y}) right={right_click}")
            except Exception:
                _lg = None
            # TODO: test passing use_post
            await self.set_mouse_position(x, y)
            await asyncio.sleep(self.click_predelay)
            button_down_sent = False
            try:
                # mouse button down
                send_method(self.client.window_handle, button_down_message, 1, 0)
                button_down_sent = True
                if _lg:
                    _lg.debug("click: DOWN sent")
                if sleep_duration > 0:
                    await asyncio.sleep(sleep_duration)
                # mouse button up
                send_method(self.client.window_handle, button_down_message + 1, 0, 0)
                button_down_sent = False
                if _lg:
                    _lg.debug("click: UP sent")
                # move mouse outside of client area — cosmetic un-highlight only,
                # nothing waits on it, so post it fire-and-forget instead of
                # blocking on a SendMessageW round-trip per click
                await self.set_mouse_position(-100, -100, use_post=True)
            finally:
                # If we sent a button-down but never the matching button-up
                # (cancel, exception, sleep interrupt), the game thinks the
                # mouse is being held. Always release it, even on the way out.
                if button_down_sent:
                    try:
                        user32.PostMessageW(
                            self.client.window_handle,
                            button_down_message + 1,
                            0,
                            0,
                        )
                    except Exception:
                        pass

    async def set_mouse_position(
        self,
        x: int,
        y: int,
        *,
        convert_from_client: bool = True,
        use_post: bool = False,
    ):
        """
        Set's the mouse position to a certain x y relative to the
        top left corner of the client

        Args:
            x: x to set
            y: y to set
            convert_from_client: If the position should be converted from client to screen
            use_post: If PostMessage should be used instead of SendMessage
        """
        if use_post:
            send_method = user32.PostMessageW
        else:
            send_method = user32.SendMessageW

        if convert_from_client:
            point = ctypes.wintypes.tagPOINT(x, y)

            # https://docs.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-clienttoscreen
            if (
                user32.ClientToScreen(self.client.window_handle, ctypes.byref(point))
                == 0
            ):
                raise RuntimeError("Client to screen conversion failed")

            # same point structure is overwritten by ClientToScreen; these are also ints and not
            # c_longs for some reason?
            x = point.x
            y = point.y

        res = await self.client.hook_handler.write_mouse_position(x, y)
        # position doesn't matter here; sending mouse move
        # mouse move is here so that items are highlighted
        send_method(self.client.window_handle, 0x200, 0, 0)
        return res
