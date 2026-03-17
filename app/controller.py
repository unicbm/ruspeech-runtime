"""Runtime controller for streaming dictation and subtitle sessions."""

from __future__ import annotations

import logging
import os
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .asr_backends import create_asr_backend
from .audio_sources import create_audio_source
from .config import ensure_logging_dir, load_config
from .output_sinks import create_output_sinks
from .runtime_types import AudioSource, ASRBackend, OutputSink, RecognitionEvent, TranscriptionResult


logger = logging.getLogger(__name__)


class VoiceRuntimeController:
    def __init__(
        self,
        config_path: Optional[str] = None,
        config: Optional[dict] = None,
        on_result: Optional[Callable[[TranscriptionResult], None]] = None,
        source: Optional[AudioSource] = None,
        backend: Optional[ASRBackend] = None,
        sinks: Optional[list[OutputSink]] = None,
    ) -> None:
        self.config = config if config is not None else load_config(config_path)
        self.on_result = on_result
        self.log_dir = ensure_logging_dir(self.config)
        self.mode = self.config.get("mode", "dictation")
        self.source = source or create_audio_source(self.config)
        self.backend = backend or create_asr_backend(self.config)
        self.sinks = sinks if sinks is not None else create_output_sinks(self.config)

        self._running = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._session_counter = 0
        self._session_id = 0
        self._session_frames: list[np.ndarray] = []
        self._session_started_at = 0.0
        self._audio_cfg = {"sample_rate": self.config["source"]["sample_rate"]}
        self.last_segment_path: Optional[Path] = None

    def start(self) -> None:
        with self._lock:
            if self._running.is_set():
                logger.debug("Runtime already active")
                return

            self._session_counter += 1
            self._session_id = self._session_counter
            self._session_frames.clear()
            self._session_started_at = time.monotonic()
            self.backend.initialize()
            self.backend.start_stream(
                session_id=self._session_id,
                source_kind=self.source.source_kind,
                continuous_segments=self.mode == "subtitles",
            )
            self.source.flush()
            self.source.start()
            self._running.set()
            self._capture_thread = threading.Thread(
                target=self._capture_loop,
                daemon=True,
                name=f"VoiceSession-{self._session_id}",
            )
            self._capture_thread.start()
            logger.info(
                "Voice runtime started, session_id=%s mode=%s source=%s",
                self._session_id,
                self.mode,
                self.source.source_kind,
            )

    def stop(self) -> None:
        with self._lock:
            if not self._running.is_set():
                return
            self._running.clear()

        self.source.stop()
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=3.0)
        self._capture_thread = None
        self._persist_recent_audio()
        self._dispatch_events(self.backend.finalize())
        logger.info("Voice runtime stopped, session_id=%s", self._session_id)

    def cleanup(self) -> None:
        try:
            self.stop()
        except Exception as exc:
            logger.debug("Controller stop during cleanup failed: %s", exc)

        try:
            self.source.stop()
        except Exception as exc:
            logger.debug("Source cleanup failed: %s", exc)

        try:
            self.backend.cleanup()
        except Exception as exc:
            logger.debug("Backend cleanup failed: %s", exc)

        for sink in self.sinks:
            try:
                sink.close()
            except Exception as exc:
                logger.debug("Sink cleanup failed: %s", exc)

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def _capture_loop(self) -> None:
        while self._running.is_set():
            frame = self.source.read(timeout=0.2)
            if frame is None:
                continue
            self._session_frames.append(frame.samples.copy())
            try:
                self._dispatch_events(self.backend.push_audio(frame.samples))
            except Exception as exc:
                logger.error("ASR backend failed: %s", exc, exc_info=True)
                error_event = RecognitionEvent(
                    text="",
                    raw_text="",
                    is_final=True,
                    source_kind=self.source.source_kind,
                    session_id=self._session_id,
                    duration=time.monotonic() - self._session_started_at,
                    latency_ms=0.0,
                    language=self.config["asr"].get("language", "ru"),
                    confidence=0.0,
                    error=str(exc),
                )
                self._dispatch_events([error_event])
                self._running.clear()
                try:
                    self.source.stop()
                except Exception:
                    logger.debug("Source stop after backend error failed", exc_info=True)
                break

    def _dispatch_events(self, events: list[RecognitionEvent]) -> None:
        for event in events:
            for sink in self.sinks:
                try:
                    sink.handle_event(event)
                except Exception as exc:
                    logger.error("Sink %s failed: %s", sink.__class__.__name__, exc, exc_info=True)

            if event.is_final and self.on_result is not None:
                try:
                    self.on_result(TranscriptionResult.from_event(event))
                except Exception as exc:
                    logger.error("Result handler failed: %s", exc, exc_info=True)

    def _persist_recent_audio(self) -> None:
        if not self._session_frames:
            return

        try:
            samples = np.concatenate(self._session_frames, axis=0)
        except Exception as exc:
            logger.warning("Unable to combine session frames: %s", exc)
            return
        finally:
            self._session_frames.clear()

        recent_path = Path(self.log_dir) / "recent.wav"
        os.makedirs(recent_path.parent, exist_ok=True)
        tmp_path = recent_path.parent / f".recent-{self._session_id}-{threading.get_ident()}.tmp.wav"
        try:
            with wave.open(str(tmp_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.config["source"]["sample_rate"])
                pcm = np.clip(samples, -1.0, 1.0)
                wav_file.writeframes((pcm * 32767.0).astype(np.int16).tobytes())
            os.replace(tmp_path, recent_path)
            self.last_segment_path = recent_path
        except OSError as exc:
            logger.warning("Unable to persist recent audio to %s: %s", recent_path, exc)
            self.last_segment_path = None
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
