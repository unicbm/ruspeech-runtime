"""Command-line entry for the streaming voice runtime."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

import keyboard

from app import (
    TranscriptionResult,
    VoiceRuntimeController,
    apply_cli_overrides,
    ensure_logging_dir,
    load_config,
    resolve_hotkey_mode,
)
from app.hotkeys import HotkeyManager
from app.logging_config import setup_logging
from app.plugins.dataset_recorder import wrap_result_handler


logger = logging.getLogger(__name__)


_TOGGLE_DEBOUNCE_SECONDS = 0.2
_toggle_lock = threading.Lock()
_last_toggle_time = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Streaming Russian voice runtime")
    parser.add_argument("--config", help="Path to config JSON")
    parser.add_argument("--mode", choices=["dictation", "subtitles"], help="Override runtime mode")
    parser.add_argument("--source", choices=["microphone", "loopback"], help="Override audio source")
    parser.add_argument("--backend", help="Override ASR backend")
    parser.add_argument("--once", action="store_true", help="Run a single capture cycle for debugging")
    parser.add_argument("--save-dataset", action="store_true", help="Persist audio/text pairs")
    parser.add_argument("--dataset-dir", default="dataset", help="Dataset output directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = apply_cli_overrides(
        load_config(args.config),
        mode=args.mode,
        source=args.source,
        backend=args.backend,
    )

    log_dir_abs = ensure_logging_dir(config)
    setup_logging(level=config["logging"].get("level", "INFO"), log_dir=log_dir_abs)

    controller = VoiceRuntimeController(config_path=args.config, config=config, on_result=None)
    controller.on_result = _make_result_handler(controller)
    if args.save_dataset:
        controller.on_result = wrap_result_handler(controller.on_result, controller, args.dataset_dir)

    hotkeys = HotkeyManager()
    hotkey_mode = resolve_hotkey_mode(config)

    try:
        if hotkey_mode == "push_to_talk":
            combo = config["hotkeys"].get("push_to_talk", "f4")
            hotkeys.register_push_to_talk(combo, controller.start, controller.stop)
            logger.info("Runtime ready in push-to-talk mode, hold %s to capture", combo)
        else:
            combo = config["hotkeys"].get("toggle", "f2")
            hotkeys.register_toggle(combo, lambda: _toggle(controller))
            logger.info("Runtime ready in toggle mode, press %s to start/stop", combo)

        if args.once:
            controller.start()
            input("Press Enter to stop and exit...")
            controller.stop()
        else:
            keyboard.wait()
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting")
    finally:
        controller.cleanup()
        hotkeys.cleanup()
        sys.exit(0)


def _make_result_handler(controller: VoiceRuntimeController):
    def _handle_result(result: TranscriptionResult) -> None:
        if result.error:
            logger.error("Recognition failed in session %s: %s", result.session_id, result.error)
            return

        logger.info(
            "Final text [%s/%s]: %s (duration %.2fs, latency %.2fs)",
            controller.mode,
            result.source_kind,
            result.text,
            result.duration,
            result.inference_latency,
        )

    return _handle_result


def _toggle(controller: VoiceRuntimeController) -> None:
    global _last_toggle_time
    now = time.monotonic()
    with _toggle_lock:
        if now - _last_toggle_time < _TOGGLE_DEBOUNCE_SECONDS:
            logger.debug("Ignoring repeated toggle request within debounce window")
            return
        _last_toggle_time = now

    if controller.is_running:
        controller.stop()
    else:
        controller.start()


if __name__ == "__main__":
    main()
