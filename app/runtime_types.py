"""Shared runtime types for streaming voice sessions."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass(slots=True)
class AudioFrame:
    samples: np.ndarray
    sample_rate: int
    channels: int = 1
    source_kind: str = "microphone"
    timestamp: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class RecognitionEvent:
    text: str
    raw_text: str
    is_final: bool
    source_kind: str
    session_id: int
    duration: float = 0.0
    latency_ms: float = 0.0
    language: str = "ru"
    confidence: float = 0.0
    error: Optional[str] = None


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    raw_text: str
    duration: float
    inference_latency: float
    confidence: float
    source_kind: str
    session_id: int
    error: Optional[str] = None

    @classmethod
    def from_event(cls, event: RecognitionEvent) -> "TranscriptionResult":
        return cls(
            text=event.text,
            raw_text=event.raw_text,
            duration=event.duration,
            inference_latency=event.latency_ms / 1000.0,
            confidence=event.confidence,
            source_kind=event.source_kind,
            session_id=event.session_id,
            error=event.error,
        )


class AudioSource(ABC):
    source_kind = "microphone"

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self, timeout: float = 0.1) -> Optional[AudioFrame]:
        raise NotImplementedError

    @abstractmethod
    def flush(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        raise NotImplementedError

    @property
    def is_running(self) -> bool:
        return False

    @property
    def last_error(self) -> Optional[str]:
        return None


class ASRBackend(ABC):
    @abstractmethod
    def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def start_stream(self, session_id: int, source_kind: str, continuous_segments: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def push_audio(self, samples: np.ndarray) -> list[RecognitionEvent]:
        raise NotImplementedError

    @abstractmethod
    def finalize(self) -> list[RecognitionEvent]:
        raise NotImplementedError

    @abstractmethod
    def cleanup(self) -> None:
        raise NotImplementedError


class OutputSink(ABC):
    @abstractmethod
    def handle_event(self, event: RecognitionEvent) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None
