import wave
from io import BytesIO
from unittest.mock import Mock

import av
from fastapi.testclient import TestClient

from app.api import routes
from app.config import Settings
from app.main import app
from app.services.transcription import (
    TranscriptionError,
    TranscriptionResult,
    TranscriptionSegment,
)


def wav_bytes() -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 800)
    return buffer.getvalue()


def media_without_audio_bytes() -> bytes:
    buffer = BytesIO()
    container = av.open(buffer, mode="w", format="matroska")
    stream = container.add_stream("ffv1", rate=1)
    stream.width = 16
    stream.height = 16
    stream.pix_fmt = "yuv420p"
    frame = av.VideoFrame(16, 16, "yuv420p")
    for plane in frame.planes:
        plane.update(bytes(plane.buffer_size))
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return buffer.getvalue()


def test_valid_upload_is_accepted_and_cleaned_up(tmp_path, monkeypatch):
    monkeypatch.setattr(
        routes,
        "settings",
        Settings(max_upload_size_mb=1, temp_dir=str(tmp_path)),
    )

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={"file": ("sample.wav", wav_bytes(), "audio/wav")},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "accepted"
    assert response.json()["extension"] == ".wav"
    assert response.json()["audio_format"] == "wav"
    assert list(tmp_path.iterdir()) == []


def test_invalid_format_returns_client_error_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setattr(
        routes,
        "settings",
        Settings(max_upload_size_mb=1, temp_dir=str(tmp_path)),
    )

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={"file": ("broken.wav", b"not audio", "audio/wav")},
        )

    assert response.status_code == 415
    assert response.json()["detail"] == (
        "The uploaded file is not a supported audio format."
    )
    assert list(tmp_path.iterdir()) == []


def test_media_without_audio_stream_returns_415_and_cleans_up(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        routes,
        "settings",
        Settings(max_upload_size_mb=1, temp_dir=str(tmp_path)),
    )

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={
                "file": (
                    "video.webm",
                    media_without_audio_bytes(),
                    "video/webm",
                )
            },
        )

    assert response.status_code == 415
    assert response.json()["detail"] == (
        "The uploaded file does not contain an audio stream."
    )
    assert list(tmp_path.iterdir()) == []


def test_upload_size_limit_returns_413(tmp_path, monkeypatch):
    monkeypatch.setattr(
        routes,
        "settings",
        Settings(max_upload_size_mb=1, temp_dir=str(tmp_path)),
    )

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={"file": ("large.wav", b"x" * (1024 * 1024 + 1), "audio/wav")},
        )

    assert response.status_code == 413
    assert response.json()["detail"] == (
        "The audio file exceeds the maximum upload size."
    )
    assert list(tmp_path.iterdir()) == []


def test_transcription_returns_text_and_segments_and_cleans_up(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        routes,
        "settings",
        Settings(max_upload_size_mb=1, temp_dir=str(tmp_path)),
    )
    captured_audio = None

    def transcribe(validated_audio):
        nonlocal captured_audio
        captured_audio = validated_audio
        assert validated_audio.path.exists()
        return TranscriptionResult(
            text="hello world",
            segments=(
                TranscriptionSegment(start=0.0, end=1.2, text="hello world"),
            ),
        )

    transcription_mock = Mock()
    transcription_mock.transcribe.side_effect = transcribe
    monkeypatch.setattr(routes, "transcription_service", transcription_mock)

    with TestClient(app) as client:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", wav_bytes(), "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "text": "hello world",
        "segments": [
            {"start": 0.0, "end": 1.2, "text": "hello world"},
        ],
    }
    transcription_mock.transcribe.assert_called_once_with(captured_audio)
    assert list(tmp_path.iterdir()) == []


def test_transcription_invalid_audio_returns_415_and_cleans_up(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        routes,
        "settings",
        Settings(max_upload_size_mb=1, temp_dir=str(tmp_path)),
    )
    transcription_mock = Mock()
    monkeypatch.setattr(routes, "transcription_service", transcription_mock)

    with TestClient(app) as client:
        response = client.post(
            "/transcribe",
            files={"file": ("broken.wav", b"not audio", "audio/wav")},
        )

    assert response.status_code == 415
    assert response.json()["detail"] == (
        "The uploaded file is not a supported audio format."
    )
    transcription_mock.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_transcription_failure_returns_safe_error_and_cleans_up(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        routes,
        "settings",
        Settings(max_upload_size_mb=1, temp_dir=str(tmp_path)),
    )
    transcription_mock = Mock()
    transcription_mock.transcribe.side_effect = TranscriptionError(
        "internal model failure"
    )
    monkeypatch.setattr(routes, "transcription_service", transcription_mock)

    with TestClient(app) as client:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", wav_bytes(), "audio/wav")},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Transcription failed."}
    assert list(tmp_path.iterdir()) == []
