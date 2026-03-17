"""Global hotkey management for toggle and push-to-talk interactions."""

from __future__ import annotations

import logging
import threading
from typing import Callable

import keyboard


logger = logging.getLogger(__name__)


def _normalize_key_name(name: str) -> str:
    normalized = (name or "").lower()
    aliases = {
        "left ctrl": "ctrl",
        "right ctrl": "ctrl",
        "left shift": "shift",
        "right shift": "shift",
        "left alt": "alt",
        "right alt": "alt",
        "alt gr": "alt",
        "windows": "win",
    }
    return aliases.get(normalized, normalized)


class HotkeyManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._registrations = []

    def register_toggle(self, combo: str, callback: Callable[[], None]) -> None:
        with self._lock:
            hotkey_id = keyboard.add_hotkey(combo, callback)
            self._registrations.append(("hotkey", hotkey_id))
            logger.info("Registered toggle hotkey %s", combo)

    def register_push_to_talk(
        self,
        combo: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        required_keys = {_normalize_key_name(part.strip()) for part in combo.split("+") if part.strip()}
        if not required_keys:
            raise ValueError("push_to_talk combo must contain at least one key")

        state = {"pressed": set(), "active": False}

        def handler(event) -> None:
            key_name = _normalize_key_name(event.name)
            if key_name not in required_keys:
                return

            if event.event_type == "down":
                state["pressed"].add(key_name)
                if not state["active"] and required_keys.issubset(state["pressed"]):
                    state["active"] = True
                    on_press()
                return

            state["pressed"].discard(key_name)
            if state["active"]:
                state["active"] = False
                on_release()

        hook = keyboard.hook(handler)
        self._registrations.append(("hook", hook))
        logger.info("Registered push-to-talk combo %s", combo)

    def cleanup(self) -> None:
        with self._lock:
            for kind, token in self._registrations:
                try:
                    if kind == "hotkey":
                        keyboard.remove_hotkey(token)
                    else:
                        keyboard.unhook(token)
                except Exception as exc:
                    logger.debug("Failed to remove %s registration: %s", kind, exc)
            self._registrations.clear()

        try:
            keyboard.unhook_all()
        except Exception as exc:
            logger.warning("Failed to unhook keyboard listeners: %s", exc)
