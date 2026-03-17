"""ASR backends and backend factory."""

from __future__ import annotations

import inspect
import logging
import os
import time
from typing import Optional

import numpy as np

from .runtime_types import ASRBackend, RecognitionEvent


logger = logging.getLogger(__name__)


class BackendInitializationError(RuntimeError):
    """Raised when an ASR backend cannot be initialized."""


class SherpaOnnxBackend(ASRBackend):
    def __init__(self, config: dict) -> None:
        self.config = config
        self.asr_cfg = config["asr"]
        self.sherpa_cfg = self.asr_cfg.get("sherpa", {})
        self.sample_rate = int(config["source"]["sample_rate"])
        self.language = self.asr_cfg.get("language", "ru")
        self.enable_endpoint_detection = bool(self.asr_cfg.get("enable_endpoint_detection", True))
        self._recognizer = None
        self._stream = None
        self._session_id = 0
        self._source_kind = "microphone"
        self._continuous_segments = False
        self._audio_seconds = 0.0
        self._last_partial_text = ""
        self._last_final_text = ""

    def initialize(self) -> None:
        if self._recognizer is not None:
            return

        try:
            import sherpa_onnx
        except ImportError as exc:
            raise BackendInitializationError(
                "sherpa-onnx is required for the default Russian backend"
            ) from exc

        recognizer_kwargs = self._build_recognizer_kwargs()
        ctor = sherpa_onnx.OnlineRecognizer
        valid_params = set(inspect.signature(ctor).parameters)
        filtered_kwargs = {
            key: value
            for key, value in recognizer_kwargs.items()
            if value is not None and key in valid_params
        }
        missing_required = [key for key in ("tokens", "sample_rate") if key not in filtered_kwargs]
        if missing_required:
            raise BackendInitializationError(
                f"Missing sherpa-onnx configuration keys: {', '.join(missing_required)}"
            )
        has_transducer = all(filtered_kwargs.get(name) for name in ("encoder", "decoder", "joiner"))
        has_single_model = any(filtered_kwargs.get(name) for name in ("model", "paraformer"))
        if not has_transducer and not has_single_model:
            raise BackendInitializationError(
                "Sherpa-ONNX config must provide either encoder/decoder/joiner or a single model/paraformer file"
            )

        try:
            self._recognizer = ctor(**filtered_kwargs)
        except Exception as exc:
            raise BackendInitializationError(f"Unable to initialize sherpa-onnx: {exc}") from exc

        logger.info("Sherpa-ONNX backend initialized")

    def start_stream(self, session_id: int, source_kind: str, continuous_segments: bool) -> None:
        self.initialize()
        assert self._recognizer is not None
        self._stream = self._recognizer.create_stream()
        self._session_id = session_id
        self._source_kind = source_kind
        self._continuous_segments = continuous_segments
        self._audio_seconds = 0.0
        self._last_partial_text = ""
        self._last_final_text = ""
        logger.debug(
            "Sherpa stream started, session_id=%s source_kind=%s continuous=%s",
            session_id,
            source_kind,
            continuous_segments,
        )

    def push_audio(self, samples: np.ndarray) -> list[RecognitionEvent]:
        if self._stream is None:
            raise RuntimeError("ASR stream not started")

        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return []

        self._audio_seconds += samples.size / float(self.sample_rate)
        started_at = time.monotonic()
        self._stream.accept_waveform(self.sample_rate, samples)
        self._decode_ready()
        latency_ms = (time.monotonic() - started_at) * 1000.0

        events: list[RecognitionEvent] = []
        current_text = self._current_text()
        if current_text and current_text != self._last_partial_text:
            self._last_partial_text = current_text
            events.append(self._make_event(current_text, is_final=False, latency_ms=latency_ms))

        if (
            self._continuous_segments
            and self.enable_endpoint_detection
            and self._is_endpoint()
            and current_text
            and current_text != self._last_final_text
        ):
            self._last_final_text = current_text
            events.append(self._make_event(current_text, is_final=True, latency_ms=latency_ms))
            self._reset_stream()

        return events

    def finalize(self) -> list[RecognitionEvent]:
        if self._stream is None:
            return []

        started_at = time.monotonic()
        self._stream.input_finished()
        self._decode_ready()
        latency_ms = (time.monotonic() - started_at) * 1000.0
        current_text = self._current_text()
        self._stream = None

        if not current_text or current_text == self._last_final_text:
            return []

        self._last_final_text = current_text
        return [self._make_event(current_text, is_final=True, latency_ms=latency_ms)]

    def cleanup(self) -> None:
        self._stream = None
        self._recognizer = None

    def _build_recognizer_kwargs(self) -> dict:
        model_dir = self.sherpa_cfg.get("model_dir")
        resolved = {
            "tokens": self._resolve_path(self.sherpa_cfg.get("tokens"), model_dir, "tokens.txt"),
            "encoder": self._resolve_path(self.sherpa_cfg.get("encoder"), model_dir, "encoder.onnx"),
            "decoder": self._resolve_path(self.sherpa_cfg.get("decoder"), model_dir, "decoder.onnx"),
            "joiner": self._resolve_path(self.sherpa_cfg.get("joiner"), model_dir, "joiner.onnx"),
            "model": self._resolve_path(self.sherpa_cfg.get("model"), model_dir, "model.onnx"),
            "paraformer": self._resolve_path(
                self.sherpa_cfg.get("paraformer"), model_dir, "model.int8.onnx"
            )
            or self._resolve_path(self.sherpa_cfg.get("paraformer"), model_dir, "model.onnx"),
        }
        return {
            **resolved,
            "sample_rate": self.sample_rate,
            "feature_dim": int(self.sherpa_cfg.get("feature_dim", 80)),
            "provider": self.asr_cfg.get("provider", "cpu"),
            "num_threads": int(self.asr_cfg.get("num_threads", 2)),
            "decoding_method": self.sherpa_cfg.get("decoding_method", "greedy_search"),
            "enable_endpoint_detection": self.enable_endpoint_detection,
            "rule1_min_trailing_silence": float(self.asr_cfg.get("rule1_min_trailing_silence", 1.2)),
            "rule2_min_trailing_silence": float(self.asr_cfg.get("rule2_min_trailing_silence", 0.8)),
            "rule3_min_utterance_length": float(self.asr_cfg.get("rule3_min_utterance_length", 20.0)),
        }

    def _resolve_path(self, explicit: Optional[str], model_dir: Optional[str], filename: str) -> Optional[str]:
        if explicit:
            return explicit
        if not model_dir:
            return None
        candidate = os.path.join(model_dir, filename)
        return candidate if os.path.exists(candidate) else None

    def _decode_ready(self) -> None:
        assert self._recognizer is not None
        assert self._stream is not None
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)

    def _current_text(self) -> str:
        assert self._recognizer is not None
        assert self._stream is not None
        result = self._recognizer.get_result(self._stream)
        text = getattr(result, "text", result)
        return str(text).strip()

    def _is_endpoint(self) -> bool:
        assert self._recognizer is not None
        assert self._stream is not None
        checker = getattr(self._recognizer, "is_endpoint", None)
        return bool(checker(self._stream)) if checker else False

    def _reset_stream(self) -> None:
        assert self._recognizer is not None
        assert self._stream is not None
        reset = getattr(self._recognizer, "reset", None)
        if reset:
            reset(self._stream)
        else:
            self._stream = self._recognizer.create_stream()
        self._last_partial_text = ""
        self._audio_seconds = 0.0

    def _make_event(self, text: str, is_final: bool, latency_ms: float) -> RecognitionEvent:
        return RecognitionEvent(
            text=text,
            raw_text=text,
            is_final=is_final,
            source_kind=self._source_kind,
            session_id=self._session_id,
            duration=self._audio_seconds,
            latency_ms=latency_ms,
            language=self.language,
            confidence=0.0,
        )


def create_asr_backend(config: dict) -> ASRBackend:
    backend_name = config["asr"].get("backend", "sherpa-onnx").lower()
    if backend_name == "sherpa-onnx":
        return SherpaOnnxBackend(config)
    if backend_name in {"vosk", "qwen3-asr", "qwen"}:
        raise NotImplementedError(
            f"Backend '{backend_name}' is reserved by the new architecture but not implemented yet"
        )
    raise ValueError(f"Unsupported ASR backend: {backend_name}")
