from __future__ import annotations

import copy
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from app.asr_backends import BackendInitializationError, FunASRBackend, SherpaOnnxBackend, create_asr_backend
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


class _FakeFunASRServer:
    def __init__(self) -> None:
        self.cleaned = False
        self.paths: list[str] = []

    def initialize(self) -> dict:
        return {"success": True}

    def transcribe_audio(self, audio_path: str, options: dict | None = None) -> dict:
        self.paths.append(audio_path)
        return {
            "success": True,
            "text": "你好世界",
            "raw_text": "你好世界",
            "duration": 1.0,
            "language": "zh-CN",
            "confidence": 0.8,
        }

    def cleanup(self) -> None:
        self.cleaned = True


class SherpaBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeOnlineRecognizer.init_calls.clear()
        _FakeOnlineRecognizer.recognizers.clear()

    def test_t_one_backend_uses_configured_sample_rate_consistently(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["asr"]["sherpa"]["sample_rate"] = 8000

        backend = SherpaOnnxBackend(config)
        fake_module = types.SimpleNamespace(OnlineRecognizer=_FakeOnlineRecognizer)

        with patch.dict(sys.modules, {"sherpa_onnx": fake_module}):
            backend.initialize()
            backend.start_stream(session_id=1, source_kind="microphone", continuous_segments=False)
            backend.push_audio(np.ones(320, dtype=np.float32))

        self.assertEqual(_FakeOnlineRecognizer.init_calls[0]["sample_rate"], 8000)
        stream = _FakeOnlineRecognizer.recognizers[0].streams[0]
        self.assertEqual(stream.accept_calls[0][0], 8000)

    def test_mismatched_source_and_model_sample_rates_fail_backend_initialization(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["source"]["sample_rate"] = 16000
        config["asr"]["sherpa"]["sample_rate"] = 8000

        backend = SherpaOnnxBackend(config)
        with self.assertRaisesRegex(BackendInitializationError, "must match"):
            backend.initialize()

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

    def test_create_backend_supports_funasr(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["asr"]["backend"] = "funasr"
        backend = create_asr_backend(config)
        self.assertIsInstance(backend, FunASRBackend)

    def test_funasr_backend_transcribes_buffer_on_finalize(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["asr"]["backend"] = "funasr"
        config["source"]["sample_rate"] = 16000
        config["source"]["frame_ms"] = 40

        fake_server = _FakeFunASRServer()
        with patch("app.asr_backends.FunASRServer", return_value=fake_server):
            backend = FunASRBackend(config)
            backend.initialize()
            backend.start_stream(session_id=7, source_kind="microphone", continuous_segments=False)
            backend.push_audio(np.ones(1600, dtype=np.float32))
            events = backend.finalize()
            backend.cleanup()

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_final)
        self.assertEqual(events[0].text, "你好世界")
        self.assertEqual(events[0].session_id, 7)
        self.assertEqual(fake_server.cleaned, True)


if __name__ == "__main__":
    unittest.main()
