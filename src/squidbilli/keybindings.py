from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import dearpygui.dearpygui as dpg


@dataclass(frozen=True)
class KeyCombo:
    key: int
    shift: bool = False
    ctrl: bool = False
    alt: bool = False


class Actions:
    PLAY_TOGGLE = "play_toggle"
    PLAY_TOGGLE_B = "play_toggle_b"
    BPM_DOWN = "bpm_down"
    BPM_UP = "bpm_up"
    CROSSFADER_FOCUS = "crossfader_focus"
    JUMP_BACK_SMALL = "jump_back_small"
    JUMP_BACK_MED = "jump_back_med"
    JUMP_BACK_LARGE = "jump_back_large"
    LIBRARY_FOCUS_SEARCH = "library_focus_search"
    LIBRARY_NEXT = "library_next"
    LIBRARY_PREV = "library_prev"
    LIBRARY_LOAD_SELECTED = "library_load_selected"
    LIBRARY_LOAD_SELECTED_B = "library_load_selected_b"

    @staticmethod
    def mute_lane(i: int) -> str:
        return f"lane_mute_{i}"

    @staticmethod
    def solo_lane(i: int) -> str:
        return f"lane_solo_{i}"


class KeybindingManager:
    def __init__(self):
        self._bindings: Dict[KeyCombo, str] = {}
        self._handlers: Dict[str, Callable[[], None]] = {}

    def bind(self, combo: KeyCombo, action: str):
        self._bindings[combo] = action

    def on(self, action: str, handler: Callable[[], None]):
        self._handlers[action] = handler

    def handle_keypress(self, key: int) -> bool:
        shift_down = (hasattr(dpg, "mvKey_LShift") and dpg.is_key_down(dpg.mvKey_LShift)) or (
            hasattr(dpg, "mvKey_RShift") and dpg.is_key_down(dpg.mvKey_RShift)
        )
        ctrl_down = (hasattr(dpg, "mvKey_LControl") and dpg.is_key_down(dpg.mvKey_LControl)) or (
            hasattr(dpg, "mvKey_RControl") and dpg.is_key_down(dpg.mvKey_RControl)
        )
        alt_down = (hasattr(dpg, "mvKey_LAlt") and dpg.is_key_down(dpg.mvKey_LAlt)) or (
            hasattr(dpg, "mvKey_RAlt") and dpg.is_key_down(dpg.mvKey_RAlt)
        )

        combo = KeyCombo(
            key=key,
            shift=shift_down,
            ctrl=ctrl_down,
            alt=alt_down,
        )
        action = self._bindings.get(combo)
        if not action:
            return False
        handler = self._handlers.get(action)
        if not handler:
            return False
        handler()
        return True


def default_keybindings() -> KeybindingManager:
    km = KeybindingManager()

    # DearPyGui 2.x naming differences
    space_key = getattr(dpg, "mvKey_Spacebar", getattr(dpg, "mvKey_Space", None))
    enter_key = getattr(dpg, "mvKey_Return", getattr(dpg, "mvKey_Enter", None))

    # Bracket keys are not exposed in some DPG builds; fall back to ASCII codes.
    lbracket_key = getattr(dpg, "mvKey_LBracket", ord("["))
    rbracket_key = getattr(dpg, "mvKey_RBracket", ord("]"))

    if space_key is not None:
        km.bind(KeyCombo(space_key), Actions.PLAY_TOGGLE)
        km.bind(KeyCombo(space_key, shift=True), Actions.PLAY_TOGGLE_B)
    if enter_key is not None:
        km.bind(KeyCombo(enter_key), Actions.LIBRARY_LOAD_SELECTED)
        km.bind(KeyCombo(enter_key, shift=True), Actions.LIBRARY_LOAD_SELECTED_B)

    km.bind(KeyCombo(lbracket_key), Actions.BPM_DOWN)
    km.bind(KeyCombo(rbracket_key), Actions.BPM_UP)

    # Jump back (macOS laptop-friendly)
    # DPG exposes punctuation keys in some builds.
    comma_key = getattr(dpg, "mvKey_Comma", ord(","))
    minus_key = getattr(dpg, "mvKey_Minus", ord("-"))
    back_key = getattr(dpg, "mvKey_Back", None)
    km.bind(KeyCombo(comma_key), Actions.JUMP_BACK_SMALL)
    km.bind(KeyCombo(minus_key), Actions.JUMP_BACK_MED)
    if back_key is not None:
        km.bind(KeyCombo(back_key), Actions.JUMP_BACK_LARGE)

    for i in range(8):
        km.bind(KeyCombo(dpg.mvKey_1 + i), Actions.mute_lane(i))
        km.bind(KeyCombo(dpg.mvKey_1 + i, shift=True), Actions.solo_lane(i))

    km.bind(KeyCombo(getattr(dpg, "mvKey_F", ord("F"))), Actions.LIBRARY_FOCUS_SEARCH)
    km.bind(KeyCombo(dpg.mvKey_Down), Actions.LIBRARY_NEXT)
    km.bind(KeyCombo(dpg.mvKey_Up), Actions.LIBRARY_PREV)

    return km
