"""Output sinks for dictation and subtitle modes."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

from .output import type_text
from .runtime_types import OutputSink, RecognitionEvent


logger = logging.getLogger(__name__)


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
    ) -> None:
        self.enabled = enabled
        self.width = width
        self.height = height
        self.x = x
        self.y = y
        self.opacity = opacity
        self.linger_ms = linger_ms
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
            root.attributes("-alpha", self.opacity)
        except Exception:
            logger.debug("Alpha transparency not supported by current Tk build")
        root.configure(bg="#111111")
        root.geometry(f"{self.width}x{self.height}+{self.x}+{self.y}")

        label = tk.Label(
            root,
            text="",
            fg="#F6F2E8",
            bg="#111111",
            font=("Segoe UI", 20, "bold"),
            wraplength=self.width - 32,
            justify="left",
            anchor="w",
            padx=16,
            pady=16,
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
            )
        )

    return sinks
