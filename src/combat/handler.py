from __future__ import annotations


import asyncio


from wizwalker.combat import CombatHandler, CombatMember, CombatCard

from wizwalker.errors import MemoryInvalidated, WizWalkerMemoryError
from wizwalker.memory import WindowFlags


class _ErrorOnlyLogger:
    _SILENCED = {"debug", "info", "success", "trace", "warning"}

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        if name in self._SILENCED:
            return _noop
        return getattr(self._real, name)


def _noop(*_a, **_k):
    return None


try:
    from loguru import logger as _real_logger

    _logger = _ErrorOnlyLogger(_real_logger)
except Exception:
    _logger = None

# set True only when diagnosing cast-index or target-resolution issues
# when False, the expensive pre-cast hand/member dumps are skipped entirely
# so that the debug block never adds latency to normal play
_VERBOSE_LOG = True

_UNSET = object()  # sentinel for "attribute not present on client"


def _dbg(msg: str):
    # combat debug tracing intentionally silenced; mouse-handler logs in
    # libs/wizwalker/wizwalker/mouse_handler.py are kept for diagnosing
    # stuck-input issues. re-enable here if combat decisions need tracing.
    return


def _combat_log(msg: str):
    if _logger is not None:
        _logger.debug(f"Combat: {msg}")


def _move_label(move) -> str:
    if getattr(move, "is_pass", False):
        return "pass"
    if getattr(move, "is_willcast", False):
        return "willcast"
    if getattr(move, "petcast_spell", None):
        return f"petcast {move.petcast_spell}"
    spell = getattr(move, "spell", None)
    if isinstance(spell, TemplateReq):
        base = "any<" + "&".join(spell.types) + ">"
    else:
        base = str(spell) if spell else "card"
    enchants = [
        e
        for e in (getattr(move, "enchant", None), getattr(move, "enchant2", None))
        if e
    ]
    if enchants:
        base += " + " + " + ".join(enchants)
    return base


async def _card_label(card: CombatCard) -> str:
    try:
        n = await card.name()
        if n:
            return n
    except Exception:
        pass

    tid = None
    try:
        tid = await card.template_id()
    except Exception:
        pass

    if tid:
        try:
            cache = card.combat_handler.client.cache_handler
            resolved = await cache.get_template_name(tid)
            if resolved:
                return f"{resolved} (tid={tid})"
        except Exception:
            pass
        return f"card#{tid}"

    return "card"


async def _hand_label(cards: list[CombatCard]) -> str:
    names = []
    for c in cards:
        names.append(await _card_label(c))
    return ", ".join(names) if names else "empty"


async def _log_target_window(target):
    if target is None or target is False:
        return
    if isinstance(target, list):
        for t in target:
            await _log_target_window(t)
        return
    try:
        win = await target.get_health_text_window()
        rect = await win.scale_to_client()
        cx, cy = rect.center()
        _dbg(f"  click target: health window center=({cx},{cy}) rect={rect}")
    except Exception as exc:
        _dbg(
            f"  click target: get_health_text_window failed: {type(exc).__name__}: {exc}"
        )


async def _member_label(m) -> str:
    if m is None:
        return "None"
    if m is False:
        return "False"
    if isinstance(m, list):
        labels = []
        for x in m:
            labels.append(await _member_label(x))
        return "[" + ", ".join(labels) + "]"
    try:
        nm = await m.name()
    except Exception:
        nm = "?"
    try:
        part = await m.get_participant()
        team = await part.team_id()
        oid = await part.owner_id_full()
    except Exception:
        team, oid = "?", "?"
    return f"{nm}(team={team},owner={oid})"


from .config import (
    CombatConfig,
    MoveConfig,
    PriorityLine,
    TemplateReq,
    parse_config,
    parse_lua_table,
)

from .effects import (
    card_matches_reqs,
)


# SpellTarget bitmask: bit N set = subcircle N targeted. _subcircle_of()
# computes this dynamically per-target

# default target when a spell has no explicit target (e.g. willcast item
# cards). the server treats unknown targets for self-cast spells correctly,
# but we still need *some* int - 0 is the safe sentinel
_NO_TARGET = 0


async def _areturn(val):
    return val


async def _get_my_spell_list(handler) -> list | None:
    try:
        client = handler.client
        my_id = await client.client_object.global_id_full()
        participants = await client.duel.participant_list()
        for p in participants:
            try:
                if await p.owner_id_full() == my_id:
                    hand = await p.hand()
                    if hand is not None:
                        return await hand.spell_list()
            except Exception:
                continue
    except Exception:
        pass
    return None


async def _hand_index_of(
    handler: "NativeCombat", card: CombatCard, *, spells=None
) -> int | None:
    # get our spell template id to match by
    try:
        wanted_tid = await card.template_id()
    except Exception:
        wanted_tid = None
    try:
        wanted_name = await card.name()
    except Exception:
        wanted_name = None

    if spells is None:
        spells = await _get_my_spell_list(handler)

    if spells:
        if wanted_tid is not None:
            for idx, s in enumerate(spells):
                try:
                    if await s.template_id() == wanted_tid:
                        return idx
                except Exception:
                    continue
        if wanted_name is not None:
            for idx, s in enumerate(spells):
                try:
                    tpl = await s.spell_template()
                    if tpl and (await tpl.name()) == wanted_name:
                        return idx
                except Exception:
                    continue
        # spell_list is the source of truth for the cast index. if we have it
        # and the card isn't in it, it's not castable now - return None and let
        # the caller bail. the castable-cards fallback uses a different index
        # space the server would silently drop, hanging the round
        return None

    # fallback (test path / participant hand unavailable): match against
    # wizwalker's castable_cards by spell-window addr or name
    try:
        target_addr = card._spell_window.base_address
    except Exception:
        target_addr = None
    try:
        castable = await handler.get_castable_cards()
    except Exception:
        castable = await handler.get_cards()
    if target_addr is not None:
        for idx, c in enumerate(castable):
            try:
                if c._spell_window.base_address == target_addr:
                    return idx
            except Exception:
                continue
    if wanted_name is not None:
        for idx, c in enumerate(castable):
            try:
                if await c.name() == wanted_name:
                    return idx
            except Exception:
                continue
    return None


async def _index_of_tid(
    spells, tid: int | None, *, handler: "NativeCombat | None" = None
) -> int | None:
    if tid is None:
        return None
    if spells:
        for idx, s in enumerate(spells):
            try:
                if await s.template_id() == tid:
                    return idx
            except Exception:
                continue
    if handler is None:
        return None
    try:
        castable = await handler.get_castable_cards()
    except Exception:
        try:
            castable = await handler.get_cards()
        except Exception:
            return None
    for idx, c in enumerate(castable):
        try:
            if await c.template_id() == tid:
                return idx
        except Exception:
            continue
    return None


