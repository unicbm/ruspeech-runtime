"""Audio source implementations for microphone and WASAPI loopback."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

import numpy as np

from .runtime_types import AudioFrame, AudioSource


logger = logging.getLogger(__name__)


class AudioSourceError(RuntimeError):
    """Raised when an audio source cannot be started."""


class QueuedAudioSource(AudioSource):
    def __init__(
        self,
        sample_rate: int,
        frame_ms: int,
        channels: int = 1,
        queue_size: int = 200,
    ) -> None:
        self._sample_rate = int(sample_rate)
        self.frame_ms = int(frame_ms)
        self.channels = int(max(channels, 1))
        self.frame_size = int(self._sample_rate * self.frame_ms / 1000)
        if self.frame_size <= 0:
            raise ValueError("frame_ms too small for selected sample rate")

        self._queue: "queue.Queue[AudioFrame]" = queue.Queue(maxsize=queue_size)
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._last_error: Optional[str] = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def read(self, timeout: float = 0.1) -> Optional[AudioFrame]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _enqueue(self, samples: np.ndarray) -> None:
        frame = AudioFrame(
            samples=samples.astype(np.float32, copy=False),
            sample_rate=self.sample_rate,
            channels=1,
            source_kind=self.source_kind,
        )
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            logger.warning("%s audio queue full, dropping frame", self.source_kind)


class MicrophoneSource(QueuedAudioSource):
    source_kind = "microphone"

    def __init__(
        self,
        sample_rate: int,
        frame_ms: int,
        device: Optional[str] = None,
        channels: int = 1,
    ) -> None:
        super().__init__(sample_rate=sample_rate, frame_ms=frame_ms, channels=channels)
        self.device = device
        self._stream = None

    def start(self) -> None:
        with self._lock:
            if self._running.is_set():
                return

            try:
                import sounddevice as sd
            except ImportError as exc:
                self._last_error = str(exc)
                raise AudioSourceError("sounddevice is required for microphone capture") from exc

            self.flush()
            self._last_error = None
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    blocksize=self.frame_size,
                    channels=self.channels,
                    dtype="float32",
                    callback=self._callback,
                    device=self.device,
                )
                self._stream.start()
            except Exception as exc:
                self._last_error = str(exc)
                raise AudioSourceError(f"Unable to start microphone capture: {exc}") from exc

            self._running.set()
            logger.info(
                "Microphone source started, sample_rate=%sHz frame_size=%s device=%s",
                self.sample_rate,
                self.frame_size,
                self.device or "default",
            )

    def stop(self) -> None:
        with self._lock:
            if not self._running.is_set():
                return
            try:
                if self._stream is not None:
                    self._stream.stop()
                    self._stream.close()
            finally:
                self._stream = None
                self._running.clear()
                logger.info("Microphone source stopped")

    def _callback(self, indata, frames, time_info, status) -> None:  # type: ignore[override]
        if status:
            logger.warning("Microphone stream status: %s", status)

        samples = np.asarray(indata, dtype=np.float32)
        if samples.ndim == 2:
            mono = samples.mean(axis=1)
        else:
            mono = samples.reshape(-1)
        self._enqueue(mono.copy())


class WasapiLoopbackSource(QueuedAudioSource):
    source_kind = "loopback"

    def __init__(
        self,
        sample_rate: int,
        frame_ms: int,
        device: Optional[str] = None,
        channels: int = 2,
    ) -> None:
        super().__init__(sample_rate=sample_rate, frame_ms=frame_ms, channels=channels)
        self.device = device
        self._thread: Optional[threading.Thread] = None
        self._microphone = None

    def start(self) -> None:
        with self._lock:
            if self._running.is_set():
                return

            try:
                import soundcard as sc
            except ImportError as exc:
                self._last_error = str(exc)
                raise AudioSourceError("soundcard is required for WASAPI loopback capture") from exc

            self.flush()
            self._last_error = None
            self._microphone = self._resolve_loopback_device(sc)
            self._running.set()
            self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="LoopbackSource")
            self._thread.start()
            logger.info(
                "Loopback source started, sample_rate=%sHz frame_size=%s speaker=%s",
                self.sample_rate,
                self.frame_size,
                getattr(self._microphone, "name", self.device or "default"),
            )

    def stop(self) -> None:
        with self._lock:
            if not self._running.is_set():
                return
            self._running.clear()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._microphone = None
        logger.info("Loopback source stopped")

    def _resolve_loopback_device(self, soundcard_module):
        microphones = []
        try:
            microphones = list(soundcard_module.all_microphones(include_loopback=True))
        except Exception:
            logger.debug("Unable to enumerate loopback microphones", exc_info=True)

        if self.device:
            for microphone in microphones:
                if self.device.lower() in getattr(microphone, "name", "").lower():
                    return microphone
            for speaker in soundcard_module.all_speakers():
                if self.device.lower() in speaker.name.lower():
                    try:
                        return soundcard_module.get_microphone(
                            id=str(getattr(speaker, "id", speaker.name)),
                            include_loopback=True,
                        )
                    except Exception:
                        logger.debug("Fallback loopback lookup by speaker id failed", exc_info=True)
            raise AudioSourceError(f"Loopback speaker not found: {self.device}")

        speaker = soundcard_module.default_speaker()
        if speaker is None:
            raise AudioSourceError("No default speaker available for loopback capture")
        for microphone in microphones:
            if getattr(speaker, "name", "").lower() in getattr(microphone, "name", "").lower():
                return microphone
        try:
            return soundcard_module.get_microphone(
                id=str(getattr(speaker, "id", speaker.name)),
                include_loopback=True,
            )
        except Exception as exc:
            raise AudioSourceError(f"Unable to resolve default loopback speaker: {exc}") from exc

    def _capture_loop(self) -> None:
        assert self._microphone is not None
        try:
            with self._microphone.recorder(
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=self.frame_size,
            ) as recorder:
                while self._running.is_set():
                    samples = recorder.record(self.frame_size)
                    if samples is None:
                        continue
                    frame = np.asarray(samples, dtype=np.float32)
                    if frame.size == 0:
                        continue
                    if frame.ndim == 2:
                        mono = frame.mean(axis=1)
                    else:
                        mono = frame.reshape(-1)
                    self._enqueue(mono.copy())
        except Exception as exc:
            self._last_error = str(exc)
            logger.error("Loopback capture failed: %s", exc, exc_info=True)
            self._running.clear()


def create_audio_source(config: dict) -> AudioSource:
    source_cfg = config["source"]
    source_type = source_cfg.get("type", "microphone").lower()

    if source_type == "microphone":
        return MicrophoneSource(
            sample_rate=source_cfg["sample_rate"],
            frame_ms=source_cfg["frame_ms"],
            device=source_cfg.get("device"),
            channels=source_cfg.get("channels", 1),
        )

    if source_type == "loopback":
        return WasapiLoopbackSource(
            sample_rate=source_cfg["sample_rate"],
            frame_ms=source_cfg["frame_ms"],
            device=source_cfg.get("device"),
            channels=source_cfg.get("channels", 2),
        )

    raise ValueError(f"Unsupported audio source: {source_type}")
