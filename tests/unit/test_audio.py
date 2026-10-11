from io import BytesIO

import pytest
from fastapi import UploadFile

from app.services.audio import (
    AudioTooLargeError,
    EmptyAudioError,
    UnsupportedAudioError,
    store_and_validate_upload,
)


@pytest.mark.asyncio
async def test_empty_upload_is_rejected(tmp_path):
    upload = UploadFile(filename="empty.wav", file=BytesIO())

    with pytest.raises(EmptyAudioError):
        await store_and_validate_upload(
            upload,
            max_size_bytes=1024,
            temp_dir=str(tmp_path),
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_unsupported_extension_is_rejected(tmp_path):
    upload = UploadFile(filename="audio.txt", file=BytesIO(b"audio"))

    with pytest.raises(UnsupportedAudioError):
        await store_and_validate_upload(
            upload,
            max_size_bytes=1024,
            temp_dir=str(tmp_path),
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_size_limit_is_enforced(tmp_path):
    upload = UploadFile(filename="large.wav", file=BytesIO(b"x" * 11))

    with pytest.raises(AudioTooLargeError):
        await store_and_validate_upload(
            upload,
            max_size_bytes=10,
            temp_dir=str(tmp_path),
        )