async def _subcircle_of(target) -> int:
    if target is None or target is False:
        return _NO_TARGET
    if isinstance(target, list):
        if not target:
            return _NO_TARGET
        mask = 0
        for m in target:
            try:
                part = await m.get_participant()
                mask |= 1 << (await part.subcircle())
            except Exception:
                continue
        return mask if mask else _NO_TARGET
    try:
        part = await target.get_participant()
        return 1 << (await part.subcircle())
    except Exception:
        return _NO_TARGET


class NativeCombat(CombatHandler):
    def __init__(self, client, config=None, cast_time: float = 0.2):

        super().__init__(client)

        self._config: CombatConfig | None = None

        self._cast_time = cast_time

        self._turn_adjust = 0

        self._rel_offset = 0

        self._prev_card_count = 0

        self._did_first_round = False

        # window/member caches - populated lazily, cleared per combat
        self._member_windows = None  # cached CombatantControl windows
        self._client_member_idx = None  # index of client in _member_windows

        # caches for one priority scan, set up and torn down in
        # _handle_round_inner. while live, name and enemy/ally/boss lookups hit
        # these instead of re-reading memory each line. don't rely on them
        # outside the scan
        self._round_name_cache: dict | None = None
        self._round_target_cache: dict | None = None

        # tracks the previous value of client.combat_config so we can detect
        # a CombatConfig → None transition (toggle off) and mirror it
        self._last_live_config = _UNSET

        # id() of the last config whose focus_school we wrote, so we don't
        # re-poke primary_magic_school_id every round
        self._applied_focus_for: int | None = None

        # stuck-on-pass detection: rounds since we last cast a non-pass. if it
        # drags on (hand drained to cards the playstyle can't use) we auto-flee
        # instead of looping forever
        self._rounds_since_cast = 0
        self._stuck_flee_threshold = 8

        # cooperative cancel. lua-driven combat runs in the bot task, not
        # combat_task, so combat_task.cancel() can't reach it - the toggle
        # hotkey calls cancel_combat() on client._active_combat instead
        self._should_exit = False

        if config is not None:
            if isinstance(config, CombatConfig):
                self._config = config
            else:
                self.set_config_string(str(config))

        # client._active_combat is set in handle_combat() at ownership, not
        # here. setting it in __init__ let two handlers race - the second
        # stomped the first as "active" while the first kept sending packets

    def _clear_member_cache(self):
        self._member_windows = None
        self._client_member_idx = None

    @staticmethod
    def _card_key(card: CombatCard):
        try:
            return card._spell_window.base_address
        except Exception:
            return id(card)

    async def _names_for(self, card: CombatCard) -> list[str]:
        cache = self._round_name_cache
        if cache is None:
            return await _card_names(card)
        key = self._card_key(card)
        cached = cache.get(key)
        if cached is not None:
            return cached
        names = await _card_names(card)
        cache[key] = names
        return names

    async def _packet_pause(self):
        if self._cast_time and self._cast_time > 0:
            await asyncio.sleep(self._cast_time)

    def set_config_string(self, text: str, cast_time: float | None = None):

        self._config = parse_config(text)

        if cast_time is not None:
            self._cast_time = cast_time

        self._reset_round_state()

    def set_config_lua(self, lua_table, cast_time: float | None = None):

        self._config = parse_lua_table(lua_table)

        if cast_time is not None:
            self._cast_time = cast_time

        self._reset_round_state()

    def clear_config(self):

        self._config = None

        self._reset_round_state()

    def cancel_combat(self):
        self._should_exit = True
        if _logger is not None:
            _logger.debug("NativeCombat: cancel_combat() received")

    async def handle_combat(self):
        try:
            from wizwalker.memory import DuelPhase
            from wizwalker import MemoryReadError, ReadingEnumFailed
        except Exception:
            await super().handle_combat()
            return

        # wait for any sibling handler on this client to finish before taking
        # over - the toggle loop and lua's waitfor_battle_finish can both spawn
        # handlers and double-send every packet. bail if the battle ends or
        # we're cancelled while waiting
        while True:
            if self._should_exit:
                return
            existing = getattr(self.client, "_active_combat", None)
            if existing is None or existing is self:
                break
            if not await self.in_combat():
                return
            await asyncio.sleep(0.5)

        # take ownership. last writer wins on the assignment, but the
        # in-loop ownership check below catches the race: whichever instance
        # ends up not owning _active_combat exits at the next checkpoint
        try:
            self.client._active_combat = self
        except Exception:
            pass

        self._clear_member_cache()
        self._should_exit = False

        try:
            while await self.in_combat():
                # yield to a sibling that won the ownership race after us
                if getattr(self.client, "_active_combat", None) is not self:
                    if _logger is not None:
                        _logger.info(
                            "NativeCombat: ownership taken by sibling handler; exiting."
                        )
                    return  # don't clear _active_combat in finally - it's not ours
                if self._should_exit_now():
                    break
                await self.wait_for_planning_phase(sleep_time=0.1)
                if self._should_exit_now():
                    break
                try:
                    if await self.client.duel.duel_phase() != DuelPhase.planning:
                        break
                except (ReadingEnumFailed, MemoryReadError):
                    break
                try:
                    round_number = await self.round_number()
                except Exception as exc:
                    if _logger is not None:
                        _logger.warning(
                            f"round_number() failed ({type(exc).__name__}: {exc}); retrying"
                        )
                    await asyncio.sleep(0.5)
                    continue
                try:
                    await self.handle_round()
                except Exception as exc:
                    if _logger is not None:
                        _logger.warning(
                            f"handle_round raised {type(exc).__name__}: {exc}; passing turn"
                        )
                    await self._send_pass()
                if self._should_exit_now():
                    break
                await self.wait_until_next_round(round_number, sleep_time=0.1)
        finally:
            self._spell_check_boxes = None
            self._clear_member_cache()
            # release the _active_combat slot, but only if it's still us
            try:
                if getattr(self.client, "_active_combat", None) is self:
                    self.client._active_combat = None
            except Exception:
                pass

    def _should_exit_now(self) -> bool:
        if self._should_exit:
            if _logger is not None:
                _logger.info("NativeCombat: exiting combat loop (cancel_combat).")
            return True
        return False

    async def get_members(self):
        if not self._member_windows:
            self._member_windows = await self.client.root_window.get_windows_with_name(
                "CombatantControl"
            )
        return [CombatMember(self, w) for w in self._member_windows]

    async def get_client_member(self, *, retries: int = 10, sleep_time: float = 0.5):
        if self._client_member_idx is not None and self._member_windows:
            try:
                member = CombatMember(
                    self, self._member_windows[self._client_member_idx]
                )
                part = await member.get_participant()
                await part.owner_id_full()
                return member
            except Exception:
                self._clear_member_cache()

        for _ in range(retries):
            members = await self.get_members()
            for idx, member in enumerate(members):
                try:
                    if await member.is_client():
                        self._client_member_idx = idx
                        return member
                except Exception:
                    pass
            await asyncio.sleep(0.05)

        raise ValueError("Couldn't find client's CombatMember")

    async def wait_until_next_round(self, current_round: int, sleep_time: float = 0.1):
        while await self.in_combat():
            try:
                if await self.round_number() > current_round:
                    return
            except Exception:
                pass
            await asyncio.sleep(sleep_time)

    async def handle_round(self):
        if _logger is not None and _VERBOSE_LOG:
            _logger.debug(
                f"NativeCombat.handle_round: enter (config={self._config is not None})"
            )
        await self._handle_round_inner()

    async def _send_pass(self):
        try:
            if _logger is not None and _VERBOSE_LOG:
                _logger.debug("_send_pass: calling client.send_combat_pass() (packet)")
            await self.client.send_combat_pass()
            await self._packet_pause()
            self._clear_member_cache()
            if _logger is not None and _VERBOSE_LOG:
                _logger.debug("_send_pass: send_combat_pass returned cleanly")
        except Exception as exc:
            if _logger is not None:
                _logger.warning(
                    f"Combat: packet pass failed ({type(exc).__name__}); "
                    f"trying the pass button instead."
                )
            try:
                await self.pass_button()
            except Exception:
                pass

    async def _write_focus_school(self, school: str) -> bool:
        try:
            from wizwalker.memory.memory_objects.conditionals import (
                school_id_to_names,
            )

            key = (school or "").lower()
            sid = next(
                (v for k, v in school_id_to_names.items() if k.lower() == key),
                None,
            )
            if sid is None:
                if _logger is not None:
                    _logger.warning(
                        f"Combat: focus school {school!r} not in "
                        f"school_id_to_names; ignoring."
                    )
                return False

            for m in await self.get_members():
                try:
                    if await m.is_player():
                        part = await m.get_participant()
                        await part.write_primary_magic_school_id(int(sid))
                        return True
                except Exception:
                    continue
            return False
        except Exception as exc:
            if _logger is not None:
                _logger.warning(
                    f"Combat: failed to write focus school "
                    f"({type(exc).__name__}: {exc})"
                )
            return False

    async def _apply_focus_school(self):
        cfg = self._config
        if cfg is None or not cfg.focus_school:
            return
        if self._applied_focus_for == id(cfg):
            return

        await self._write_focus_school(cfg.focus_school)
        # mark as applied even on failure so we don't retry every round
        self._applied_focus_for = id(cfg)

    async def _apply_pip_school(self):
        cfg = self._config
        if cfg is None or not cfg.pip_school:
            return
        try:
            from src.utils import assign_school_pip

            await assign_school_pip(self.client, cfg.pip_school)
        except Exception as exc:
            if _logger is not None:
                _logger.warning(
                    f"Combat: pip-school assignment failed "
                    f"({type(exc).__name__}: {exc})"
                )

    async def _handle_round_inner(self):

        if _logger is not None and _VERBOSE_LOG:
            _logger.debug("_handle_round_inner: enter")

        live = getattr(self.client, "combat_config", _UNSET)
        prev_live = self._last_live_config
        self._last_live_config = live

        if live is not _UNSET:
            if isinstance(live, CombatConfig) and live is not self._config:
                self._config = live
                self._reset_round_state()
                # new config - its focus_school (if any) hasn't been applied yet
                self._applied_focus_for = None
            elif (
                live is None
                and isinstance(prev_live, CombatConfig)
                and self._config is prev_live
            ):
                # client.combat_config was just toggled from a CombatConfig → None.
                # mirror the deactivation. skipped when self._config was set via
                # set_config_string() (then self._config is not prev_live).
                self._config = None
                self._applied_focus_for = None

        if not self._config:
            _combat_log("no playstyle loaded; passing.")
            await self._send_pass()

            return

        await self._apply_focus_school()
        await self._apply_pip_school()

        # reading battle state can briefly fail mid-transition (windows not
        # refreshed, duel struct being rewritten). retry a few times so a
        # transient hiccup doesn't drop the whole turn
        real_round = cur_card_count = client_member = None
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                real_round, cur_card_count, client_member = await asyncio.gather(
                    self.round_number(),
                    self._get_card_count(),
                    self.get_client_member(),
                )
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 3:
                    # member-window cache may be stale (new wave spawned, etc.)
                    self._clear_member_cache()
                    await asyncio.sleep(0.3 + 0.2 * attempt)
                    continue

        if last_exc is not None:
            if _logger is not None:
                _logger.warning(
                    f"Combat: could not read battle state after retries "
                    f"({type(last_exc).__name__}: {last_exc}); passing."
                )
            await self._send_pass()
            return

        if self._did_first_round and cur_card_count >= self._prev_card_count:
            self._turn_adjust -= 1

        self._did_first_round = True

        self._prev_card_count = cur_card_count

        try:
            stunned = await client_member.is_stunned()
        except Exception:
            stunned = False

        if stunned:
            _combat_log("stunned; passing this round.")
            await self._send_pass()

            self._turn_adjust -= 1

            return

        exec_round = real_round - 1 + self._turn_adjust + self._rel_offset

        priority = self._get_priority(real_round, exec_round)

        if priority is None:
            _combat_log("no matching playstyle rule; passing.")
            await self._send_pass()

            return

        # pre-fetch the card list and server spell_list once for the entire
        # priority scan. the hand is stable until we actually cast, so every
        # move check in the loop can reuse these instead of re-reading memory
        try:
            round_castable, round_spells = await asyncio.gather(
                self.get_castable_cards(),
                _get_my_spell_list(self),
            )
        except Exception:
            round_castable, round_spells = None, None

        # activate per-round caches: card-name lookups and enemy/ally/boss
        # resolutions made during the priority scan reuse these instead of
        # re-reading memory each move. torn down in the finally below so
        # anything outside the scan sees the normal uncached path
        self._round_name_cache = {}
        self._round_target_cache = {}

        # pre-warm the name cache in parallel. otherwise _match_candidates
        # reads names lazily, once per (card, line) pair - N×hand_size serial
        # reads instead of one concurrent wave
        if round_castable:
            try:
                name_lists = await asyncio.gather(
                    *[_card_names(c) for c in round_castable],
                    return_exceptions=True,
                )
                for c, nl in zip(round_castable, name_lists):
                    if isinstance(nl, BaseException):
                        continue
                    self._round_name_cache[self._card_key(c)] = nl
            except Exception:
                # pre-warm is best-effort; _names_for will lazy-fill any misses
                pass

        try:
            for line in priority:
                success, willcasted = await self._exec_line(
                    line, castable=round_castable, spells=round_spells
                )
                if _logger is not None and _VERBOSE_LOG:
                    _logger.debug(
                        f"_handle_round_inner: _exec_line success={success} wc={willcasted}"
                    )

                if success:
                    # free-action line: every move was focus/pip only, no
                    # cast. the round isn't spent, so keep scanning for a
                    # move that actually consumes the turn
                    if line.moves and all(
                        getattr(m, "set_focus", None) is not None
                        or getattr(m, "set_pip", None) is not None
                        for m in line.moves
                    ):
                        continue

                    if willcasted:
                        self._turn_adjust -= 1

                    # track stuck state: a bare `pass` line means no progress
                    # this round. too many in a row and we flee, else we'd loop
                    # forever once the hand drains to unusable cards
                    if all(getattr(m, "is_pass", False) for m in line.moves):
                        self._rounds_since_cast += 1
                        await self._maybe_flee_if_stuck()
                    else:
                        self._rounds_since_cast = 0

                    return

            # engine fallback - no priority line matched at all. also a no-progress
            # round; same stuck-detection as above
            _combat_log("nothing matched; passing.")
            self._rounds_since_cast += 1
            if await self._maybe_flee_if_stuck():
                return
            await self._send_pass()
        finally:
            self._round_name_cache = None
            self._round_target_cache = None

    async def _maybe_flee_if_stuck(self) -> bool:
        if self._rounds_since_cast < self._stuck_flee_threshold:
            return False
        if _logger is not None:
            _logger.warning(
                f"Combat: no progress for {self._rounds_since_cast} rounds; "
                f"sending flee to break out of stuck state."
            )
        try:
            await self.client.send_combat_flee()
            await self._packet_pause()
            self._clear_member_cache()
            self._rounds_since_cast = 0
            return True
        except Exception as exc:
            if _logger is not None:
                _logger.warning(
                    f"Combat: stuck-flee failed ({type(exc).__name__}: {exc}); "
                    f"falling back to pass."
                )
            return False

    def _get_priority(
        self, real_round: int, exec_round: int
    ) -> list[PriorityLine] | None:
        cfg = self._config

        round_lines = cfg.round_map.get(real_round)
        general_lines = cfg.lines or []

        if round_lines:
            return round_lines + general_lines
        return general_lines or None

    def _reset_round_state(self):

        self._turn_adjust = 0

        self._rel_offset = 0

        self._prev_card_count = 0

        self._did_first_round = False

        self._rounds_since_cast = 0

    async def _exec_line(
        self, line: PriorityLine, *, castable=None, spells=None
    ) -> tuple[bool, bool]:

        willcasted = False

        for move in line.moves:
            ok, wc = await self._exec_move(move, castable=castable, spells=spells)

            if not ok:
                return False, False

            if wc:
                willcasted = True

        return True, willcasted

    async def _exec_move(
        self, move: MoveConfig, *, castable=None, spells=None
    ) -> tuple[bool, bool]:

        if not await self._check_condition(move):
            return False, False

        if move.set_focus is not None:
            # free action: write the school and continue. counts as success so
            # _exec_line keeps walking the & chain, and _handle_round_inner's
            # focus-only check keeps scanning instead of ending the round
            await self._write_focus_school(move.set_focus)
            _combat_log(f"focus → {move.set_focus}")
            return True, False

        if move.set_pip is not None:
            # free action: click the SchoolPipPanel to assign an
            # unassigned school pip. same continuation semantics as
            # set_focus - line success without consuming the round
            try:
                from src.utils import assign_school_pip

                clicked = await assign_school_pip(self.client, move.set_pip)
                _combat_log(
                    f"pip → {move.set_pip}"
                    + ("" if clicked else " (panel not up, skipped)")
                )
            except Exception as exc:
                if _logger is not None:
                    _logger.warning(
                        f"Combat: pip click failed ({type(exc).__name__}: {exc})"
                    )
            return True, False

        if move.is_pass:
            _combat_log("playstyle chose pass.")
            await self._send_pass()

            return True, False

        if move.is_willcast:
            return await self._try_willcast()

        if move.draw_count > 0:
            return await self._try_draw(move.draw_count), False

        if move.is_discard:
            return await self._try_discard(), False

        if move.petcast_spell is not None:
            return await self._try_petcast(move)

        # preserve the original 3-way parallelism when a round-level
        # spell_list isn't already available (pre-fetch failure path)
        if spells is None:
            target, candidates, spells = await asyncio.gather(
                self._resolve_target(move),
                self._get_candidates(move, castable=castable),
                _get_my_spell_list(self),
            )
        else:
            target, candidates = await asyncio.gather(
                self._resolve_target(move),
                self._get_candidates(move, castable=castable),
            )

        _dbg(
            f"move spell={move.spell!r} target_kind={move.target!r}"
            f"(n={move.target_n}) → resolved={await _member_label(target)}"
        )

        if target is False:
            _dbg("target resolution failed → skipping move")
            return False, False

        if not candidates:
            if _logger is not None:
                try:
                    hand = await _hand_label(await self.get_cards())
                except Exception:
                    hand = "unknown"
                _logger.debug(
                    f"Combat: skipped {_move_label(move)}; card not in hand. Hand: {hand}."
                )
            return False, False

        try:
            cand_names = [await c.name() for c in candidates]
            _dbg(f"candidates: {cand_names}")
        except Exception:
            pass

        cur_card = await self._post_filter(candidates, move, target)

        if cur_card is None:
            return False, False

        if _logger is not None and _VERBOSE_LOG:
            try:
                _logger.debug(
                    f"_exec_move: post_filter picked {await cur_card.name()!r} "
                    f"(move.spell={move.spell!r} enchant={move.enchant!r})"
                )
            except Exception:
                pass

        if target and not isinstance(target, list):
            if await _card_is_multi_target(cur_card):
                target = [target]

        try:
            already_enchanted = await cur_card.is_enchanted()
        except Exception:
            already_enchanted = False
        if move.enchant and not already_enchanted:
            target = await self._refresh_target(move, target)
            if target is False:
                return False, False
            return await self._enchant_and_cast(cur_card, move, target, spells=spells)

        return await self._cast_with_retry(cur_card, target, move, spells=spells)

    async def _get_candidates(
        self, move: MoveConfig, castable=None
    ) -> list[CombatCard]:

        spell = move.spell

        if spell is None:
            return []

        if castable is None:
            castable = await self.get_castable_cards()
        candidates = await self._exclude_enchant_cards(
            await self._match_candidates(move, castable), move
        )

        if candidates or isinstance(spell, TemplateReq):
            return candidates

        try:
            all_cards = await self.get_cards()
        except Exception:
            all_cards = []

        visible_candidates = await self._exclude_enchant_cards(
            await self._match_candidates(move, all_cards), move
        )
        if not visible_candidates:
            return []

        # the first planning tick can expose the card in hand before
        # maybe_spell_grayed settles. give it a few short polls, then fall
        # back to the visible hand so priority does not incorrectly skip it
        for _ in range(3):
            await asyncio.sleep(0.15)
            fresh = await self.get_castable_cards()
            candidates = await self._exclude_enchant_cards(
                await self._match_candidates(move, fresh), move
            )
            if candidates:
                return candidates

        return visible_candidates

    async def _match_candidates(
        self, move: MoveConfig, cards: list[CombatCard]
    ) -> list[CombatCard]:

        spell = move.spell

        if spell is None:
            return []

        if isinstance(spell, TemplateReq):
            out = []

            for c in cards:
                try:
                    matches = await card_matches_reqs(c, spell.types)
                    nm = await c.name()
                    _dbg(f"  template {spell.types}: {nm!r} matches={matches}")
                    if matches:
                        out.append(c)
                except Exception as exc:
                    _dbg(f"  card_matches_reqs raised: {type(exc).__name__}: {exc}")

            return out

        try:
            target = spell.lower()

            for c in cards:
                for nm in await self._names_for(c):
                    if target == nm.lower():
                        return [c]

            out = []

            for c in cards:
                for nm in await self._names_for(c):
                    if target in nm.lower():
                        out.append(c)
                        break

            return out

        except Exception as exc:
            _dbg(f"_get_candidates named branch raised: {type(exc).__name__}: {exc}")
            return []

    async def _exclude_enchant_cards(
        self, candidates: list[CombatCard], move: MoveConfig
    ) -> list[CombatCard]:
        needles = [e.lower() for e in (move.enchant, move.enchant2) if e]
        if not needles or not candidates:
            return candidates
        out = []
        for c in candidates:
            try:
                names = [n.lower() for n in await self._names_for(c)]
            except Exception:
                out.append(c)
                continue
            if any(needle in nm for nm in names for needle in needles):
                continue
            out.append(c)
        return out

    async def _post_filter(
        self, candidates: list[CombatCard], move: MoveConfig, target
    ) -> CombatCard | None:

        for card in candidates:
            try:
                if not await self._passes_all_specs(card, move, target):
                    continue

                return card

            except (ValueError, WizWalkerMemoryError):
                continue

        return None

    async def _passes_all_specs(
        self, card: CombatCard, move: MoveConfig, target
    ) -> bool:

        getattr(move, "_verbs", [])

        return True

    async def _resolve_target(self, move: MoveConfig):

        tgt = move.target

        if tgt is None:
            return None

        if tgt == "self":
            # resolve to the caster's own member so _subcircle_of encodes their
            # subcircle bit. raw 0 ("no target") gets silently rejected - the
            # enchant applies but the self-buff never casts. None only if the
            # client member can't be read
            return await self.get_client_member() or None

        if tgt == "boss":
            res = await self.get_boss_or_none() or await self._first_enemy()
            return res if res is not None else False

        if tgt == "enemy":
            if move.target_n:
                res = await self.get_nth_enemy_or_none(move.target_n - 1)
            else:
                res = await self._first_enemy()
            return res if res is not None else False

        if tgt == "ally":
            if move.target_n:
                res = await self.get_nth_ally_or_none(move.target_n - 1)
            else:
                res = await self._first_ally()
            return res if res is not None else False

        if tgt == "aoe":
            # packet API needs an enemy-team bitmask for AOE; fall through
            # the list path in _subcircle_of, which returns _ENEMY_AOE_BITMASK
            # for a pure-enemy list
            enemies = await self.get_enemies()
            return enemies if enemies else False

        if tgt == "enemies":
            return await self.get_enemies()

        if tgt == "allies":
            return await self.get_allies()

        if tgt == "spell":
            return await self._resolve_spell_target(move)

        try:
            return await self.get_member_vaguely_named(tgt, timeout=1.0)

        except Exception:
            return False

    async def _resolve_spell_target(self, move: MoveConfig) -> CombatCard | None:

        ts = move.target_spell

        if ts is None:
            return None

        cards = await self.get_castable_cards()

        for c in cards:
            if not (await c.is_enchanted() or await c.is_enchanted_from_item_card()):
                continue

            if isinstance(ts, TemplateReq):
                if await card_matches_reqs(c, ts.types):
                    return c

            elif isinstance(ts, str) and ts.lower() in (await c.name()).lower():
                return c

        for c in cards:
            if isinstance(ts, TemplateReq):
                if await card_matches_reqs(c, ts.types):
                    return c

            elif isinstance(ts, str) and ts.lower() in (await c.name()).lower():
                return c

        return None

    async def _first_enemy(self) -> CombatMember | None:

        enemies = await self.get_enemies()

        return enemies[0] if enemies else None

    async def _first_ally(self) -> CombatMember | None:

        allies = await self.get_allies()

        return allies[0] if allies else None

    async def _await_enchant_consumed(
        self,
        enchant_tid: int | None,
        initial_count: int,
        *,
        timeout: float = 1.0,
    ) -> bool:
        if enchant_tid is None:
            return False
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            if self._should_exit:
                return False
            spells = await _get_my_spell_list(self)
            # wait until there are fewer copies of enchant_tid than before the
            # packet. counting copies (not just absence) handles 2+ of the same
            # TC in hand. if spells isn't readable (mocked tests, flaky hand
            # reads) fall back to castable_cards, the same mirror _hand_index_of
            # uses
            if spells:
                current_count = 0
                for s in spells:
                    try:
                        if await s.template_id() == enchant_tid:
                            current_count += 1
                    except Exception:
                        continue
                spell_list_clear = current_count < initial_count
            else:
                spell_list_clear = True
                try:
                    castable = await self.get_castable_cards()
                    for c in castable:
                        try:
                            if await c.template_id() == enchant_tid:
                                spell_list_clear = False
                                break
                        except Exception:
                            continue
                except Exception:
                    pass
            if spell_list_clear:
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.1)

    async def _enchant_and_cast(
        self, card: CombatCard, move: MoveConfig, target, *, spells=None
    ) -> tuple[bool, bool]:
        # gather: find both enchant cards. (The cast subcircle is resolved by
        # _cast_with_retry from the live target, so we don't precompute it.)
        castable = await self.get_castable_cards()
        enchant1, enchant2_card = await asyncio.gather(
            self._find_castable_from(move.enchant, castable),
            self._find_castable_from(move.enchant2, castable)
            if move.enchant2
            else _areturn(None),
        )
        if enchant1 is None:
            _combat_log(
                f"{move.enchant} is not available; trying {await _card_label(card)} without it."
            )
            return await self._cast_with_retry(card, target, move, spells=spells)

        # capture identity (label + template_ids) for every card up front
        # both `card.name()` and `card.template_id()` read live from the
        # SpellCheckBox window the CombatCard wraps. once we queue a cast,
        # the client recycles those windows for whichever cards slide into
        # the freed slots, so a read after the fact silently returns the
        # wrong (but plausible) name. we capture once and reuse from here.
        card_label = await _card_label(card)
        try:
            card_tid = await card.template_id()
        except Exception:
            card_tid = None
        try:
            e1_tid = await enchant1.template_id()
        except Exception:
            e1_tid = None
        try:
            e2_tid = await enchant2_card.template_id() if enchant2_card else None
        except Exception:
            e2_tid = None

        # reuse caller-provided spell_list; fetch only if not already available
        if spells is None:
            spells = await _get_my_spell_list(self)
        e1_idx = await _index_of_tid(spells, e1_tid, handler=self)
        t_idx = await _index_of_tid(spells, card_tid, handler=self)
        if e1_idx is None or t_idx is None:
            return await self._cast_with_retry(card, target, move)

        if _logger is not None and _VERBOSE_LOG:
            _logger.debug(
                f"_enchant_and_cast: e1={move.enchant!r}[{e1_idx}] "
                f"e2={move.enchant2!r} target={card_label!r}[{t_idx}]"
            )

        # count pre-enchant copies of the enchant tid in spell_list. settle
        # waits for this count to drop, so we must snapshot it BEFORE sending
        # the packet. handles duplicate-TC hands correctly (two Epics, etc.).
        e1_initial_count = 0
        if spells and e1_tid is not None:
            for _s in spells:
                try:
                    if await _s.template_id() == e1_tid:
                        e1_initial_count += 1
                except Exception:
                    continue

        # send first enchant
        try:
            await self.client.send_combat_enchant(e1_idx, t_idx)
            await self._packet_pause()
        except (RuntimeError, WizWalkerMemoryError):
            return False, False

        # packet sent. any failure past here means we already burned a TC, so
        # commit the round (pass + return True) instead of falling through and
        # cascade-enchanting another card. clear the name cache too -
        # window→spell mappings break once the server compacts spell_list
        self._round_name_cache = {}

        # wait for the enchant to register first. send_combat_enchant consumes
        # the TC and shifts every later slot, so casting on a stale index hits
        # the wrong/freed slot and the server silently drops it (the "enchants
        # but casts next round" hang). settling on the card leaving the hand
        # keeps the cast index correct
        settled = await self._await_enchant_consumed(e1_tid, e1_initial_count)

        # optional second enchant - apply it to the now-enchanted card at its
        # live index, then wait for it to register too. only once the first
        # enchant has settled, so the indices we resolve are valid
        if settled and e2_tid is not None:
            post = await _get_my_spell_list(self)
            target_card = await self._refind_after_enchant(move, card_label)
            e2_idx = await _index_of_tid(post, e2_tid, handler=self)
            tgt_idx = (
                await _hand_index_of(self, target_card, spells=post)
                if target_card is not None
                else None
            )
            if e2_idx is not None and tgt_idx is not None:
                # count pre-enchant copies for the count-decrease settle
                e2_initial_count = 0
                if post:
                    for _s in post:
                        try:
                            if await _s.template_id() == e2_tid:
                                e2_initial_count += 1
                        except Exception:
                            continue
                try:
                    await self.client.send_combat_enchant(e2_idx, tgt_idx)
                    await self._packet_pause()
                    # clear cache again - second enchant compacts the list too
                    self._round_name_cache = {}
                    await self._await_enchant_consumed(e2_tid, e2_initial_count)
                except (RuntimeError, WizWalkerMemoryError):
                    pass  # cast with just the first enchant applied

        # cast it, re-finding from a fresh hand read. don't reuse the pre-enchant
        # card ref - its window may have been recycled onto a different spell
        # after spell_list compaction. if refind really can't find it (pet
        # may-cast ate it, fizzle shuffle), fail and fall through; the cache
        # clear above stops that from cascade-enchanting the next line
        refound = await self._refind_after_enchant(move, card_label)
        ok, wc = (False, False)
        if refound is not None:
            spells = await _get_my_spell_list(self)
            ok, wc = await self._cast_with_retry(refound, target, move, spells=spells)
        if ok:
            _combat_log(
                f"queued {card_label} with {move.enchant}"
                f"{' and ' + move.enchant2 if move.enchant2 else ''}."
            )
        return ok, wc

    async def _refind_after_enchant(
        self, move: MoveConfig, card_label: str
    ) -> CombatCard | None:
        try:
            fresh = await self.get_castable_cards()
        except Exception:
            return None
        if not fresh:
            return None

        matches = await self._match_candidates(move, fresh)

        for c in matches:
            try:
                if await c.is_enchanted() or await c.is_enchanted_from_item_card():
                    return c
            except Exception:
                continue

        if matches:
            return matches[0]

        # move no longer matches the enchanted variant (e.g. name changed):
        # fall back to a direct name match against the captured label
        want = (card_label or "").lower()
        if want:
            for c in fresh:
                try:
                    if want in (await c.name()).lower():
                        return c
                except Exception:
                    continue
        return None

    async def _find_castable(self, name: str) -> CombatCard | None:

        try:
            target = name.lower()

            for c in await self.get_castable_cards():
                for nm in await self._names_for(c):
                    if target in nm.lower():
                        return c

        except Exception:
            pass

        return None

    async def _find_castable_from(
        self, name: str, cards: list[CombatCard]
    ) -> CombatCard | None:
        try:
            target = name.lower()
            for c in cards:
                for nm in await self._names_for(c):
                    if target in nm.lower():
                        return c
        except Exception:
            pass
        return None

    async def _find_castable_literal(self, name: str) -> CombatCard | None:

        try:
            for c in await self.get_castable_cards():
                for nm in await self._names_for(c):
                    if nm == name:
                        return c

        except Exception:
            pass

        return None

    async def _cast_with_retry(
        self, card: CombatCard, target, move: MoveConfig, *, spells=None
    ) -> tuple[bool, bool]:

        attempts = 0
        max_attempts = 2

        try:
            spell_name = await card.name()
        except Exception:
            spell_name = "?"

        _dbg(f"casting {spell_name!r} → {await _member_label(target)}")

        # reuse caller-provided spell_list; fetch only if not already available
        if spells is None:
            spells = await _get_my_spell_list(self)

        while attempts < max_attempts:
            attempts += 1

            # resolve hand index and subcircle in parallel
            hand_idx, sub = await asyncio.gather(
                _hand_index_of(self, card, spells=spells),
                _subcircle_of(target),
            )
            if hand_idx is None:
                _dbg(f"cast {spell_name!r}: card no longer in hand")
                return False, False

            if _logger is not None and _VERBOSE_LOG:
                tgt_info = f"type={type(target).__name__}"
                try:
                    if isinstance(target, list):
                        parts = []
                        for t in target:
                            tnm = await t.name()
                            tpart = await t.get_participant()
                            parts.append(
                                f"{tnm}(t={await tpart.team_id()},s={await tpart.subcircle()})"
                            )
                        tgt_info = f"list[{len(target)}]={parts}"
                    elif target is not None and target is not False:
                        tnm = await target.name()
                        tpart = await target.get_participant()
                        tgt_info = f"name={tnm!r} team={await tpart.team_id()} sub={await tpart.subcircle()}"
                except Exception as exc:
                    tgt_info = f"err: {exc}"
                try:
                    member_dump = []
                    for m in await self.get_members():
                        nm = await m.name()
                        p = await m.get_participant()
                        member_dump.append(
                            f"{nm}(t={await p.team_id()},s={await p.subcircle()})"
                        )
                except Exception:
                    member_dump = ["?"]
                try:
                    full = [await c.name() for c in await self.get_cards()]
                except Exception:
                    full = ["?"]
                try:
                    castable = [await c.name() for c in await self.get_castable_cards()]
                except Exception:
                    castable = ["?"]
                _logger.debug(
                    f"send_combat_spell: spell={spell_name!r} hand_idx={hand_idx} "
                    f"sub={sub} target=[{tgt_info}] members={member_dump}"
                )
                _logger.debug(f"  wizwalker full hand:     {full}")
                _logger.debug(f"  wizwalker castable hand: {castable}")
                if spells:
                    names = []
                    for s in spells:
                        try:
                            tpl = await s.spell_template()
                            nm = await tpl.name() if tpl else "?"
                        except Exception:
                            nm = "?"
                        try:
                            tid = await s.template_id()
                        except Exception:
                            tid = "?"
                        names.append(f"{nm}#{tid}")
                    _logger.debug(f"  server hand (spell_list): {names}")
                try:
                    wt = await card.template_id()
                    wn = await card.name()
                except Exception:
                    wt = wn = "?"
                _logger.debug(
                    f"  matched card: name={wn!r} tid={wt} -> hand_idx={hand_idx}"
                )

            if _logger is not None and _VERBOSE_LOG:
                _logger.debug(
                    f"send_combat_spell {spell_name!r}: hand_idx={hand_idx} sub={sub}"
                )

            try:
                await self.client.send_combat_spell(hand_idx, sub)
                await self._packet_pause()
                self._clear_member_cache()
            except (RuntimeError, WizWalkerMemoryError, ValueError) as exc:
                if _logger is not None:
                    _logger.warning(
                        f"Combat: could not queue {spell_name} "
                        f"(attempt {attempts}/{max_attempts}, {type(exc).__name__}: {exc})."
                    )

                card = await self._refind(move)
                if card is None:
                    return False, False

                target = await self._refresh_target(move, target)
                if target is False:
                    return False, False

                spells = await _get_my_spell_list(self)
                continue

            _combat_log(f"queued {spell_name}.")
            return True, False

        return False, False

    async def _refresh_target(self, move: MoveConfig, prev):

        if isinstance(prev, list):
            new = await self._resolve_target(move)

            if new is False or new is None:
                return False

            return [new] if not isinstance(new, list) else new

        new = await self._resolve_target(move)

        if new is False:
            return False

        return new

    async def _refind(self, move: MoveConfig) -> CombatCard | None:

        if isinstance(move.spell, TemplateReq):
            candidates = await self._get_candidates(move)

            return candidates[0] if candidates else None

        if isinstance(move.spell, str):
            return await self._find_castable(move.spell)

        return None

    async def _try_petcast(self, move: MoveConfig) -> tuple[bool, bool]:
        try:
            target = await self._resolve_target(move)
            if target is False:
                return False, False
            sub = await _subcircle_of(target)
            await self.client.send_pet_willcast(move.petcast_spell, sub)
            await self._packet_pause()
            self._clear_member_cache()
            if _logger is not None and _VERBOSE_LOG:
                _logger.debug(f"petcast {move.petcast_spell!r}: sent sub={sub}")
            return True, False
        except Exception as exc:
            if _logger is not None:
                _logger.warning(
                    f"_try_petcast {move.petcast_spell!r} failed: "
                    f"{type(exc).__name__}: {exc}"
                )
            return False, False

    async def _try_willcast(self) -> tuple[bool, bool]:

        try:
            cards = await self.get_castable_cards()
            spells = await _get_my_spell_list(self)

            for c in cards:
                if await c.is_item_card() or await c.is_cloaked():
                    idx = await _hand_index_of(self, c, spells=spells)
                    if idx is None:
                        continue
                    try:
                        await self.client.send_combat_spell(idx, _NO_TARGET)
                        await self._packet_pause()
                        self._clear_member_cache()
                    except (RuntimeError, WizWalkerMemoryError):
                        continue

                    return True, True

        except Exception:
            pass

        return False, False

    async def _try_draw(self, count: int) -> bool:

        for _ in range(count):
            hand_count, _ = await self.get_card_counts()

            if hand_count >= 7:
                break

            try:
                grayed = await self._draw_button_grayed()

                if grayed:
                    break

                await self.client.send_combat_draw()
                await self._packet_pause()

            except Exception:
                break

        return True

    async def _try_discard(self) -> bool:

        try:
            cards = await self.get_castable_cards()

            if cards:
                spells = await _get_my_spell_list(self)
                idx = await _hand_index_of(self, cards[0], spells=spells)
                if idx is None:
                    return False
                await self.client.send_combat_discard(idx)
                await self._packet_pause()
                return True

        except Exception:
            pass

        return False

    async def _draw_button_grayed(self) -> bool:

        try:
            wins = await self.client.root_window.get_windows_with_name("Draw")

            if wins:
                return await wins[0].is_control_grayed()

        except Exception:
            pass

        return True

    async def _check_condition(self, move: MoveConfig) -> bool:

        if move.lua_condition is not None:
            try:
                return bool(move.lua_condition())

            except Exception:
                return False

        cond = move.condition

        if cond is None:
            return True

        try:
            member = await self._condition_member(cond.subject)

            if member is None:
                return True

            raw = await _read_member_attr(member, cond.attr)

            if cond.percent:
                max_val = await _read_member_attr(member, f"max_{cond.attr}")

                raw = (raw / max_val * 100) if max_val else 0

            return _compare(raw, cond.op, cond.value)

        except Exception:
            return True

    async def _condition_member(self, subject: str) -> CombatMember | None:

        if subject == "self":
            return await self.get_client_member()

        if subject == "boss":
            return await self.get_boss_or_none()

        if subject == "enemy":
            return await self._first_enemy()

        if subject == "ally":
            return await self._first_ally()

        return None

    async def _get_card_count(self) -> int:

        try:
            hand, _ = await self.get_card_counts()

            return hand

        except Exception:
            return 0

    # helpers required by the move executor

    async def get_cards(self) -> list[CombatCard]:
        windows = await self._get_card_windows()
        if not windows:
            return []
        rev = windows[::-1]
        flag_results = await asyncio.gather(*[w.flags() for w in rev])
        return [
            CombatCard(self, w)
            for w, flags in zip(rev, flag_results)
            if WindowFlags.visible in flags
        ]

    async def get_castable_cards(self) -> list[CombatCard]:

        cards = await self.get_cards()
        if not cards:
            return cards

        async def _check(c: CombatCard) -> bool:
            try:
                return await c.is_castable()
            except Exception as exc:
                # treat as castable on a flaky read so the round still progresses
                _dbg(
                    f"is_castable raised for a card, treating as castable:"
                    f" {type(exc).__name__}: {exc}"
                )
                return True

        flags = await asyncio.gather(*[_check(c) for c in cards])
        out = [c for c, ok in zip(cards, flags) if ok]

        if not out and cards:
            _dbg(
                f"get_castable_cards: hand={len(cards)} but all is_castable=False;"
                f" returning hand as fallback"
            )
            return cards

        return out

    async def get_castable_card_named(self, name: str) -> CombatCard | None:
        target = name.lower()
        for c in await self.get_castable_cards():
            for nm in await self._names_for(c):
                if target == nm.lower():
                    return c
        return None

    async def _my_team_and_id(self) -> tuple[int | None, str | None]:
        try:
            me = await self.get_client_member()
            part = await me.get_participant()
            return await part.team_id(), await part.owner_id_full()
        except Exception:
            return None, None

    async def get_enemies(self) -> list[CombatMember]:
        cache = self._round_target_cache
        if cache is not None:
            cached = cache.get("enemies", _UNSET)
            if cached is not _UNSET:
                return cached
        my_team, _ = await self._my_team_and_id()
        out = []
        for m in await self.get_members():
            try:
                if await m.is_dead():
                    continue
                part = await m.get_participant()
                if my_team is None or await part.team_id() != my_team:
                    out.append(m)
            except MemoryInvalidated:
                self._clear_member_cache()
                out = []
                break
            except Exception as exc:
                if _logger is not None:
                    _logger.warning(
                        f"get_enemies: skipped member ({type(exc).__name__}: {exc})"
                    )
        if not out:
            # cached windows may be stale (e.g. a new enemy wave spawned after
            # the previous wave died). refresh and retry once.
            self._clear_member_cache()
            my_team, _ = await self._my_team_and_id()
            for m in await self.get_members():
                try:
                    if await m.is_dead():
                        continue
                    part = await m.get_participant()
                    if my_team is None or await part.team_id() != my_team:
                        out.append(m)
                except MemoryInvalidated:
                    self._clear_member_cache()
                    out = []
                    break
                except Exception as exc:
                    _dbg(
                        f"get_enemies (retry): skipped member: {type(exc).__name__}: {exc}"
                    )
        if cache is not None:
            cache["enemies"] = out
        labels = [await _member_label(m) for m in out]
        _dbg(f"get_enemies (my_team={my_team}) → {labels}")
        return out

    async def get_allies(self) -> list[CombatMember]:
        cache = self._round_target_cache
        if cache is not None:
            cached = cache.get("allies", _UNSET)
            if cached is not _UNSET:
                return cached
        my_team, my_id = await self._my_team_and_id()
        out = []
        for m in await self.get_members():
            try:
                if await m.is_dead():
                    continue
                part = await m.get_participant()
                if (
                    my_team is not None
                    and await part.team_id() == my_team
                    and await part.owner_id_full() != my_id
                ):
                    out.append(m)
            except MemoryInvalidated:
                self._clear_member_cache()
                out = []
                break
            except Exception as exc:
                _dbg(f"get_allies: skipped a member: {type(exc).__name__}: {exc}")
        if cache is not None:
            cache["allies"] = out
        labels = [await _member_label(m) for m in out]
        _dbg(f"get_allies (my_team={my_team}, my_id={my_id}) → {labels}")
        return out

    async def get_boss_or_none(self) -> CombatMember | None:
        cache = self._round_target_cache
        if cache is not None:
            cached = cache.get("boss", _UNSET)
            if cached is not _UNSET:
                return cached
        result: CombatMember | None = None
        for _ in range(2):
            for m in await self.get_members():
                try:
                    if await m.is_boss():
                        result = m
                        break
                except MemoryInvalidated:
                    self._clear_member_cache()
                    break
                except Exception:
                    pass
            else:
                # inner loop ran to completion without finding a boss
                result = None
                break
            if result is not None:
                break
        if cache is not None:
            cache["boss"] = result
        return result

    async def get_nth_enemy_or_none(self, n: int) -> CombatMember | None:
        enemies = await self.get_enemies()
        return enemies[n] if n < len(enemies) else None

    async def get_nth_ally_or_none(self, n: int) -> CombatMember | None:
        allies = await self.get_allies()
        return allies[n] if n < len(allies) else None

    async def get_member_vaguely_named(
        self, name: str, timeout: float = 1.0
    ) -> CombatMember:
        import time

        deadline = time.monotonic() + timeout
        while True:
            for m in await self.get_members():
                try:
                    if name.lower() in (await m.name()).lower():
                        return m
                except MemoryInvalidated:
                    self._clear_member_cache()
                    break
                except Exception:
                    pass
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.1)
        raise ValueError(f"Couldn't find member vaguely named {name!r}")

    async def get_card_counts(self) -> tuple[int, int]:
        try:
            wins = await self.client.root_window.get_windows_with_name("CountText")
            if wins:
                text = await wins[0].maybe_text()
                if text:
                    lines = text.splitlines()
                    raw = lines[1] if len(lines) > 1 else lines[0]
                    raw = raw[8:-9].replace("of", "").strip()
                    parts = raw.split()
                    if len(parts) >= 2:
                        return int(parts[0]), int(parts[1])
        except Exception:
            pass
        cards = await self.get_cards()
        return len(cards), 0


