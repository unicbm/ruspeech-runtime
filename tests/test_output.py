from __future__ import annotations

import unittest
from unittest.mock import patch

from app.output import type_text


class TypeTextTests(unittest.TestCase):
    def test_auto_prefers_clipboard_then_unicode_then_type(self) -> None:
        calls = []

        with (
            patch("app.output._try_clipboard_injection", side_effect=lambda payload: calls.append("clipboard") or False),
            patch("app.output._type_with_unicode", side_effect=lambda payload: calls.append("unicode") or False),
            patch("app.output._type_with_keyboard", side_effect=lambda payload: calls.append("type") or True),
        ):
            type_text("privet", method="auto")

        self.assertEqual(calls, ["clipboard", "unicode", "type"])

    def test_clipboard_mode_falls_back_to_unicode_before_type(self) -> None:
        calls = []

        with (
            patch("app.output._try_clipboard_injection", side_effect=lambda payload: calls.append("clipboard") or False),
            patch("app.output._type_with_unicode", side_effect=lambda payload: calls.append("unicode") or True),
            patch("app.output._type_with_keyboard", side_effect=lambda payload: calls.append("type") or True),
        ):
            type_text("privet", method="clipboard")

        self.assertEqual(calls, ["clipboard", "unicode"])


if __name__ == "__main__":
    unittest.main()
