from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.hotkeys import HotkeyManager, HotkeyRecorder


class HotkeyManagerTests(unittest.TestCase):
    def test_toggle_hotkey_triggers_once_on_release(self) -> None:
        events = []

        def capture_hook(handler, suppress=False):
            events.append((handler, suppress))
            return "token"

        with patch("app.hotkeys.keyboard.hook", side_effect=capture_hook):
            manager = HotkeyManager()
            calls = []
            manager.register_toggle("f2", lambda: calls.append("toggle"))

        self.assertEqual(len(events), 1)
        handler, suppress = events[0]
        self.assertTrue(suppress)
        handler(SimpleNamespace(name="f2", event_type="down"))
        handler(SimpleNamespace(name="f2", event_type="down"))
        handler(SimpleNamespace(name="f2", event_type="up"))
        handler(SimpleNamespace(name="f2", event_type="up"))
        self.assertEqual(calls, ["toggle"])

    def test_toggle_hotkey_for_combo_triggers_when_combo_releases(self) -> None:
        events = []

        def capture_hook(handler, suppress=False):
            events.append((handler, suppress))
            return "token"

        with patch("app.hotkeys.keyboard.hook", side_effect=capture_hook):
            manager = HotkeyManager()
            calls = []
            manager.register_toggle("ctrl+shift+a", lambda: calls.append("toggle"))

        handler, suppress = events[0]
        self.assertTrue(suppress)
        handler(SimpleNamespace(name="ctrl", event_type="down"))
        handler(SimpleNamespace(name="shift", event_type="down"))
        handler(SimpleNamespace(name="a", event_type="down"))
        handler(SimpleNamespace(name="a", event_type="up"))
        handler(SimpleNamespace(name="shift", event_type="up"))
        handler(SimpleNamespace(name="ctrl", event_type="up"))
        self.assertEqual(calls, ["toggle"])

    def test_push_to_talk_suppresses_keys_and_stops_on_release(self) -> None:
        events = []

        def capture_hook(handler, suppress=False):
            events.append((handler, suppress))
            return "token"

        with patch("app.hotkeys.keyboard.hook", side_effect=capture_hook):
            manager = HotkeyManager()
            calls = []
            manager.register_push_to_talk(
                "ctrl+space",
                lambda: calls.append("start"),
                lambda: calls.append("stop"),
            )

        handler, suppress = events[0]
        self.assertTrue(suppress)
        handler(SimpleNamespace(name="ctrl", event_type="down"))
        handler(SimpleNamespace(name="space", event_type="down"))
        handler(SimpleNamespace(name="space", event_type="up"))
        self.assertEqual(calls, ["start", "stop"])

    def test_hotkey_recorder_returns_combo_after_release(self) -> None:
        events = []

        def capture_hook(handler, suppress=False):
            events.append((handler, suppress))
            return "token"

        with patch("app.hotkeys.keyboard.hook", side_effect=capture_hook):
            combos = []
            recorder = HotkeyRecorder(combos.append)
            recorder.start()

        handler, suppress = events[0]
        self.assertTrue(suppress)
        handler(SimpleNamespace(name="ctrl", event_type="down"))
        handler(SimpleNamespace(name="shift", event_type="down"))
        handler(SimpleNamespace(name="shift", event_type="up"))
        handler(SimpleNamespace(name="ctrl", event_type="up"))
        self.assertEqual(combos, ["ctrl+shift"])

    def test_hotkey_recorder_can_cancel_with_escape(self) -> None:
        events = []

        def capture_hook(handler, suppress=False):
            events.append((handler, suppress))
            return "token"

        with patch("app.hotkeys.keyboard.hook", side_effect=capture_hook):
            cancelled = []
            recorder = HotkeyRecorder(lambda _combo: None, on_cancel=lambda: cancelled.append(True))
            recorder.start()

        handler, _ = events[0]
        handler(SimpleNamespace(name="esc", event_type="down"))
        self.assertEqual(cancelled, [True])


if __name__ == "__main__":
    unittest.main()
