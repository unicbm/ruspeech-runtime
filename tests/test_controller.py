from __future__ import annotations

import copy
import queue
import time
import unittest
from unittest.mock import patch

import numpy as np

from app.config import DEFAULT_CONFIG
from app.controller import VoiceRuntimeController
from app.runtime_types import AudioFrame, RecognitionEvent


class FakeSource:
    source_kind = "microphone"

    def __init__(self, *, fail_on_start: bool = False) -> None:
        self._queue: "queue.Queue[AudioFrame]" = queue.Queue()
        self._running = False
        self._last_error = None
        self._fail_on_start = fail_on_start
        self.sample_rate = 16000

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def start(self) -> None:
        if self._fail_on_start:
            self._last_error = "boom"
            raise RuntimeError("boom")
        self._last_error = None
        self._running = True

    def stop(self) -> None:
        self._running = False

    def read(self, timeout: float = 0.1):
        if not self._running:
            return None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()

    def push(self, samples: np.ndarray) -> None:
        self._queue.put(
            AudioFrame(
                samples=samples.astype(np.float32),
                sample_rate=self.sample_rate,
                channels=1,
                source_kind=self.source_kind,
            )
        )


class FailingLoopbackSource(FakeSource):
    source_kind = "loopback"

    def fail_runtime(self, message: str = "loopback died") -> None:
        self._last_error = message
        self._running = False


class FakeBackend:
    def __init__(self) -> None:
        self.initialized = False
        self.started = None
        self.received = []
        self.finalize_calls = 0
        self.cleanup_calls = 0
        self.raise_on_push = False

    def initialize(self) -> None:
        self.initialized = True

    def start_stream(self, session_id: int, source_kind: str, continuous_segments: bool) -> None:
        self.started = (session_id, source_kind, continuous_segments)

    def push_audio(self, samples: np.ndarray):
        self.received.append(samples.copy())
        if self.raise_on_push:
            raise RuntimeError("backend exploded")
        return [
            RecognitionEvent(
                text="privet",
                raw_text="privet",
                is_final=False,
                source_kind="microphone",
                session_id=self.started[0],
            )
        ]

    def finalize(self):
        self.finalize_calls += 1
        if self.started is None:
            return []
        return [
            RecognitionEvent(
                text="privet mir",
                raw_text="privet mir",
                is_final=True,
                source_kind="microphone",
                session_id=self.started[0],
                duration=0.5,
                latency_ms=12.0,
            )
        ]

    def cleanup(self) -> None:
        self.cleanup_calls += 1


class CaptureSink:
    def __init__(self, *, delay: float = 0.0) -> None:
        self.delay = delay
        self.events = []

    def handle_event(self, event: RecognitionEvent) -> None:
        if self.delay:
            time.sleep(self.delay)
        self.events.append(event)

    def close(self) -> None:
        return None


class ControllerTests(unittest.TestCase):
    def _make_controller(
        self,
        *,
        source: FakeSource | None = None,
        backend: FakeBackend | None = None,
        sink: CaptureSink | None = None,
    ) -> tuple[VoiceRuntimeController, FakeSource, FakeBackend, CaptureSink]:
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["logging"]["dir"] = "logs"
        source = source or FakeSource()
        backend = backend or FakeBackend()
        sink = sink or CaptureSink()
        controller = VoiceRuntimeController(
            config=config,
            source=source,
            backend=backend,
            sinks=[sink],
            on_result=None,
        )
        self.addCleanup(controller.cleanup)
        return controller, source, backend, sink

    def test_controller_dispatches_partial_and_final_events(self) -> None:
        controller, source, backend, sink = self._make_controller()
        results = []
        controller.on_result = results.append

        with patch.object(controller, "_persist_recent_audio") as persist_recent_audio:
            controller.start()
            source.push(np.ones(320, dtype=np.float32))
            self._wait_for(lambda: len(sink.events) >= 1)

            controller.stop()
            self._wait_for(lambda: len(results) == 1)

        self.assertTrue(backend.initialized)
        self.assertEqual(backend.started, (1, "microphone", False))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].text, "privet mir")
        self.assertEqual([event.is_final for event in sink.events], [False, True])
        self.assertEqual(controller.state, VoiceRuntimeController.STATE_IDLE)
        persist_recent_audio.assert_called_once_with()

    def test_start_failure_rolls_back_and_allows_restart(self) -> None:
        source = FakeSource(fail_on_start=True)
        controller, _, backend, _ = self._make_controller(source=source)

        with patch.object(controller, "_persist_recent_audio"):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                controller.start()

        self.assertEqual(controller.state, VoiceRuntimeController.STATE_IDLE)
        self.assertEqual(backend.finalize_calls, 1)
        self.assertEqual(backend.cleanup_calls, 1)

        controller.source = FakeSource()
        with patch.object(controller, "_persist_recent_audio"):
            controller.start()
        self.assertTrue(controller.is_running)

    def test_backend_error_runs_finalize_and_emits_error(self) -> None:
        backend = FakeBackend()
        backend.raise_on_push = True
        controller, source, _, sink = self._make_controller(backend=backend)
        results = []
        controller.on_result = results.append

        with patch.object(controller, "_persist_recent_audio") as persist_recent_audio:
            controller.start()
            source.push(np.ones(320, dtype=np.float32))
            self._wait_for(lambda: len(results) >= 2)

        self.assertEqual(controller.state, VoiceRuntimeController.STATE_IDLE)
        self.assertEqual(backend.finalize_calls, 1)
        self.assertEqual(backend.cleanup_calls, 1)
        self.assertEqual(results[0].text, "privet mir")
        self.assertEqual(results[1].error, "ASR backend failed: backend exploded")
        self.assertTrue(any(event.error for event in sink.events))
        persist_recent_audio.assert_called_once_with()

    def test_source_failure_transitions_to_idle_with_error(self) -> None:
        source = FailingLoopbackSource()
        controller, _, backend, sink = self._make_controller(source=source)
        results = []
        controller.on_result = results.append

        with patch.object(controller, "_persist_recent_audio") as persist_recent_audio:
            controller.start()
            source.fail_runtime()
            self._wait_for(lambda: len(results) >= 2)

        self.assertEqual(controller.state, VoiceRuntimeController.STATE_IDLE)
        self.assertEqual(backend.finalize_calls, 1)
        self.assertEqual(results[-1].error, "loopback died")
        self.assertTrue(any(event.error == "loopback died" for event in sink.events))
        persist_recent_audio.assert_called_once_with()

    def test_slow_sink_does_not_block_capture_thread(self) -> None:
        sink = CaptureSink(delay=0.05)
        controller, source, backend, _ = self._make_controller(sink=sink)

        with patch.object(controller, "_persist_recent_audio"):
            controller.start()
            for _ in range(10):
                source.push(np.ones(320, dtype=np.float32))

            self._wait_for(lambda: len(backend.received) == 10)
            controller.stop()

        self.assertEqual(len(backend.received), 10)

    def test_recent_audio_keeps_only_recent_window(self) -> None:
        controller, _, _, _ = self._make_controller()
        sample_rate = controller.config["source"]["sample_rate"]
        frame = np.ones(320, dtype=np.float32)

        for _ in range(2000):
            controller._append_recent_audio(frame)

        self.assertLessEqual(controller._recent_sample_count, sample_rate * 30)
        self.assertLessEqual(sum(chunk.size for chunk in controller._recent_frames), sample_rate * 30)

    def _wait_for(self, predicate, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("condition not met before timeout")


if __name__ == "__main__":
    unittest.main()
