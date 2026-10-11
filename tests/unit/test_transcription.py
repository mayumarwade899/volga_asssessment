from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.services.audio import StoredAudio
from app.services.transcription import TranscriptionError, TranscriptionService


@pytest.fixture
def validated_audio(tmp_path: Path) -> StoredAudio:
    path = tmp_path / "validated.wav"
    path.write_bytes(b"validated audio placeholder")
    return StoredAudio(
        path=path,
        size_bytes=path.stat().st_size,
        extension=".wav",
        audio_format="wav",
    )


def test_model_loads_lazily_and_is_reused(validated_audio):
    model = Mock()
    model.transcribe.side_effect = lambda path: (
        iter([SimpleNamespace(start=0.0, end=1.25, text=" hello ")]),
        SimpleNamespace(),
    )

    with patch(
        "app.services.transcription.WhisperModel", return_value=model
    ) as model_class:
        service = TranscriptionService(
            model_name="tiny",
            device="cpu",
            compute_type="int8",
        )
        assert model_class.call_count == 0

        first_result = service.transcribe(validated_audio)
        second_result = service.transcribe(validated_audio)

    model_class.assert_called_once_with(
        "tiny",
        device="cpu",
        compute_type="int8",
    )
    assert model.transcribe.call_count == 2
    assert first_result.text == "hello"
    assert first_result.segments[0].start == 0.0
    assert first_result.segments[0].end == 1.25
    assert second_result == first_result


def test_empty_transcription_result_returns_empty_output(validated_audio):
    model = Mock()
    model.transcribe.return_value = (
        iter(()),
        SimpleNamespace(language="en"),
    )

    with patch("app.services.transcription.WhisperModel", return_value=model):
        result = TranscriptionService().transcribe(validated_audio)

    assert result.text == ""
    assert result.segments == ()


def test_transcription_failure_is_safe(validated_audio):
    model = Mock()
    model.transcribe.side_effect = RuntimeError(
        f"cannot read {validated_audio.path}"
    )

    with patch("app.services.transcription.WhisperModel", return_value=model):
        service = TranscriptionService()

        with pytest.raises(
            TranscriptionError,
            match="^Transcription failed\\.$",
        ) as error:
            service.transcribe(validated_audio)

    assert str(validated_audio.path) not in str(error.value)
