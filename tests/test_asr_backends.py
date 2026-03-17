from __future__ import annotations

import copy
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from app.asr_backends import SherpaOnnxBackend
from app.config import DEFAULT_CONFIG


class _FakeStream:
    def __init__(self) -> None:
        self.accept_calls: list[tuple[int, np.ndarray]] = []
        self.finished = False

    def accept_waveform(self, sample_rate: int, samples: np.ndarray) -> None:
        self.accept_calls.append((sample_rate, samples.copy()))

    def input_finished(self) -> None:
        self.finished = True


class _FakeRecognizer:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.streams: list[_FakeStream] = []
        self.results: list[str] = []
        self.endpoint = False
        self.reset_calls = 0

    def create_stream(self) -> _FakeStream:
        stream = _FakeStream()
        self.streams.append(stream)
        return stream

    def is_ready(self, stream: _FakeStream) -> bool:
        return False

    def decode_stream(self, stream: _FakeStream) -> None:
        return None

    def get_result(self, stream: _FakeStream):
        text = self.results[-1] if self.results else ""
        return types.SimpleNamespace(text=text)

    def is_endpoint(self, stream: _FakeStream) -> bool:
        return self.endpoint

    def reset(self, stream: _FakeStream) -> None:
        self.reset_calls += 1


class _FakeOnlineRecognizer:
    init_calls: list[dict] = []
    recognizers: list[_FakeRecognizer] = []

    @classmethod
    def from_t_one_ctc(cls, model: str, **kwargs):
        cls.init_calls.append({"model": model, **kwargs})
        recognizer = _FakeRecognizer({"model": model, **kwargs})
        cls.recognizers.append(recognizer)
        return recognizer


class SherpaBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeOnlineRecognizer.init_calls.clear()
        _FakeOnlineRecognizer.recognizers.clear()

    def test_t_one_backend_uses_model_sample_rate_but_stream_input_rate(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["source"]["sample_rate"] = 16000
        config["asr"]["sherpa"]["sample_rate"] = 8000

        backend = SherpaOnnxBackend(config)
        fake_module = types.SimpleNamespace(OnlineRecognizer=_FakeOnlineRecognizer)

        with patch.dict(sys.modules, {"sherpa_onnx": fake_module}):
            backend.initialize()
            backend.start_stream(session_id=1, source_kind="microphone", continuous_segments=False)
            backend.push_audio(np.ones(320, dtype=np.float32))

        self.assertEqual(_FakeOnlineRecognizer.init_calls[0]["sample_rate"], 8000)
        stream = _FakeOnlineRecognizer.recognizers[0].streams[0]
        self.assertEqual(stream.accept_calls[0][0], 16000)

    def test_continuous_segments_allow_same_final_text_after_reset(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        backend = SherpaOnnxBackend(config)
        backend._recognizer = _FakeRecognizer({})
        backend.start_stream(session_id=1, source_kind="loopback", continuous_segments=True)

        recognizer = backend._recognizer
        assert recognizer is not None

        recognizer.results.append("hello")
        recognizer.endpoint = True
        first_events = backend.push_audio(np.ones(320, dtype=np.float32))

        recognizer.results.append("hello")
        recognizer.endpoint = True
        second_events = backend.push_audio(np.ones(320, dtype=np.float32))

        self.assertEqual([event.is_final for event in first_events], [False, True])
        self.assertEqual([event.is_final for event in second_events], [False, True])
        self.assertEqual(recognizer.reset_calls, 2)


if __name__ == "__main__":
    unittest.main()