async def _card_names(card: CombatCard) -> list[str]:
    names = []
    try:
        gs = await card.get_graphical_spell()
        tpl = await gs.spell_template()
        n = await tpl.name()
        if n:
            names.append(n)
        try:
            code = await tpl.display_name()
            d = await card.combat_handler.client.cache_handler.get_langcode_name(code)
            if d and d not in names:
                names.append(d)
        except Exception:
            pass
    except Exception:
        pass
    return names


async def _read_member_attr(member: CombatMember, attr: str) -> float:

    mapping = {
        "health": member.health,
        "max_health": member.max_health,
        "mana": member.mana,
        "max_mana": member.max_mana,
    }

    fn = mapping.get(attr)

    if fn:
        return float(await fn())

    return 0.0


async def _card_is_multi_target(card: CombatCard) -> bool:

    from wizwalker.memory.memory_objects.enums import EffectTarget

    try:
        for eff in await card.get_spell_effects():
            tgt = await eff.effect_target()

            if tgt in (
                EffectTarget.multi_target_enemy,
                EffectTarget.multi_target_friendly,
            ):
                return True

    except Exception:
        pass

    return False


def _compare(a: float, op: str, b: float) -> bool:

    return {
        "<": a < b,
        "<=": a <= b,
        ">": a > b,
        ">=": a >= b,
        "==": a == b,
        "!=": a != b,
    }.get(op, False)
