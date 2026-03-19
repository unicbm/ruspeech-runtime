"""Configuration helpers for the streaming runtime."""

from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any, Dict, Optional

SUPPORTED_MODES = {"dictation", "subtitles"}
SUPPORTED_SOURCES = {"microphone", "loopback"}
SUPPORTED_BACKENDS = {"sherpa-onnx", "funasr"}
RESERVED_BACKENDS = {"vosk", "qwen3-asr", "qwen"}
SUPPORTED_SINKS = {"type_text", "console_subtitles", "overlay_subtitles"}
DEFAULT_CONFIG_FILENAME = "runtime-config.json"


DEFAULT_CONFIG: Dict[str, Any] = {
    "mode": "dictation",
    "source": {
        "type": "microphone",
        "device": None,
        "sample_rate": 8000,
        "channels": 1,
        "frame_ms": 20,
    },
    "hotkeys": {
        "mode": "auto",
        "toggle": "f2",
        "push_to_talk": "f2",
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
            "variant": "t-one-ctc",
            "sample_rate": 8000,
            "feature_dim": 80,
            "decoding_method": "greedy_search",
        },
        "funasr": {
            "language": "zh",
            "batch_size_s": 60,
            "hotword": "",
            "use_vad": True,
            "use_punc": True,
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
        "auto_scale": True,
        "width": 960,
        "height": 180,
        "x": 120,
        "y": 120,
        "opacity": 0.85,
        "linger_ms": 2500,
    },
    "logging": {"dir": "logs", "level": "INFO"},
    "gui": {
        "show_status_prompt": True,
        "always_on_top": False,
    },
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
        hotkeys["mode"] = DEFAULT_CONFIG["hotkeys"]["mode"]
    hotkeys.setdefault("toggle", DEFAULT_CONFIG["hotkeys"]["toggle"])
    hotkeys.setdefault("push_to_talk", DEFAULT_CONFIG["hotkeys"]["push_to_talk"])

    asr = config.setdefault("asr", {})
    asr.setdefault("backend", DEFAULT_CONFIG["asr"]["backend"])
    asr.setdefault("language", DEFAULT_CONFIG["asr"]["language"])
    asr.setdefault("provider", DEFAULT_CONFIG["asr"]["provider"])
    asr.setdefault("num_threads", DEFAULT_CONFIG["asr"]["num_threads"])
    asr.setdefault("enable_endpoint_detection", DEFAULT_CONFIG["asr"]["enable_endpoint_detection"])
    sherpa = asr.setdefault("sherpa", {})
    funasr = asr.setdefault("funasr", {})
    for key, value in DEFAULT_CONFIG["asr"]["funasr"].items():
        funasr.setdefault(key, value)

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
    sherpa.setdefault("sample_rate", source["sample_rate"])

    if "sinks" not in output:
        if config["mode"] == "subtitles":
            output["sinks"] = ["console_subtitles", "overlay_subtitles"]
        else:
            output["sinks"] = ["type_text"]

    config.setdefault("overlay", copy.deepcopy(DEFAULT_CONFIG["overlay"]))
    config.setdefault("logging", copy.deepcopy(DEFAULT_CONFIG["logging"]))
    config.setdefault("gui", copy.deepcopy(DEFAULT_CONFIG["gui"]))
    return config


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    if not path:
        return validate_config(config)

    expanded_path = os.path.expanduser(path)
    if not os.path.exists(expanded_path):
        raise FileNotFoundError(f"Config file not found: {expanded_path}")

    with open(expanded_path, "r", encoding="utf-8") as file:
        overrides = json.load(file)

    normalized = _normalize_legacy_config(overrides)
    return validate_config(_merge_dict(config, normalized))


def get_default_config_path() -> str:
    return os.path.join(get_app_root(), DEFAULT_CONFIG_FILENAME)


def resolve_config_path(path: Optional[str] = None) -> Optional[str]:
    if path:
        return os.path.expanduser(path)
    default_path = get_default_config_path()
    return default_path if os.path.exists(default_path) else None


def save_config(config: Dict[str, Any], path: Optional[str] = None) -> str:
    target_path = os.path.expanduser(path or get_default_config_path())
    validated = validate_config(config)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as file:
        json.dump(validated, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return target_path


def apply_cli_overrides(
    config: Dict[str, Any],
    mode: Optional[str] = None,
    source: Optional[str] = None,
    backend: Optional[str] = None,
) -> Dict[str, Any]:
    merged = copy.deepcopy(config)
    if mode:
        merged["mode"] = str(mode).lower()
        if merged["mode"] == "subtitles" and merged["output"].get("sinks") == ["type_text"]:
            merged["output"]["sinks"] = ["console_subtitles", "overlay_subtitles"]
        elif merged["mode"] == "dictation" and merged["output"].get("sinks") == [
            "console_subtitles",
            "overlay_subtitles",
        ]:
            merged["output"]["sinks"] = ["type_text"]
    if source:
        merged["source"]["type"] = str(source).lower()
    if backend:
        merged["asr"]["backend"] = str(backend).lower()
    return validate_config(merged)


def resolve_hotkey_mode(config: Dict[str, Any]) -> str:
    hotkeys = config.get("hotkeys", {})
    requested = str(hotkeys.get("mode", DEFAULT_CONFIG["hotkeys"]["mode"])).lower()
    if requested == "auto":
        return "push_to_talk" if str(config.get("mode", "dictation")).lower() == "dictation" else "toggle"
    return "push_to_talk" if requested == "push_to_talk" else "toggle"


def ensure_logging_dir(config: Dict[str, Any]) -> str:
    log_dir = config["logging"].get("dir", "logs")
    if not log_dir:
        log_dir = "logs"
    expanded = os.path.expanduser(log_dir)
    if not os.path.isabs(expanded):
        expanded = os.path.join(get_app_root(), expanded)
    log_dir = expanded

    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def get_app_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_root() -> str:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return os.path.abspath(meipass)
    return get_app_root()


def resolve_runtime_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return path
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(get_resource_root(), expanded)


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    validated = copy.deepcopy(config)

    mode = str(validated.get("mode", DEFAULT_CONFIG["mode"])).lower()
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported runtime mode: {mode}")
    validated["mode"] = mode

    source_cfg = validated.setdefault("source", copy.deepcopy(DEFAULT_CONFIG["source"]))
    source_type = str(source_cfg.get("type", DEFAULT_CONFIG["source"]["type"])).lower()
    if source_type not in SUPPORTED_SOURCES:
        raise ValueError(f"Unsupported audio source: {source_type}")
    source_cfg["type"] = source_type
    source_cfg["sample_rate"] = _require_positive_int(source_cfg.get("sample_rate"), "source.sample_rate")
    source_cfg["frame_ms"] = _require_positive_int(source_cfg.get("frame_ms"), "source.frame_ms")
    source_cfg["channels"] = _require_positive_int(source_cfg.get("channels", 1), "source.channels")
    if int(source_cfg["sample_rate"] * source_cfg["frame_ms"] / 1000) <= 0:
        raise ValueError("source.frame_ms is too small for the selected source.sample_rate")

    asr_cfg = validated.setdefault("asr", copy.deepcopy(DEFAULT_CONFIG["asr"]))
    backend_name = str(asr_cfg.get("backend", DEFAULT_CONFIG["asr"]["backend"])).lower()
    if backend_name in RESERVED_BACKENDS:
        raise ValueError(f"ASR backend '{backend_name}' is declared but not implemented")
    if backend_name not in SUPPORTED_BACKENDS:
        raise ValueError(f"Unsupported ASR backend: {backend_name}")
    asr_cfg["backend"] = backend_name
    asr_cfg["num_threads"] = _require_positive_int(asr_cfg.get("num_threads", 2), "asr.num_threads")
    funasr_cfg = asr_cfg.setdefault("funasr", copy.deepcopy(DEFAULT_CONFIG["asr"]["funasr"]))
    funasr_cfg["batch_size_s"] = _require_positive_int(
        funasr_cfg.get("batch_size_s", DEFAULT_CONFIG["asr"]["funasr"]["batch_size_s"]),
        "asr.funasr.batch_size_s",
    )
    funasr_cfg["hotword"] = str(funasr_cfg.get("hotword", DEFAULT_CONFIG["asr"]["funasr"]["hotword"]))
    funasr_cfg["language"] = str(funasr_cfg.get("language", DEFAULT_CONFIG["asr"]["funasr"]["language"]))
    funasr_cfg["use_vad"] = bool(funasr_cfg.get("use_vad", DEFAULT_CONFIG["asr"]["funasr"]["use_vad"]))
    funasr_cfg["use_punc"] = bool(funasr_cfg.get("use_punc", DEFAULT_CONFIG["asr"]["funasr"]["use_punc"]))

    sherpa_cfg = asr_cfg.setdefault("sherpa", copy.deepcopy(DEFAULT_CONFIG["asr"]["sherpa"]))
    sherpa_cfg["sample_rate"] = _require_positive_int(
        sherpa_cfg.get("sample_rate", source_cfg["sample_rate"]),
        "asr.sherpa.sample_rate",
    )
    sherpa_cfg["feature_dim"] = _require_positive_int(
        sherpa_cfg.get("feature_dim", DEFAULT_CONFIG["asr"]["sherpa"]["feature_dim"]),
        "asr.sherpa.feature_dim",
    )
    if backend_name == "sherpa-onnx":
        if sherpa_cfg["sample_rate"] != source_cfg["sample_rate"]:
            raise ValueError(
                "source.sample_rate and asr.sherpa.sample_rate must match until resampling is implemented"
            )
        _validate_optional_paths(
            {
                "asr.sherpa.model_dir": sherpa_cfg.get("model_dir"),
                "asr.sherpa.tokens": sherpa_cfg.get("tokens"),
                "asr.sherpa.encoder": sherpa_cfg.get("encoder"),
                "asr.sherpa.decoder": sherpa_cfg.get("decoder"),
                "asr.sherpa.joiner": sherpa_cfg.get("joiner"),
                "asr.sherpa.model": sherpa_cfg.get("model"),
                "asr.sherpa.paraformer": sherpa_cfg.get("paraformer"),
            }
        )

    output_cfg = validated.setdefault("output", copy.deepcopy(DEFAULT_CONFIG["output"]))
    sinks = [str(item).lower() for item in output_cfg.get("sinks", [])]
    if not sinks:
        raise ValueError("output.sinks must contain at least one sink")
    invalid_sinks = [name for name in sinks if name not in SUPPORTED_SINKS]
    if invalid_sinks:
        raise ValueError(f"Unsupported output sinks: {', '.join(invalid_sinks)}")
    output_cfg["sinks"] = sinks

    if mode == "dictation" and "type_text" not in sinks:
        raise ValueError("dictation mode requires the 'type_text' sink")
    if mode == "subtitles" and not {"console_subtitles", "overlay_subtitles"}.intersection(sinks):
        raise ValueError("subtitles mode requires at least one subtitle sink")
    if backend_name == "funasr":
        if mode != "dictation":
            raise ValueError("ASR backend 'funasr' only supports dictation mode")
        if source_type != "microphone":
            raise ValueError("ASR backend 'funasr' only supports microphone input")

    return validated


def _require_positive_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def _validate_optional_paths(paths: Dict[str, Any]) -> None:
    for field_name, value in paths.items():
        if not value:
            continue
        resolved = resolve_runtime_path(str(value))
        if resolved and not os.path.exists(resolved):
            raise FileNotFoundError(f"{field_name} does not exist: {resolved}")
