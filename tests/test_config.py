from __future__ import annotations

import json
import tempfile
import unittest

from app.config import DEFAULT_CONFIG, apply_cli_overrides, load_config


class ConfigTests(unittest.TestCase):
    def test_default_config_prefers_dictation(self) -> None:
        config = load_config()
        self.assertEqual(config["mode"], "dictation")
        self.assertEqual(config["source"]["type"], "microphone")
        self.assertEqual(config["output"]["sinks"], ["type_text"])
        self.assertEqual(config["asr"]["backend"], "sherpa-onnx")

    def test_legacy_audio_config_is_migrated(self) -> None:
        legacy = {
            "audio": {"sample_rate": 22050, "block_ms": 40, "device": "USB Mic"},
            "output": {"method": "unicode"},
        }
        with tempfile.NamedTemporaryFile("w+", suffix=".json", encoding="utf-8", delete=False) as handle:
            json.dump(legacy, handle)
            path = handle.name

        config = load_config(path)
        self.assertEqual(config["source"]["sample_rate"], 22050)
        self.assertEqual(config["source"]["frame_ms"], 40)
        self.assertEqual(config["source"]["device"], "USB Mic")
        self.assertEqual(config["output"]["method"], "unicode")
        self.assertEqual(config["output"]["sinks"], ["type_text"])

    def test_cli_subtitle_override_switches_default_sinks(self) -> None:
        config = apply_cli_overrides(DEFAULT_CONFIG, mode="subtitles")
        self.assertEqual(config["mode"], "subtitles")
        self.assertEqual(config["output"]["sinks"], ["console_subtitles", "overlay_subtitles"])


if __name__ == "__main__":
    unittest.main()
