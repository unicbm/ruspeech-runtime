"""Output sinks for dictation and subtitle modes."""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
from typing import Optional

from .output import type_text
from .runtime_types import OutputSink, RecognitionEvent


logger = logging.getLogger(__name__)

_BASE_SCREEN_WIDTH = 1920
_BASE_SCREEN_HEIGHT = 1080
_BASE_OVERLAY_FONT_SIZE = 20
_BASE_OVERLAY_PADDING = 16


def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        logger.debug("Per-monitor DPI awareness unavailable", exc_info=True)

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        logger.debug("System DPI awareness unavailable", exc_info=True)


def _resolve_overlay_layout(
    screen_width: int,
    screen_height: int,
    width: int,
    height: int,
    x: int,
    y: int,
    auto_scale: bool,
) -> dict[str, int]:
    scale = 1.0
    if auto_scale:
        scale = max(1.0, min(screen_width / _BASE_SCREEN_WIDTH, screen_height / _BASE_SCREEN_HEIGHT))

    resolved_width = max(480, int(round(width * scale)))
    resolved_height = max(120, int(round(height * scale)))
    resolved_x = max(0, int(round(x * scale)))
    resolved_y = max(0, int(round(y * scale)))
    padding = max(_BASE_OVERLAY_PADDING, int(round(_BASE_OVERLAY_PADDING * scale)))
    return {
        "width": resolved_width,
        "height": resolved_height,
        "x": resolved_x,
        "y": resolved_y,
        "font_size": max(_BASE_OVERLAY_FONT_SIZE, int(round(_BASE_OVERLAY_FONT_SIZE * scale))),
        "padding": padding,
        "wraplength": max(200, resolved_width - padding * 2),
    }


class TypeTextSink(OutputSink):
    def __init__(self, method: str = "auto", append_newline: bool = False) -> None:
        self.method = method
        self.append_newline = append_newline

    def handle_event(self, event: RecognitionEvent) -> None:
        if event.is_final and event.text:
            type_text(event.text, append_newline=self.append_newline, method=self.method)


class ConsoleSubtitleSink(OutputSink):
    def __init__(self, show_partial: bool = True) -> None:
        self.show_partial = show_partial
        self._last_partial: Optional[str] = None

    def handle_event(self, event: RecognitionEvent) -> None:
        if event.error:
            print(f"[error] {event.error}", flush=True)
            return

        if not event.is_final:
            if not self.show_partial or not event.text or event.text == self._last_partial:
                return
            self._last_partial = event.text
            print(f"[partial] {event.text}", flush=True)
            return

        self._last_partial = None
        if event.text:
            print(f"[final] {event.text}", flush=True)


class OverlaySubtitleSink(OutputSink):
    def __init__(
        self,
        enabled: bool,
        width: int = 960,
        height: int = 180,
        x: int = 120,
        y: int = 120,
        opacity: float = 0.85,
        linger_ms: int = 2500,
        auto_scale: bool = True,
    ) -> None:
        self.enabled = enabled
        self.width = width
        self.height = height
        self.x = x
        self.y = y
        self.opacity = opacity
        self.linger_ms = linger_ms
        self.auto_scale = auto_scale
        self._messages: "queue.Queue[tuple[str, bool] | None]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        if self.enabled:
            self._thread = threading.Thread(target=self._ui_loop, daemon=True, name="SubtitleOverlay")
            self._thread.start()
            self._started.wait(timeout=2.0)

    def handle_event(self, event: RecognitionEvent) -> None:
        if not self.enabled or not event.text:
            return
        try:
            self._messages.put_nowait((event.text, event.is_final))
        except queue.Full:
            logger.warning("Overlay queue is full, dropping subtitle update")

    def close(self) -> None:
        if not self.enabled:
            return
        self._messages.put(None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _ui_loop(self) -> None:
        _enable_dpi_awareness()
        try:
            import tkinter as tk
        except ImportError:
            logger.warning("tkinter unavailable, overlay sink disabled")
            self._started.set()
            return

        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.tk.call("tk", "scaling", max(1.0, root.winfo_fpixels("1i") / 72.0))
        except Exception:
            logger.debug("Tk scaling unavailable", exc_info=True)
        try:
            root.attributes("-alpha", self.opacity)
        except Exception:
            logger.debug("Alpha transparency not supported by current Tk build")
        root.configure(bg="#111111")
        layout = _resolve_overlay_layout(
            root.winfo_screenwidth(),
            root.winfo_screenheight(),
            self.width,
            self.height,
            self.x,
            self.y,
            self.auto_scale,
        )
        root.geometry(f"{layout['width']}x{layout['height']}+{layout['x']}+{layout['y']}")

        label = tk.Label(
            root,
            text="",
            fg="#F6F2E8",
            bg="#111111",
            font=("Segoe UI", layout["font_size"], "bold"),
            wraplength=layout["wraplength"],
            justify="left",
            anchor="w",
            padx=layout["padding"],
            pady=layout["padding"],
        )
        label.pack(fill="both", expand=True)

        hide_job = {"id": None}

        def show_text(text: str, is_final: bool) -> None:
            label.configure(text=text)
            root.deiconify()
            if hide_job["id"] is not None:
                root.after_cancel(hide_job["id"])
                hide_job["id"] = None
            if is_final:
                hide_job["id"] = root.after(self.linger_ms, root.withdraw)

        def poll_queue() -> None:
            while True:
                try:
                    message = self._messages.get_nowait()
                except queue.Empty:
                    break

                if message is None:
                    root.destroy()
                    return

                text, is_final = message
                show_text(text, is_final)

            root.after(50, poll_queue)

        self._started.set()
        root.deiconify()
        root.withdraw()
        root.after(50, poll_queue)
        root.mainloop()


def create_output_sinks(config: dict) -> list[OutputSink]:
    output_cfg = config["output"]
    sinks: list[OutputSink] = []
    sink_names = [str(item).lower() for item in output_cfg.get("sinks", [])]

    if "type_text" in sink_names:
        sinks.append(
            TypeTextSink(
                method=output_cfg.get("method", "auto"),
                append_newline=bool(output_cfg.get("append_newline", False)),
            )
        )

    if "console_subtitles" in sink_names:
        sinks.append(
            ConsoleSubtitleSink(
                show_partial=bool(output_cfg.get("console", {}).get("show_partial", True))
            )
        )

    if "overlay_subtitles" in sink_names:
        overlay_cfg = config.get("overlay", {})
        sinks.append(
            OverlaySubtitleSink(
                enabled=bool(overlay_cfg.get("enabled", True)),
                width=int(overlay_cfg.get("width", 960)),
                height=int(overlay_cfg.get("height", 180)),
                x=int(overlay_cfg.get("x", 120)),
                y=int(overlay_cfg.get("y", 120)),
                opacity=float(overlay_cfg.get("opacity", 0.85)),
                linger_ms=int(overlay_cfg.get("linger_ms", 2500)),
                auto_scale=bool(overlay_cfg.get("auto_scale", True)),
            )
        )

    return sinks
