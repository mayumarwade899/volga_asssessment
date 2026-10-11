"""Faster-Whisper transcription service."""

from __future__ import annotations

from dataclasses import dataclass

from faster_whisper import WhisperModel

from app.config import settings
from app.services.audio import StoredAudio


class TranscriptionError(RuntimeError):
    """Raised when model loading or transcription fails."""


@dataclass(frozen=True)
class TranscriptionSegment:
    """A piece of transcription with its time interval in seconds."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    """Complete transcription text and its segment-level timestamps."""

    text: str
    segments: tuple[TranscriptionSegment, ...]


class TranscriptionService:
    """Lazily load and reuse one configured Faster-Whisper model."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ) -> None:
        self.model_name = model_name or settings.model_size
        self.device = device or settings.device
        self.compute_type = compute_type or settings.compute_type
        self._model: WhisperModel | None = None

    def transcribe(self, audio: StoredAudio) -> TranscriptionResult:
        """Transcribe a validated audio file without exposing internal errors."""

        try:
            model = self._get_model()
            raw_segments, _ = model.transcribe(str(audio.path))
            segments = tuple(
                TranscriptionSegment(
                    start=float(segment.start),
                    end=float(segment.end),
                    text=segment.text.strip(),
                )
                for segment in raw_segments
            )
            return TranscriptionResult(
                text=" ".join(segment.text for segment in segments),
                segments=segments,
            )
        except Exception:
            raise TranscriptionError("Transcription failed.") from None

    def _get_model(self) -> WhisperModel:
        """Load the model once, only when transcription is requested."""

        if self._model is None:
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model


transcription_service = TranscriptionService()
