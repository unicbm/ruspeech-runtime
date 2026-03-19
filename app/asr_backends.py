"""ASR backends and backend factory."""

from __future__ import annotations

import logging
import os
import tempfile
import time
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from .config import ensure_logging_dir, resolve_runtime_path
from .funasr_server import FunASRServer
from .runtime_types import ASRBackend, RecognitionEvent


logger = logging.getLogger(__name__)


class BackendInitializationError(RuntimeError):
    """Raised when an ASR backend cannot be initialized."""


class SherpaOnnxBackend(ASRBackend):
    def __init__(self, config: dict) -> None:
        self.config = config
        self.asr_cfg = config["asr"]
        self.sherpa_cfg = self.asr_cfg.get("sherpa", {})
        self.input_sample_rate = int(config["source"]["sample_rate"])
        self.model_sample_rate = int(self.sherpa_cfg.get("sample_rate", self.input_sample_rate))
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
        if self.input_sample_rate != self.model_sample_rate:
            raise BackendInitializationError(
                "source.sample_rate and asr.sherpa.sample_rate must match until resampling is implemented"
            )

        try:
            import sherpa_onnx
        except ImportError as exc:
            raise BackendInitializationError(
                "sherpa-onnx is required for the default Russian backend"
            ) from exc

        model_paths = self._resolve_model_paths()
        tokens = model_paths["tokens"]
        if not tokens:
            raise BackendInitializationError("Missing sherpa-onnx tokens.txt path")

        provider = self.asr_cfg.get("provider", "cpu")
        num_threads = int(self.asr_cfg.get("num_threads", 2))
        common_kwargs = {
            "tokens": tokens,
            "num_threads": num_threads,
            "sample_rate": self.model_sample_rate,
            "feature_dim": int(self.sherpa_cfg.get("feature_dim", 80)),
            "enable_endpoint_detection": self.enable_endpoint_detection,
            "rule1_min_trailing_silence": float(self.asr_cfg.get("rule1_min_trailing_silence", 1.2)),
            "rule2_min_trailing_silence": float(self.asr_cfg.get("rule2_min_trailing_silence", 0.8)),
            "rule3_min_utterance_length": float(self.asr_cfg.get("rule3_min_utterance_length", 20.0)),
            "decoding_method": self.sherpa_cfg.get("decoding_method", "greedy_search"),
            "provider": provider,
        }

        variant = str(self.sherpa_cfg.get("variant", "")).lower()

        try:
            if variant == "t-one-ctc" or (model_paths["model"] and not model_paths["encoder"]):
                if not model_paths["model"]:
                    raise BackendInitializationError("Missing model.onnx for sherpa t-one CTC backend")
                self._recognizer = sherpa_onnx.OnlineRecognizer.from_t_one_ctc(
                    model=model_paths["model"],
                    **common_kwargs,
                )
            elif model_paths["paraformer"] and model_paths["encoder"]:
                self._recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
                    encoder=model_paths["encoder"],
                    decoder=model_paths["paraformer"],
                    **common_kwargs,
                )
            elif all(model_paths[name] for name in ("encoder", "decoder", "joiner")):
                self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                    encoder=model_paths["encoder"],
                    decoder=model_paths["decoder"],
                    joiner=model_paths["joiner"],
                    model_type=self.sherpa_cfg.get("model_type", ""),
                    **common_kwargs,
                )
            elif model_paths["model"]:
                self._recognizer = sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(
                    model=model_paths["model"],
                    **common_kwargs,
                )
            else:
                raise BackendInitializationError(
                    "Sherpa-ONNX config must provide either model.onnx or encoder/decoder/joiner files"
                )
        except BackendInitializationError:
            raise
        except Exception as exc:
            raise BackendInitializationError(f"Unable to initialize sherpa-onnx: {exc}") from exc

        logger.info(
            "Sherpa-ONNX backend initialized, input_sample_rate=%sHz model_sample_rate=%sHz",
            self.input_sample_rate,
            self.model_sample_rate,
        )

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

        self._audio_seconds += samples.size / float(self.input_sample_rate)
        started_at = time.monotonic()
        self._stream.accept_waveform(self.input_sample_rate, samples)
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

    def _resolve_model_paths(self) -> dict:
        model_dir = self.sherpa_cfg.get("model_dir")
        return {
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

    def _resolve_path(self, explicit: Optional[str], model_dir: Optional[str], filename: str) -> Optional[str]:
        if explicit:
            explicit_path = resolve_runtime_path(explicit)
            return explicit_path if explicit_path and os.path.exists(explicit_path) else explicit_path
        if not model_dir:
            return None
        base_dir = resolve_runtime_path(model_dir) or model_dir
        candidate = os.path.join(base_dir, filename)
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
        self._last_final_text = ""
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


class FunASRBackend(ASRBackend):
    def __init__(self, config: dict) -> None:
        self.config = config
        self.asr_cfg = config["asr"]
        self.funasr_cfg = self.asr_cfg.get("funasr", {})
        self.input_sample_rate = int(config["source"]["sample_rate"])
        self.language = self.funasr_cfg.get("language", self.asr_cfg.get("language", "zh"))
        self._server: Optional[FunASRServer] = None
        self._session_id = 0
        self._source_kind = "microphone"
        self._audio_seconds = 0.0
        self._frames: list[np.ndarray] = []
        self._log_dir = ensure_logging_dir(config)

    def initialize(self) -> None:
        if self._server is None:
            self._server = FunASRServer()
        result = self._server.initialize()
        if not result.get("success", False):
            raise BackendInitializationError(result.get("error", "FunASR initialization failed"))

    def start_stream(self, session_id: int, source_kind: str, continuous_segments: bool) -> None:
        self.initialize()
        self._session_id = session_id
        self._source_kind = source_kind
        self._audio_seconds = 0.0
        self._frames.clear()
        if continuous_segments:
            logger.debug("FunASR backend ignores continuous_segments and emits final text only")

    def push_audio(self, samples: np.ndarray) -> list[RecognitionEvent]:
        frame = np.asarray(samples, dtype=np.float32).reshape(-1)
        if frame.size == 0:
            return []
        self._frames.append(frame.copy())
        self._audio_seconds += frame.size / float(self.input_sample_rate)
        return []

    def finalize(self) -> list[RecognitionEvent]:
        if not self._frames or self._server is None:
            self._frames.clear()
            return []

        samples = np.concatenate(self._frames, axis=0)
        self._frames.clear()
        duration = samples.size / float(self.input_sample_rate) if samples.size else 0.0
        temp_path = self._write_temp_wav(samples)
        started_at = time.monotonic()
        try:
            result = self._server.transcribe_audio(temp_path, options=self._build_options())
        finally:
            latency_ms = (time.monotonic() - started_at) * 1000.0
            try:
                os.remove(temp_path)
            except OSError:
                logger.debug("Failed to remove temporary FunASR audio file: %s", temp_path)

        if not result.get("success", False):
            return [
                RecognitionEvent(
                    text="",
                    raw_text="",
                    is_final=True,
                    source_kind=self._source_kind,
                    session_id=self._session_id,
                    duration=duration,
                    latency_ms=latency_ms,
                    language=self.language,
                    confidence=0.0,
                    error=result.get("error", "FunASR transcription failed"),
                )
            ]

        final_text = str(result.get("text", "")).strip()
        raw_text = str(result.get("raw_text", final_text)).strip()
        if not final_text and not raw_text:
            return []

        return [
            RecognitionEvent(
                text=final_text,
                raw_text=raw_text,
                is_final=True,
                source_kind=self._source_kind,
                session_id=self._session_id,
                duration=float(result.get("duration", duration)),
                latency_ms=latency_ms,
                language=str(result.get("language", self.language)),
                confidence=float(result.get("confidence", 0.0)),
            )
        ]

    def cleanup(self) -> None:
        self._frames.clear()
        if self._server is not None:
            try:
                self._server.cleanup()
            finally:
                self._server = None

    def _build_options(self) -> dict:
        return {
            "batch_size_s": self.funasr_cfg.get("batch_size_s", 60),
            "hotword": self.funasr_cfg.get("hotword", ""),
            "use_vad": self.funasr_cfg.get("use_vad", True),
            "use_punc": self.funasr_cfg.get("use_punc", True),
            "language": self.funasr_cfg.get("language", self.language),
        }

    def _write_temp_wav(self, samples: np.ndarray) -> str:
        pcm = np.clip(samples, -1.0, 1.0)
        fd, temp_path = tempfile.mkstemp(
            prefix=f"funasr-session-{self._session_id}-",
            suffix=".wav",
            dir=Path(self._log_dir),
        )
        os.close(fd)
        with wave.open(temp_path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.input_sample_rate)
            wav_file.writeframes((pcm * 32767.0).astype(np.int16).tobytes())
        return temp_path


def create_asr_backend(config: dict) -> ASRBackend:
    backend_name = config["asr"].get("backend", "sherpa-onnx").lower()
    if backend_name == "sherpa-onnx":
        return SherpaOnnxBackend(config)
    if backend_name == "funasr":
        return FunASRBackend(config)
    if backend_name in {"vosk", "qwen3-asr", "qwen"}:
        raise NotImplementedError(
            f"Backend '{backend_name}' is reserved by the new architecture but not implemented yet"
        )
    raise ValueError(f"Unsupported ASR backend: {backend_name}")
