"""Configuration helpers for the streaming runtime."""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, Optional


DEFAULT_CONFIG: Dict[str, Any] = {
    "mode": "dictation",
    "source": {
        "type": "microphone",
        "device": None,
        "sample_rate": 16000,
        "channels": 1,
        "frame_ms": 20,
    },
    "hotkeys": {
        "mode": "toggle",
        "toggle": "f2",
        "push_to_talk": "f4",
    },
    "asr": {
        "backend": "sherpa-onnx",
        "language": "ru",
        "provider": "cpu",
        "num_threads": 2,
        "enable_endpoint_detection": True,
        "rule1_min_trailing_silence": 1.2,
        "rule2_min_trailing_silence": 0.8,
        "rule3_min_utterance_length": 20.0,
        "sherpa": {
            "model_dir": "models/sherpa-onnx-ru-streaming",
            "tokens": None,
            "encoder": None,
            "decoder": None,
            "joiner": None,
            "model": None,
            "paraformer": None,
            "feature_dim": 80,
            "decoding_method": "greedy_search",
        },
    },
    "output": {
        "method": "auto",
        "append_newline": False,
        "sinks": ["type_text"],
        "console": {"show_partial": True},
    },
    "overlay": {
        "enabled": True,
        "width": 960,
        "height": 180,
        "x": 120,
        "y": 120,
        "opacity": 0.85,
        "linger_ms": 2500,
    },
    "logging": {"dir": "logs", "level": "INFO"},
}


def _merge_dict(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _normalize_legacy_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    config = copy.deepcopy(raw)

    if "source" not in config and "audio" in config:
        audio = config.pop("audio")
        config["source"] = {
            "type": "microphone",
            "device": audio.get("device"),
            "sample_rate": audio.get("sample_rate", DEFAULT_CONFIG["source"]["sample_rate"]),
            "channels": 1,
            "frame_ms": audio.get("block_ms", DEFAULT_CONFIG["source"]["frame_ms"]),
        }

    hotkeys = config.setdefault("hotkeys", {})
    if "mode" not in hotkeys:
        hotkeys["mode"] = "toggle"
    hotkeys.setdefault("toggle", DEFAULT_CONFIG["hotkeys"]["toggle"])
    hotkeys.setdefault("push_to_talk", DEFAULT_CONFIG["hotkeys"]["push_to_talk"])

    asr = config.setdefault("asr", {})
    asr.setdefault("backend", DEFAULT_CONFIG["asr"]["backend"])
    asr.setdefault("language", DEFAULT_CONFIG["asr"]["language"])
    asr.setdefault("provider", DEFAULT_CONFIG["asr"]["provider"])
    asr.setdefault("num_threads", DEFAULT_CONFIG["asr"]["num_threads"])
    asr.setdefault("enable_endpoint_detection", DEFAULT_CONFIG["asr"]["enable_endpoint_detection"])
    asr.setdefault("sherpa", {})

    output = config.setdefault("output", {})
    output.setdefault("method", DEFAULT_CONFIG["output"]["method"])
    output.setdefault("append_newline", DEFAULT_CONFIG["output"]["append_newline"])
    output.setdefault("console", {"show_partial": True})

    mode = str(config.get("mode", DEFAULT_CONFIG["mode"])).lower()
    config["mode"] = "subtitles" if mode == "subtitles" else "dictation"

    source = config.setdefault("source", copy.deepcopy(DEFAULT_CONFIG["source"]))
    source.setdefault("type", DEFAULT_CONFIG["source"]["type"])
    source.setdefault("device", DEFAULT_CONFIG["source"]["device"])
    source.setdefault("sample_rate", DEFAULT_CONFIG["source"]["sample_rate"])
    source.setdefault("channels", DEFAULT_CONFIG["source"]["channels"])
    source.setdefault("frame_ms", DEFAULT_CONFIG["source"]["frame_ms"])

    if "sinks" not in output:
        if config["mode"] == "subtitles":
            output["sinks"] = ["console_subtitles", "overlay_subtitles"]
        else:
            output["sinks"] = ["type_text"]

    config.setdefault("overlay", copy.deepcopy(DEFAULT_CONFIG["overlay"]))
    config.setdefault("logging", copy.deepcopy(DEFAULT_CONFIG["logging"]))
    return config


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    if not path:
        return config

    expanded_path = os.path.expanduser(path)
    if not os.path.exists(expanded_path):
        raise FileNotFoundError(f"Config file not found: {expanded_path}")

    with open(expanded_path, "r", encoding="utf-8") as file:
        overrides = json.load(file)

    normalized = _normalize_legacy_config(overrides)
    return _merge_dict(config, normalized)


def apply_cli_overrides(
    config: Dict[str, Any],
    mode: Optional[str] = None,
    source: Optional[str] = None,
    backend: Optional[str] = None,
) -> Dict[str, Any]:
    merged = copy.deepcopy(config)
    if mode:
        merged["mode"] = mode
        if mode == "subtitles" and merged["output"].get("sinks") == ["type_text"]:
            merged["output"]["sinks"] = ["console_subtitles", "overlay_subtitles"]
    if source:
        merged["source"]["type"] = source
    if backend:
        merged["asr"]["backend"] = backend
    return merged


def ensure_logging_dir(config: Dict[str, Any]) -> str:
    log_dir = config["logging"].get("dir", "logs")
    if not os.path.isabs(log_dir):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(project_root, log_dir)

    os.makedirs(log_dir, exist_ok=True)
    return log_dir
