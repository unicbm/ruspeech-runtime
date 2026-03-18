from __future__ import annotations

import unittest

from app.output_sinks import OverlaySubtitleSink, _OVERLAY_QUEUE_SIZE, _resolve_overlay_layout


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

    def test_overlay_partial_updates_stay_bounded(self) -> None:
        sink = OverlaySubtitleSink(enabled=False)

        for index in range(_OVERLAY_QUEUE_SIZE + 10):
            sink._replace_partial(f"partial-{index}")

        self.assertEqual(sink._messages.qsize(), 1)
        self.assertEqual(sink._messages.get_nowait(), (f"partial-{_OVERLAY_QUEUE_SIZE + 9}", False))

    def test_overlay_final_keeps_latest_partial_and_all_finals(self) -> None:
        sink = OverlaySubtitleSink(enabled=False)

        for index in range(_OVERLAY_QUEUE_SIZE):
            sink._replace_partial(f"partial-{index}")
        sink._enqueue_final("final-text")

        queued = list(sink._messages.queue)
        self.assertIn(("final-text", True), queued)
        self.assertLessEqual(len(queued), _OVERLAY_QUEUE_SIZE)


if __name__ == "__main__":
    unittest.main()
