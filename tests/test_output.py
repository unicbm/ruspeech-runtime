from __future__ import annotations

import ctypes
import unittest
from unittest.mock import patch

from app.output import InputUnion, KeyboardInput, MouseInput, HardwareInput, _iter_utf16_code_units, type_text


class TypeTextTests(unittest.TestCase):
    def test_input_union_includes_largest_windows_members(self) -> None:
        field_names = {name for name, _ in InputUnion._fields_}
        self.assertIn("ki", field_names)
        self.assertIn("mi", field_names)
        self.assertIn("hi", field_names)
        self.assertEqual(
            ctypes.sizeof(InputUnion),
            max(ctypes.sizeof(KeyboardInput), ctypes.sizeof(MouseInput), ctypes.sizeof(HardwareInput)),
        )

    def test_utf16_code_units_support_surrogate_pairs(self) -> None:
        self.assertEqual(_iter_utf16_code_units("д"), [0x0434])
        self.assertEqual(_iter_utf16_code_units("🙂"), [0xD83D, 0xDE42])

    def test_auto_prefers_unicode_then_clipboard_then_type(self) -> None:
        calls = []

        with (
            patch("app.output._try_clipboard_injection", side_effect=lambda payload: calls.append("clipboard") or False),
            patch("app.output._type_with_unicode", side_effect=lambda payload: calls.append("unicode") or False),
            patch("app.output._type_with_keyboard", side_effect=lambda payload: calls.append("type") or True),
        ):
            type_text("privet", method="auto")

        self.assertEqual(calls, ["unicode", "clipboard", "type"])

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
