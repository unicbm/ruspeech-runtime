from __future__ import annotations

import json
import tempfile
import unittest

from app.config import DEFAULT_CONFIG, apply_cli_overrides, load_config, resolve_hotkey_mode, save_config


class ConfigTests(unittest.TestCase):
    def test_default_config_prefers_dictation(self) -> None:
        config = load_config()
        self.assertEqual(config["mode"], "dictation")
        self.assertEqual(config["source"]["type"], "microphone")
        self.assertEqual(config["source"]["sample_rate"], 8000)
        self.assertEqual(config["output"]["sinks"], ["type_text"])
        self.assertEqual(config["asr"]["backend"], "sherpa-onnx")
        self.assertEqual(config["asr"]["sherpa"]["sample_rate"], 8000)

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
        self.assertEqual(config["asr"]["sherpa"]["sample_rate"], 22050)

    def test_cli_subtitle_override_switches_default_sinks(self) -> None:
        config = apply_cli_overrides(DEFAULT_CONFIG, mode="subtitles")
        self.assertEqual(config["mode"], "subtitles")
        self.assertEqual(config["output"]["sinks"], ["console_subtitles", "overlay_subtitles"])

    def test_cli_dictation_override_restores_default_sink(self) -> None:
        config = apply_cli_overrides(
            DEFAULT_CONFIG,
            mode="subtitles",
        )
        config = apply_cli_overrides(config, mode="dictation")
        self.assertEqual(config["mode"], "dictation")
        self.assertEqual(config["output"]["sinks"], ["type_text"])

    def test_auto_hotkey_mode_prefers_push_to_talk_for_dictation(self) -> None:
        config = load_config()
        self.assertEqual(resolve_hotkey_mode(config), "push_to_talk")

    def test_auto_hotkey_mode_prefers_toggle_for_subtitles(self) -> None:
        config = apply_cli_overrides(DEFAULT_CONFIG, mode="subtitles")
        self.assertEqual(resolve_hotkey_mode(config), "toggle")

    def test_invalid_backend_is_rejected_early(self) -> None:
        with self.assertRaisesRegex(ValueError, "not implemented"):
            apply_cli_overrides(DEFAULT_CONFIG, backend="vosk")

    def test_funasr_backend_is_accepted_for_dictation(self) -> None:
        config = apply_cli_overrides(DEFAULT_CONFIG, backend="funasr")
        self.assertEqual(config["asr"]["backend"], "funasr")

    def test_funasr_backend_rejects_subtitles_mode(self) -> None:
        invalid = json.loads(json.dumps(DEFAULT_CONFIG))
        invalid["mode"] = "subtitles"
        invalid["source"]["type"] = "loopback"
        invalid["output"]["sinks"] = ["console_subtitles", "overlay_subtitles"]
        invalid["asr"]["backend"] = "funasr"
        with self.assertRaisesRegex(ValueError, "only supports dictation"):
            apply_cli_overrides(invalid)

    def test_dictation_mode_requires_type_text_sink(self) -> None:
        invalid = json.loads(json.dumps(DEFAULT_CONFIG))
        invalid["output"]["sinks"] = ["console_subtitles"]
        with self.assertRaisesRegex(ValueError, "type_text"):
            apply_cli_overrides(invalid)

    def test_file_config_without_explicit_sherpa_sample_rate_inherits_source_rate(self) -> None:
        override = {
            "source": {"sample_rate": 22050},
            "asr": {"sherpa": {"model_dir": None, "tokens": None, "model": None}},
        }
        with tempfile.NamedTemporaryFile("w+", suffix=".json", encoding="utf-8", delete=False) as handle:
            json.dump(override, handle)
            path = handle.name

        config = load_config(path)
        self.assertEqual(config["source"]["sample_rate"], 22050)
        self.assertEqual(config["asr"]["sherpa"]["sample_rate"], 22050)

    def test_mismatched_source_and_model_sample_rates_are_rejected(self) -> None:
        invalid = json.loads(json.dumps(DEFAULT_CONFIG))
        invalid["source"]["sample_rate"] = 16000
        invalid["asr"]["sherpa"]["sample_rate"] = 8000
        with self.assertRaisesRegex(ValueError, "must match"):
            apply_cli_overrides(invalid)

    def test_frame_duration_must_produce_at_least_one_sample(self) -> None:
        invalid = json.loads(json.dumps(DEFAULT_CONFIG))
        invalid["source"]["sample_rate"] = 10
        invalid["source"]["frame_ms"] = 1
        invalid["asr"]["sherpa"]["sample_rate"] = 10
        with self.assertRaisesRegex(ValueError, "too small"):
            apply_cli_overrides(invalid)

    def test_missing_model_dir_is_rejected_during_validation(self) -> None:
        invalid = json.loads(json.dumps(DEFAULT_CONFIG))
        invalid["asr"]["sherpa"]["model_dir"] = "models\\missing-model-dir"
        with self.assertRaisesRegex(FileNotFoundError, "model_dir"):
            apply_cli_overrides(invalid)

    def test_save_config_round_trips_validated_payload(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["asr"]["backend"] = "funasr"
        config["source"]["sample_rate"] = 16000
        config["source"]["frame_ms"] = 40

        with tempfile.NamedTemporaryFile("w+", suffix=".json", encoding="utf-8", delete=False) as handle:
            path = handle.name

        saved_path = save_config(config, path)
        loaded = load_config(saved_path)
        self.assertEqual(loaded["asr"]["backend"], "funasr")
        self.assertEqual(loaded["source"]["sample_rate"], 16000)


if __name__ == "__main__":
    unittest.main()
