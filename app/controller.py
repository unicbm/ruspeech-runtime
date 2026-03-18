"""Runtime controller for streaming dictation and subtitle sessions."""

from __future__ import annotations

import logging
import os
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .asr_backends import create_asr_backend
from .audio_sources import create_audio_source
from .config import ensure_logging_dir, load_config
from .output_sinks import create_output_sinks
from .runtime_types import ASRBackend, AudioSource, OutputSink, RecognitionEvent, TranscriptionResult


logger = logging.getLogger(__name__)

_RECENT_AUDIO_SECONDS = 30
_DISPATCH_QUEUE_SIZE = 256


@dataclass(slots=True)
class _QueuedEvent:
    session_token: int
    event: RecognitionEvent


class _BoundedEventQueue:
    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._items: deque[_QueuedEvent] = deque()
        self._condition = threading.Condition()
        self._closed = False
        self._inflight = 0

    def put(self, item: _QueuedEvent) -> bool:
        with self._condition:
            if self._closed:
                return False

            if item.event.is_final:
                while len(self._items) >= self._maxsize and not self._closed:
                    self._drop_oldest_partial_locked()
                    if len(self._items) < self._maxsize:
                        break
                    self._condition.wait(timeout=0.05)
                if self._closed:
                    return False
            elif len(self._items) >= self._maxsize:
                self._drop_oldest_partial_locked()
                if len(self._items) >= self._maxsize:
                    return False

            self._items.append(item)
            self._condition.notify_all()
            return True

    def get(self) -> Optional[_QueuedEvent]:
        with self._condition:
            while not self._items and not self._closed:
                self._condition.wait()
            if self._items:
                item = self._items.popleft()
                self._inflight += 1
                self._condition.notify_all()
                return item
            return None

    def task_done(self) -> None:
        with self._condition:
            if self._inflight > 0:
                self._inflight -= 1
            self._condition.notify_all()

    def wait_empty(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while (self._items or self._inflight) and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return not self._items and self._inflight == 0

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def _drop_oldest_partial_locked(self) -> bool:
        for item in list(self._items):
            if not item.event.is_final:
                self._items.remove(item)
                return True
        return False


class VoiceRuntimeController:
    STATE_IDLE = "IDLE"
    STATE_STARTING = "STARTING"
    STATE_RUNNING = "RUNNING"
    STATE_STOPPING = "STOPPING"
    STATE_ERROR = "ERROR"

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
        self._lock = threading.RLock()
        self._state = self.STATE_IDLE
        self._last_error: Optional[str] = None
        self._session_counter = 0
        self._session_id = 0
        self._active_session_token = 0
        self._teardown_token = 0
        self._capture_thread: Optional[threading.Thread] = None
        self._session_started_at = 0.0
        self._recent_frames: deque[np.ndarray] = deque()
        self._recent_sample_count = 0
        self._recent_sample_limit = int(self.config["source"]["sample_rate"] * _RECENT_AUDIO_SECONDS)
        self.last_segment_path: Optional[Path] = None

        self._dispatch_queue = _BoundedEventQueue(_DISPATCH_QUEUE_SIZE)
        self._dispatcher_thread = threading.Thread(
            target=self._dispatch_loop,
            daemon=True,
            name="VoiceRuntimeDispatch",
        )
        self._dispatcher_thread.start()

    @property
    def is_running(self) -> bool:
        return self._state == self.STATE_RUNNING

    @property
    def state(self) -> str:
        return self._state

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def start(self) -> None:
        startup_error: Optional[Exception] = None
        session_token = 0
        with self._lock:
            if self._state in {self.STATE_STARTING, self.STATE_RUNNING, self.STATE_STOPPING}:
                logger.debug("Runtime start ignored while state=%s", self._state)
                return

            self._state = self.STATE_STARTING
            self._last_error = None
            self._session_counter += 1
            self._session_id = self._session_counter
            self._active_session_token = self._session_counter
            self._teardown_token = 0
            self._session_started_at = time.monotonic()
            self._clear_recent_audio()
            self.last_segment_path = None
            session_token = self._active_session_token

            try:
                self.backend.initialize()
                self.source.flush()
                self.source.start()
                self.backend.start_stream(
                    session_id=self._session_id,
                    source_kind=self.source.source_kind,
                    continuous_segments=self.mode == "subtitles",
                )
                self._running.set()
                self._capture_thread = threading.Thread(
                    target=self._capture_loop,
                    args=(session_token,),
                    daemon=True,
                    name=f"VoiceSession-{self._session_id}",
                )
                self._capture_thread.start()
                self._state = self.STATE_RUNNING
            except Exception as exc:
                startup_error = exc
                self._last_error = str(exc)
                self._state = self.STATE_ERROR
                self._running.clear()
                self._teardown_token = session_token

        if startup_error is not None:
            self._shutdown_session(
                session_token=session_token,
                emit_error=False,
                cleanup_backend=True,
                join_capture_thread=False,
            )
            raise startup_error

        logger.info(
            "Voice runtime started, session_id=%s mode=%s source=%s",
            self._session_id,
            self.mode,
            self.source.source_kind,
        )

    def stop(self) -> None:
        session_token = self._begin_shutdown(self.STATE_STOPPING)
        if session_token == 0:
            return

        self._shutdown_session(
            session_token=session_token,
            emit_error=False,
            cleanup_backend=False,
            join_capture_thread=True,
        )
        logger.info("Voice runtime stopped, session_id=%s", self._session_id)

    def cleanup(self) -> None:
        try:
            self.stop()
        except Exception as exc:
            logger.debug("Controller stop during cleanup failed: %s", exc)

        self._dispatch_queue.wait_empty(timeout=1.0)
        self._dispatch_queue.close()
        if self._dispatcher_thread.is_alive():
            self._dispatcher_thread.join(timeout=2.0)

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

    def _begin_shutdown(self, next_state: str) -> int:
        with self._lock:
            if self._active_session_token == 0:
                return 0
            if self._teardown_token == self._active_session_token:
                return 0
            self._teardown_token = self._active_session_token
            self._state = next_state
            self._running.clear()
            return self._active_session_token

    def _capture_loop(self, session_token: int) -> None:
        while self._running.is_set() and session_token == self._active_session_token:
            try:
                frame = self.source.read(timeout=0.2)
            except Exception as exc:
                logger.error("Audio source read failed: %s", exc, exc_info=True)
                self._handle_runtime_failure(session_token, f"Audio source read failed: {exc}")
                return

            if frame is None:
                if not self._running.is_set():
                    return
                if self.source_failed():
                    error_message = self.source.last_error or "Audio source stopped unexpectedly"
                    logger.error("Audio source failed: %s", error_message)
                    self._handle_runtime_failure(session_token, error_message)
                    return
                continue

            self._append_recent_audio(frame.samples)
            try:
                self._queue_events(self.backend.push_audio(frame.samples), session_token)
            except Exception as exc:
                logger.error("ASR backend failed: %s", exc, exc_info=True)
                self._handle_runtime_failure(session_token, f"ASR backend failed: {exc}")
                return

    def _handle_runtime_failure(self, session_token: int, error_message: str) -> None:
        with self._lock:
            if session_token != self._active_session_token or self._teardown_token == session_token:
                return
            self._last_error = error_message
            self._state = self.STATE_ERROR
            self._running.clear()
            self._teardown_token = session_token

        self._shutdown_session(
            session_token=session_token,
            emit_error=True,
            cleanup_backend=True,
            join_capture_thread=False,
        )

    def _shutdown_session(
        self,
        session_token: int,
        *,
        emit_error: bool,
        cleanup_backend: bool,
        join_capture_thread: bool,
    ) -> None:
        capture_thread = self._capture_thread
        error_message = self._last_error

        try:
            self.source.stop()
        except Exception as exc:
            logger.debug("Source stop failed during session shutdown: %s", exc, exc_info=True)

        if (
            join_capture_thread
            and capture_thread is not None
            and capture_thread.is_alive()
            and capture_thread is not threading.current_thread()
        ):
            capture_thread.join(timeout=3.0)

        final_events: list[RecognitionEvent] = []
        try:
            final_events = self.backend.finalize()
        except Exception as exc:
            logger.error("ASR backend finalize failed: %s", exc, exc_info=True)
            error_message = error_message or f"ASR backend finalize failed: {exc}"
            emit_error = True
        finally:
            if cleanup_backend:
                try:
                    self.backend.cleanup()
                except Exception as exc:
                    logger.debug("Backend cleanup failed during shutdown: %s", exc, exc_info=True)

        self._persist_recent_audio()
        if final_events:
            self._queue_events(final_events, session_token)
        if emit_error and error_message:
            self._queue_events([self._make_error_event(error_message)], session_token)
        self._dispatch_queue.wait_empty(timeout=1.0)

        with self._lock:
            if self._active_session_token == session_token:
                self._capture_thread = None
                self._active_session_token = 0
                self._teardown_token = 0
                self._running.clear()
                self._state = self.STATE_IDLE

    def _dispatch_loop(self) -> None:
        while True:
            queued_event = self._dispatch_queue.get()
            if queued_event is None:
                return
            try:
                self._emit_event(queued_event.event)
            finally:
                self._dispatch_queue.task_done()

    def _emit_event(self, event: RecognitionEvent) -> None:
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

    def _queue_events(self, events: list[RecognitionEvent], session_token: int) -> None:
        for event in events:
            queued = self._dispatch_queue.put(_QueuedEvent(session_token=session_token, event=event))
            if not queued and not event.is_final:
                logger.debug("Dropping partial recognition event because dispatch queue is full")

    def _append_recent_audio(self, samples: np.ndarray) -> None:
        frame = np.asarray(samples, dtype=np.float32).reshape(-1).copy()
        if frame.size == 0:
            return

        self._recent_frames.append(frame)
        self._recent_sample_count += frame.size
        while self._recent_frames and self._recent_sample_count > self._recent_sample_limit:
            dropped = self._recent_frames.popleft()
            self._recent_sample_count -= dropped.size

    def _clear_recent_audio(self) -> None:
        self._recent_frames.clear()
        self._recent_sample_count = 0

    def _persist_recent_audio(self) -> None:
        if not self._recent_frames:
            return

        try:
            samples = np.concatenate(list(self._recent_frames), axis=0)
        except Exception as exc:
            logger.warning("Unable to combine session frames: %s", exc)
            return
        finally:
            self._clear_recent_audio()

        recent_path = Path(self.log_dir) / "recent.wav"
        os.makedirs(recent_path.parent, exist_ok=True)
        tmp_path = recent_path.parent / f"recent-{self._session_id}-{threading.get_ident()}.tmp.wav"
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

    def _make_error_event(self, error_message: str) -> RecognitionEvent:
        return RecognitionEvent(
            text="",
            raw_text="",
            is_final=True,
            source_kind=self.source.source_kind,
            session_id=self._session_id,
            duration=max(0.0, time.monotonic() - self._session_started_at),
            latency_ms=0.0,
            language=self.config["asr"].get("language", "ru"),
            confidence=0.0,
            error=error_message,
        )

    def source_failed(self) -> bool:
        return not self.source.is_running and self._running.is_set()
