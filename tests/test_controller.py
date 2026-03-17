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

    def __init__(self) -> None:
        self._queue: "queue.Queue[AudioFrame]" = queue.Queue()
        self._running = False
        self.sample_rate = 16000

    def start(self) -> None:
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


class FakeBackend:
    def __init__(self) -> None:
        self.initialized = False
        self.started = None
        self.received = []

    def initialize(self) -> None:
        self.initialized = True

    def start_stream(self, session_id: int, source_kind: str, continuous_segments: bool) -> None:
        self.started = (session_id, source_kind, continuous_segments)

    def push_audio(self, samples: np.ndarray):
        self.received.append(samples.copy())
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
        return None


class CaptureSink:
    def __init__(self) -> None:
        self.events = []

    def handle_event(self, event: RecognitionEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        return None


class ControllerTests(unittest.TestCase):
    def test_controller_dispatches_partial_and_final_events(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["logging"]["dir"] = "logs"
        source = FakeSource()
        backend = FakeBackend()
        sink = CaptureSink()
        results = []
        controller = VoiceRuntimeController(
            config=config,
            source=source,
            backend=backend,
            sinks=[sink],
            on_result=results.append,
        )

        with patch.object(controller, "_persist_recent_audio") as persist_recent_audio:
            controller.start()
            source.push(np.ones(320, dtype=np.float32))
            deadline = time.time() + 1.0
            while len(sink.events) < 1 and time.time() < deadline:
                time.sleep(0.02)

            controller.stop()
            controller.cleanup()

        self.assertTrue(backend.initialized)
        self.assertEqual(backend.started, (1, "microphone", False))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].text, "privet mir")
        self.assertEqual([event.is_final for event in sink.events], [False, True])
        persist_recent_audio.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
