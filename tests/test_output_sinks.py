from __future__ import annotations

import unittest

from app.output_sinks import _resolve_overlay_layout


class OverlayLayoutTests(unittest.TestCase):
    def test_overlay_layout_scales_for_4k(self) -> None:
        layout = _resolve_overlay_layout(3840, 2160, 960, 180, 120, 120, auto_scale=True)
        self.assertEqual(layout["width"], 1920)
        self.assertEqual(layout["height"], 360)
        self.assertEqual(layout["font_size"], 40)
        self.assertEqual(layout["padding"], 32)

    def test_overlay_layout_stays_base_size_without_auto_scale(self) -> None:
        layout = _resolve_overlay_layout(3840, 2160, 960, 180, 120, 120, auto_scale=False)
        self.assertEqual(layout["width"], 960)
        self.assertEqual(layout["height"], 180)
        self.assertEqual(layout["font_size"], 20)
        self.assertEqual(layout["padding"], 16)


if __name__ == "__main__":
    unittest.main()
