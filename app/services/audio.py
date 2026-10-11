"""Audio validation and temporary-file services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import av
from fastapi import UploadFile

ALLOWED_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}
UPLOAD_CHUNK_SIZE = 64 * 1024


class AudioUploadError(Exception):
    """Base error for client-correctable audio upload failures."""


class EmptyAudioError(AudioUploadError):
    """Raised when the uploaded file has no content."""


class UnsupportedAudioError(AudioUploadError):
    """Raised when the extension or decoded format is unsupported."""


class AudioTooLargeError(AudioUploadError):
    """Raised when an upload exceeds the configured byte limit."""


@dataclass(frozen=True)
class StoredAudio:
    """Metadata for a validated temporary audio file."""

    path: Path
    size_bytes: int
    extension: str
    audio_format: str


def upload_extension(filename: str | None) -> str:
    """Return a normalized extension without trusting the uploaded filename."""

    if not filename:
        raise UnsupportedAudioError(
            "An audio filename with a supported extension is required."
        )

    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedAudioError("The audio file extension is not supported.")
    return extension


async def store_and_validate_upload(
    upload: UploadFile,
    *,
    max_size_bytes: int,
    temp_dir: str | None = None,
) -> StoredAudio:
    """Store an upload temporarily, validate its audio stream, and return metadata."""

    extension = upload_extension(upload.filename)
    temporary_path: Path | None = None
    size_bytes = 0
    keep_temporary_file = False

    try:
        with NamedTemporaryFile(
            mode="wb",
            suffix=extension,
            dir=temp_dir or None,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

            while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
                size_bytes += len(chunk)
                if size_bytes > max_size_bytes:
                    raise AudioTooLargeError(
                        "The audio file exceeds the maximum upload size."
                    )
                temporary_file.write(chunk)

        if size_bytes == 0:
            raise EmptyAudioError("The audio file is empty.")

        audio_format = _validate_audio_format(temporary_path)
        stored_audio = StoredAudio(
            path=temporary_path,
            size_bytes=size_bytes,
            extension=extension,
            audio_format=audio_format,
        )
        keep_temporary_file = True
        return stored_audio
    except AudioUploadError:
        raise
    except OSError as exc:
        raise AudioUploadError("The audio file could not be stored safely.") from exc
    finally:
        if temporary_path is not None and not keep_temporary_file:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def remove_temporary_audio(audio: StoredAudio | None) -> None:
    """Remove a temporary audio file without exposing cleanup errors to clients."""

    if audio is None:
        return
    try:
        audio.path.unlink(missing_ok=True)
    except OSError:
        pass


def _validate_audio_format(path: Path) -> str:
    """Verify that PyAV can open the file and find an audio stream."""

    try:
        with av.open(str(path)) as container:
            audio_streams = [
                stream for stream in container.streams if stream.type == "audio"
            ]
            if not audio_streams:
                raise UnsupportedAudioError(
                    "The uploaded file does not contain an audio stream."
                )

            next(container.decode(audio=audio_streams[0].index), None)
            return container.format.name
    except UnsupportedAudioError:
        raise
    except Exception as exc:
        raise UnsupportedAudioError(
            "The uploaded file is not a supported audio format."
        ) from exc
