"""Global hotkey management for toggle and push-to-talk interactions."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

try:
    import keyboard
except ImportError:  # pragma: no cover - exercised in dependency-light test envs
    class _MissingKeyboardModule:
        def hook(self, *args, **kwargs):
            raise RuntimeError("keyboard package is required for global hotkeys")

        def unhook(self, *args, **kwargs):
            return None

        def remove_hotkey(self, *args, **kwargs):
            return None

        def unhook_all(self) -> None:
            return None

    keyboard = _MissingKeyboardModule()


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
        required_keys = {_normalize_key_name(part.strip()) for part in combo.split("+") if part.strip()}
        if not required_keys:
            raise ValueError("toggle combo must contain at least one key")

        state = {"pressed": set(), "active": False}

        def handler(event) -> None:
            key_name = _normalize_key_name(event.name)
            if key_name not in required_keys:
                return

            if event.event_type == "down":
                state["pressed"].add(key_name)
                if not state["active"] and required_keys.issubset(state["pressed"]):
                    state["active"] = True
                return

            was_active = state["active"]
            state["pressed"].discard(key_name)
            if was_active and not required_keys.issubset(state["pressed"]):
                state["active"] = False
                callback()

        with self._lock:
            hook = keyboard.hook(handler, suppress=True)
            self._registrations.append(("hook", hook))
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

        with self._lock:
            hook = keyboard.hook(handler, suppress=True)
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


class HotkeyRecorder:
    def __init__(
        self,
        on_recorded: Callable[[str], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        self.on_recorded = on_recorded
        self.on_cancel = on_cancel
        self._pressed: list[str] = []
        self._pressed_set: set[str] = set()
        self._hook = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._hook is not None:
                return
            self._pressed.clear()
            self._pressed_set.clear()
            self._hook = keyboard.hook(self._handle_event, suppress=True)

    def stop(self) -> None:
        with self._lock:
            hook = self._hook
            self._hook = None
            self._pressed.clear()
            self._pressed_set.clear()
        if hook is not None:
            try:
                keyboard.unhook(hook)
            except Exception as exc:
                logger.debug("Failed to stop hotkey recorder: %s", exc)

    def _handle_event(self, event) -> None:
        key_name = _normalize_key_name(getattr(event, "name", ""))
        if not key_name:
            return

        if event.event_type == "down":
            if key_name == "esc" and not self._pressed_set:
                self.stop()
                if self.on_cancel is not None:
                    self.on_cancel()
                return
            if key_name not in self._pressed_set:
                self._pressed.append(key_name)
                self._pressed_set.add(key_name)
            return

        if key_name not in self._pressed_set:
            return
        self._pressed_set.discard(key_name)
        if self._pressed_set:
            return

        combo = "+".join(self._pressed)
        self.stop()
        if combo:
            self.on_recorded(combo)
