"""HTTP route definitions."""

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import settings
from app.schemas import TranscriptionResponse, UploadResponse
from app.services.audio import (
    AudioTooLargeError,
    AudioUploadError,
    EmptyAudioError,
    StoredAudio,
    remove_temporary_audio,
    store_and_validate_upload,
)
from app.services.transcription import TranscriptionError, transcription_service

router = APIRouter()


@router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Return a minimal process health response."""

    return {"status": "ok"}


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_audio(file: UploadFile = File(...)) -> UploadResponse:
    """Validate an audio upload and remove it after the request completes."""

    temporary_audio = None
    try:
        temporary_audio = await _validated_audio(file)
        return UploadResponse(
            size_bytes=temporary_audio.size_bytes,
            extension=temporary_audio.extension,
            audio_format=temporary_audio.audio_format,
        )
    finally:
        remove_temporary_audio(temporary_audio)
        await file.close()


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(file: UploadFile = File(...)) -> TranscriptionResponse:
    """Validate, transcribe, and clean up an uploaded audio file."""

    temporary_audio = None
    try:
        temporary_audio = await _validated_audio(file)
        result = transcription_service.transcribe(temporary_audio)
        return TranscriptionResponse(
            text=result.text,
            segments=[
                {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                }
                for segment in result.segments
            ],
        )
    except TranscriptionError:
        raise HTTPException(
            status_code=500,
            detail="Transcription failed.",
        ) from None
    finally:
        remove_temporary_audio(temporary_audio)
        await file.close()


async def _validated_audio(file: UploadFile) -> StoredAudio:
    """Reuse the shared upload validation and map safe client errors."""

    try:
        return await store_and_validate_upload(
            file,
            max_size_bytes=settings.max_upload_size_mb * 1024 * 1024,
            temp_dir=settings.temp_dir,
        )
    except EmptyAudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AudioTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except AudioUploadError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
