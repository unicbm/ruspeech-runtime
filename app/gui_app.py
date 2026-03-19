"""Minimal Tk GUI for the local speech runtime."""

from __future__ import annotations

import copy
import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Optional

from .config import (
    DEFAULT_CONFIG,
    get_default_config_path,
    load_config,
    resolve_config_path,
    resolve_hotkey_mode,
    save_config,
)
from .controller import VoiceRuntimeController
from .hotkeys import HotkeyManager, HotkeyRecorder
from .logging_config import setup_logging
from .output_sinks import _enable_dpi_awareness
from .runtime_types import RuntimeStatus, TranscriptionResult


logger = logging.getLogger(__name__)


class StatusPrompt:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#191919")
        self.label = tk.Label(
            self.window,
            text="",
            fg="#F7F2E8",
            bg="#191919",
            font=("Segoe UI", 12, "bold"),
            padx=14,
            pady=10,
            justify="left",
            anchor="w",
        )
        self.label.pack(fill="both", expand=True)
        self._hide_job: Optional[str] = None

    def show(self, text: str, *, linger_ms: int = 1400, background: str = "#191919") -> None:
        if not text:
            return
        self.label.configure(text=text, bg=background)
        self.window.configure(bg=background)
        self._place()
        self.window.deiconify()
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if linger_ms > 0:
            self._hide_job = self.root.after(linger_ms, self.hide)

    def hide(self) -> None:
        self._hide_job = None
        self.window.withdraw()

    def _place(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(24, screen_width - width - 36)
        y = max(24, screen_height - height - 96)
        self.window.geometry(f"+{x}+{y}")


class RuntimeGuiApp:
    def __init__(self) -> None:
        config_path = resolve_config_path()
        self.config_path = config_path or get_default_config_path()
        self.config_error: Optional[str] = None
        try:
            loaded = load_config(config_path)
        except Exception as exc:
            self.config_error = str(exc)
            loaded = copy.deepcopy(DEFAULT_CONFIG)

        self.config = copy.deepcopy(loaded)
        log_dir = self.config["logging"].get("dir", DEFAULT_CONFIG["logging"]["dir"])
        setup_logging(level=self.config["logging"].get("level", "INFO"), log_dir=log_dir)

        _enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("Uni Speech Runtime")
        self.root.geometry("460x420")
        self.root.minsize(420, 360)
        if self.config.get("gui", {}).get("always_on_top", False):
            self.root.attributes("-topmost", True)

        self.event_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.prompt = StatusPrompt(self.root)
        self.controller: Optional[VoiceRuntimeController] = None
        self.hotkeys: Optional[HotkeyManager] = None
        self.hotkey_recorder: Optional[HotkeyRecorder] = None
        self._closing = False
        self._recording_target: Optional[str] = None
        self._last_prompt_state = ""

        self.mode_var = tk.StringVar(value=self.config.get("mode", "dictation"))
        self.backend_var = tk.StringVar(value=self.config["asr"].get("backend", "sherpa-onnx"))
        self.state_var = tk.StringVar(value="IDLE")
        self.source_var = tk.StringVar(value=self.config["source"].get("type", "microphone"))
        self.hotkey_var = tk.StringVar(value="")
        self.result_var = tk.StringVar(value="还没有识别结果。")
        self.note_var = tk.StringVar(value="")

        self._build_ui()
        self._apply_profile()
        self._rebuild_runtime()
        self._refresh_labels()

        if self.config_error:
            self.note_var.set(f"配置加载失败，已回退默认值: {self.config_error}")
            self.prompt.show("配置加载失败，已使用默认配置", background="#8C3A2B", linger_ms=2200)
        elif config_path is None:
            self.note_var.set(f"首次运行将保存配置到 {self.config_path}")
        else:
            self.note_var.set(f"配置文件: {self.config_path}")

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(60, self._poll_events)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._stop_hotkey_recording()
        self._cleanup_runtime()
        self.prompt.hide()
        self.root.destroy()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(1, weight=1)

        ttk.Label(container, text="模式").grid(row=0, column=0, sticky="w", pady=(0, 8))
        mode_box = ttk.Combobox(
            container,
            textvariable=self.mode_var,
            state="readonly",
            values=("dictation", "subtitles"),
        )
        mode_box.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self._on_profile_changed())

        ttk.Label(container, text="后端").grid(row=1, column=0, sticky="w", pady=(0, 8))
        backend_box = ttk.Combobox(
            container,
            textvariable=self.backend_var,
            state="readonly",
            values=("sherpa-onnx", "funasr"),
        )
        backend_box.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        backend_box.bind("<<ComboboxSelected>>", lambda _event: self._on_profile_changed())

        ttk.Label(container, text="输入源").grid(row=2, column=0, sticky="w", pady=(0, 8))
        ttk.Label(container, textvariable=self.source_var).grid(row=2, column=1, sticky="w", pady=(0, 8))

        ttk.Label(container, text="运行状态").grid(row=3, column=0, sticky="w", pady=(0, 12))
        ttk.Label(container, textvariable=self.state_var).grid(row=3, column=1, sticky="w", pady=(0, 12))

        button_row = ttk.Frame(container)
        button_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(button_row, text="开始", command=self._start_runtime)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.stop_button = ttk.Button(button_row, text="停止", command=self._stop_runtime)
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        hotkey_frame = ttk.LabelFrame(container, text="热键")
        hotkey_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(0, 14))
        hotkey_frame.columnconfigure(1, weight=1)

        ttk.Label(hotkey_frame, text="当前生效").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 8))
        ttk.Label(hotkey_frame, textvariable=self.hotkey_var).grid(row=0, column=1, sticky="w", padx=10, pady=(10, 8))

        ttk.Label(hotkey_frame, text="听写热键").grid(row=1, column=0, sticky="w", padx=10, pady=8)
        self.dictation_hotkey_value = tk.StringVar(value=self.config["hotkeys"].get("push_to_talk", "f2"))
        ttk.Label(hotkey_frame, textvariable=self.dictation_hotkey_value).grid(
            row=1, column=1, sticky="w", padx=10, pady=8
        )
        self.dictation_record_button = ttk.Button(
            hotkey_frame,
            text="录制",
            command=lambda: self._start_hotkey_recording("push_to_talk"),
        )
        self.dictation_record_button.grid(row=1, column=2, sticky="e", padx=10, pady=8)

        ttk.Label(hotkey_frame, text="切换热键").grid(row=2, column=0, sticky="w", padx=10, pady=(0, 10))
        self.toggle_hotkey_value = tk.StringVar(value=self.config["hotkeys"].get("toggle", "f2"))
        ttk.Label(hotkey_frame, textvariable=self.toggle_hotkey_value).grid(
            row=2, column=1, sticky="w", padx=10, pady=(0, 10)
        )
        self.toggle_record_button = ttk.Button(
            hotkey_frame,
            text="录制",
            command=lambda: self._start_hotkey_recording("toggle"),
        )
        self.toggle_record_button.grid(row=2, column=2, sticky="e", padx=10, pady=(0, 10))

        result_frame = ttk.LabelFrame(container, text="最近结果")
        result_frame.grid(row=6, column=0, columnspan=2, sticky="nsew")
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        self.result_label = tk.Label(
            result_frame,
            textvariable=self.result_var,
            bg="#111111",
            fg="#F7F2E8",
            justify="left",
            anchor="nw",
            wraplength=380,
            padx=12,
            pady=10,
            height=6,
        )
        self.result_label.grid(row=0, column=0, sticky="nsew")

        self.note_label = ttk.Label(container, textvariable=self.note_var, foreground="#555555", wraplength=400)
        self.note_label.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        container.rowconfigure(6, weight=1)

    def _apply_profile(self) -> None:
        backend = self.backend_var.get()
        mode = self.mode_var.get()
        if backend == "funasr":
            mode = "dictation"
            self.mode_var.set(mode)
            self.config["source"]["sample_rate"] = 16000
            self.config["source"]["frame_ms"] = 40
            self.config["asr"]["language"] = "zh"
        else:
            self.config["source"]["sample_rate"] = 8000
            self.config["source"]["frame_ms"] = 20
            self.config["asr"]["language"] = "ru"

        self.config["mode"] = mode
        self.config["asr"]["backend"] = backend
        if mode == "subtitles":
            self.config["source"]["type"] = "loopback"
            self.config["source"]["channels"] = 2
            self.config["output"]["sinks"] = ["console_subtitles", "overlay_subtitles"]
        else:
            self.config["source"]["type"] = "microphone"
            self.config["source"]["channels"] = 1
            self.config["output"]["sinks"] = ["type_text"]
        self.source_var.set(self.config["source"]["type"])

    def _on_profile_changed(self) -> None:
        self._apply_profile()
        self._persist_config()
        self._rebuild_runtime()
        self._refresh_labels()

    def _persist_config(self) -> None:
        saved_path = save_config(self.config, self.config_path)
        self.note_var.set(f"配置已保存到 {saved_path}")

    def _rebuild_runtime(self) -> None:
        was_running = bool(self.controller and self.controller.is_running)
        self._cleanup_runtime()

        self.controller = VoiceRuntimeController(
            config=self.config,
            on_result=self._queue_result,
            on_state_change=self._queue_status,
        )
        self.hotkeys = HotkeyManager()
        self._register_hotkeys()
        if was_running:
            self._start_runtime()

    def _cleanup_runtime(self) -> None:
        if self.hotkeys is not None:
            try:
                self.hotkeys.cleanup()
            except Exception:
                logger.exception("Failed to cleanup hotkeys")
            self.hotkeys = None
        if self.controller is not None:
            try:
                self.controller.cleanup()
            except Exception:
                logger.exception("Failed to cleanup controller")
            self.controller = None

    def _register_hotkeys(self) -> None:
        if self.hotkeys is None or self.controller is None:
            return
        hotkey_mode = resolve_hotkey_mode(self.config)
        if hotkey_mode == "push_to_talk":
            combo = self.config["hotkeys"].get("push_to_talk", "f2")
            self.hotkeys.register_push_to_talk(combo, self._start_runtime, self._stop_runtime)
        else:
            combo = self.config["hotkeys"].get("toggle", "f2")
            self.hotkeys.register_toggle(combo, self._toggle_runtime)

    def _toggle_runtime(self) -> None:
        if self.controller is None:
            return
        if self.controller.is_running:
            self._stop_runtime()
        else:
            self._start_runtime()

    def _start_runtime(self) -> None:
        if self.controller is None:
            return
        try:
            self.controller.start()
        except Exception as exc:
            logger.exception("Runtime start failed")
            self.result_var.set(f"启动失败: {exc}")
            self.prompt.show("启动失败，请检查音频设备或模型", background="#8C3A2B", linger_ms=2200)

    def _stop_runtime(self) -> None:
        if self.controller is None:
            return
        try:
            self.controller.stop()
        except Exception as exc:
            logger.exception("Runtime stop failed")
            self.result_var.set(f"停止失败: {exc}")
            self.prompt.show("停止运行时失败", background="#8C3A2B", linger_ms=2200)

    def _start_hotkey_recording(self, target: str) -> None:
        if self.hotkey_recorder is not None:
            return
        if self.hotkeys is not None:
            self.hotkeys.cleanup()
            self.hotkeys = None
        self._recording_target = target
        self._set_hotkey_buttons_enabled(False)
        label = "听写热键" if target == "push_to_talk" else "切换热键"
        self.note_var.set(f"正在录制 {label}，按 Esc 取消")
        self.prompt.show(f"请按下新的{label}\nEsc 取消", background="#243B53", linger_ms=0)
        self.hotkey_recorder = HotkeyRecorder(
            on_recorded=lambda combo: self.event_queue.put(("hotkey", (target, combo))),
            on_cancel=lambda: self.event_queue.put(("hotkey_cancel", target)),
        )
        self.hotkey_recorder.start()

    def _stop_hotkey_recording(self) -> None:
        if self.hotkey_recorder is not None:
            self.hotkey_recorder.stop()
            self.hotkey_recorder = None
        self._recording_target = None
        self.prompt.hide()
        self._set_hotkey_buttons_enabled(True)

    def _set_hotkey_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.dictation_record_button.configure(state=state)
        self.toggle_record_button.configure(state=state)

    def _queue_status(self, status: RuntimeStatus) -> None:
        self.event_queue.put(("status", status))

    def _queue_result(self, result: TranscriptionResult) -> None:
        self.event_queue.put(("result", result))

    def _poll_events(self) -> None:
        while True:
            try:
                event_type, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if event_type == "status":
                self._handle_status(payload)
            elif event_type == "result":
                self._handle_result(payload)
            elif event_type == "hotkey":
                target, combo = payload
                self._apply_recorded_hotkey(target, combo)
            elif event_type == "hotkey_cancel":
                self._handle_hotkey_cancel()

        if not self._closing:
            self.root.after(60, self._poll_events)

    def _handle_status(self, payload: object) -> None:
        status = payload if isinstance(payload, RuntimeStatus) else None
        if status is None:
            return
        self.state_var.set(status.state)
        self.start_button.configure(state="disabled" if status.is_running else "normal")
        self.stop_button.configure(state="normal" if status.state in {"RUNNING", "STOPPING"} else "disabled")
        self._refresh_labels()

        if not self.config.get("gui", {}).get("show_status_prompt", True):
            return

        prompt_text = self._status_prompt_text(status)
        if prompt_text and prompt_text != self._last_prompt_state:
            background = "#191919"
            linger_ms = 1400
            if status.state == "ERROR":
                background = "#8C3A2B"
                linger_ms = 2400
            elif status.state == "RUNNING":
                background = "#1F5132"
            elif status.state == "STOPPING":
                background = "#7A5A00"
            self.prompt.show(prompt_text, background=background, linger_ms=linger_ms)
            self._last_prompt_state = prompt_text

    def _handle_result(self, payload: object) -> None:
        result = payload if isinstance(payload, TranscriptionResult) else None
        if result is None:
            return
        if result.error:
            self.result_var.set(f"识别失败: {result.error}")
            self.prompt.show("识别失败", background="#8C3A2B", linger_ms=2200)
            return
        timestamp = time.strftime("%H:%M:%S")
        self.result_var.set(f"[{timestamp}] {result.text or result.raw_text}")
        self._last_prompt_state = ""

    def _apply_recorded_hotkey(self, target: str, combo: str) -> None:
        self._stop_hotkey_recording()
        self.config["hotkeys"][target] = combo
        self.dictation_hotkey_value.set(self.config["hotkeys"].get("push_to_talk", "f2"))
        self.toggle_hotkey_value.set(self.config["hotkeys"].get("toggle", "f2"))
        self._persist_config()
        if self.hotkeys is None:
            self.hotkeys = HotkeyManager()
        self._register_hotkeys()
        self._refresh_labels()
        self.note_var.set(f"已保存热键: {combo}")
        self.prompt.show(f"已保存热键: {combo}", background="#1F5132", linger_ms=1600)

    def _handle_hotkey_cancel(self) -> None:
        self._stop_hotkey_recording()
        if self.hotkeys is None:
            self.hotkeys = HotkeyManager()
        self._register_hotkeys()
        self.note_var.set("已取消热键录制")
        self.prompt.show("已取消热键录制", background="#243B53", linger_ms=1200)

    def _refresh_labels(self) -> None:
        hotkey_mode = resolve_hotkey_mode(self.config)
        active_key = "push_to_talk" if hotkey_mode == "push_to_talk" else "toggle"
        combo = self.config["hotkeys"].get(active_key, "f2")
        backend_label = self.backend_var.get()
        mode_label = self.mode_var.get()
        self.hotkey_var.set(f"{hotkey_mode}: {combo}")
        if backend_label == "funasr":
            self.note_var.set(f"中文后端启用中，仅支持麦克风听写。当前热键: {combo}")
        elif mode_label == "subtitles":
            self.note_var.set(f"字幕模式使用系统音频输入。当前热键: {combo}")

    def _status_prompt_text(self, status: RuntimeStatus) -> str:
        if status.state == "STARTING":
            return "正在启动识别"
        if status.state == "RUNNING":
            if resolve_hotkey_mode(self.config) == "push_to_talk":
                return "正在录音"
            return "识别运行中"
        if status.state == "STOPPING":
            return "正在转写"
        if status.state == "ERROR":
            return f"运行失败: {status.last_error or '未知错误'}"
        if status.state == "IDLE" and self._last_prompt_state not in {"", "待机"}:
            return "待机"
        return ""
