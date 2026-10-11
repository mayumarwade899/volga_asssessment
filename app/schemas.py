"""Request and response schema definitions."""

from typing import Literal

from pydantic import BaseModel


class UploadResponse(BaseModel):
    """Result returned after an upload passes validation."""

    status: Literal["accepted"] = "accepted"
    size_bytes: int
    extension: str
    audio_format: str


class TranscriptionSegmentResponse(BaseModel):
    """A transcription segment with timestamps in seconds."""

    start: float
    end: float
    text: str


class TranscriptionResponse(BaseModel):
    """Transcription text and its segment-level timestamps."""

    text: str
    segments: list[TranscriptionSegmentResponse]
