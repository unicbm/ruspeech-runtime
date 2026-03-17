from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.hotkeys import HotkeyManager


class HotkeyManagerTests(unittest.TestCase):
    def test_toggle_hotkey_triggers_once_on_release(self) -> None:
        events = []

        def capture_hook(handler):
            events.append(handler)
            return "token"

        with patch("app.hotkeys.keyboard.hook", side_effect=capture_hook):
            manager = HotkeyManager()
            calls = []
            manager.register_toggle("f2", lambda: calls.append("toggle"))

        self.assertEqual(len(events), 1)
        handler = events[0]
        handler(SimpleNamespace(name="f2", event_type="down"))
        handler(SimpleNamespace(name="f2", event_type="down"))
        handler(SimpleNamespace(name="f2", event_type="up"))
        handler(SimpleNamespace(name="f2", event_type="up"))
        self.assertEqual(calls, ["toggle"])

    def test_toggle_hotkey_for_combo_triggers_when_combo_releases(self) -> None:
        events = []

        def capture_hook(handler):
            events.append(handler)
            return "token"

        with patch("app.hotkeys.keyboard.hook", side_effect=capture_hook):
            manager = HotkeyManager()
            calls = []
            manager.register_toggle("ctrl+shift+a", lambda: calls.append("toggle"))

        handler = events[0]
        handler(SimpleNamespace(name="ctrl", event_type="down"))
        handler(SimpleNamespace(name="shift", event_type="down"))
        handler(SimpleNamespace(name="a", event_type="down"))
        handler(SimpleNamespace(name="a", event_type="up"))
        handler(SimpleNamespace(name="shift", event_type="up"))
        handler(SimpleNamespace(name="ctrl", event_type="up"))
        self.assertEqual(calls, ["toggle"])


if __name__ == "__main__":
    unittest.main()
