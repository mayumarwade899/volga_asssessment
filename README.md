# Volga Partners Transcription Assessment

This project is a small local speech-to-text API. It accepts an audio upload,
validates it with PyAV, transcribes it with the local multilingual
Faster-Whisper `base` model, and returns the full text with segment timestamps.

The scope is deliberately limited to the assessment workflow. Audio and
transcripts are not stored permanently, and there is no database, queue, cloud
service, authentication layer, or paid API.

## Features

- `GET /health` for a simple process check.
- `POST /upload` for audio validation and metadata.
- `POST /transcribe` for local transcription.
- Extension and decoded-content validation.
- Configurable 500 MB default upload limit.
- Chunked upload writes to a temporary file.
- Segment-level `start`, `end`, and `text` values in seconds.
- Lazy model loading and reuse within a server process.
- Mocked tests that do not download or run a real model.

## Architecture

The request flow is intentionally short:

1. FastAPI receives a multipart upload in the `file` field.
2. `app/services/audio.py` checks the extension, copies the upload to a
   temporary file in 64 KiB chunks, and asks PyAV to open and decode an audio
   stream.
3. `app/services/transcription.py` lazily loads Faster-Whisper and passes it
   the temporary file path, not an application-level audio byte buffer.
4. `app/api/routes.py` maps the result to the public JSON response.
5. A `finally` block closes the upload and removes the temporary file.

FastAPI is a good fit for a small typed HTTP service with built-in request
validation and interactive API documentation. Faster-Whisper provides local
speech recognition without a paid API or cloud dependency. The multilingual
`base` model is the default because it supports languages beyond English while
keeping CPU speed and memory use reasonable for a developer machine. CPU with
`int8` compute is the default, so a GPU is not required.

## Project structure

```text
app/
├── __init__.py              # Application package
├── main.py                  # FastAPI app and route registration
├── config.py                # Environment-backed settings
├── schemas.py               # Public response models
├── api/
│   ├── __init__.py
│   └── routes.py            # HTTP endpoints and error mapping
└── services/
    ├── __init__.py
    ├── audio.py             # Validation and temporary-file lifecycle
    └── transcription.py     # Model lifecycle and segment conversion
tests/
├── unit/                    # Audio and transcription service tests
└── integration/             # FastAPI endpoint tests
samples/                     # Small, non-sensitive fixtures only
```

`.env.example` lists non-secret configuration examples. `requirements.txt` is
the single dependency installation list; `pyproject.toml` contains package
metadata and pytest/Ruff configuration.

## Prerequisites and setup

- Python 3.11 (the project was verified with Python 3.11.9).
- Windows PowerShell.
- Enough disk space for temporary uploads and the downloaded model.
- System FFmpeg is not required for the current file-based path. Faster-Whisper
  uses PyAV for decoding. FFmpeg would only be needed if conversion or other
  preprocessing were added.

From the project root:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If activation is not possible, use the environment directly:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The first real transcription downloads the configured model if it is not in
the local Faster-Whisper/Hugging Face cache. Model loading is lazy, so tests
and application startup do not intentionally download a model.

## Configuration

Settings use the `TRANSCRIPTION_` environment-variable prefix. Defaults come
from `app/config.py`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRANSCRIPTION_APP_NAME` | `Volga Transcription Service` | FastAPI title |
| `TRANSCRIPTION_ENVIRONMENT` | `development` | Environment label |
| `TRANSCRIPTION_HOST` | `127.0.0.1` | Available host setting |
| `TRANSCRIPTION_PORT` | `8000` | Available port setting |
| `TRANSCRIPTION_MODEL_SIZE` | `base` | Faster-Whisper model |
| `TRANSCRIPTION_DEVICE` | `cpu` | Inference device |
| `TRANSCRIPTION_COMPUTE_TYPE` | `int8` | CPU compute type |
| `TRANSCRIPTION_MAX_UPLOAD_SIZE_MB` | `500` | Maximum application upload size |
| `TRANSCRIPTION_TEMP_DIR` | unset | Optional temporary-file directory |

When `TRANSCRIPTION_TEMP_DIR` is unset, the operating system temporary
directory is used. The example file is a reference; the current settings
model reads environment variables and does not automatically load a `.env`
file.

## Run the API

With the virtual environment activated:

```powershell
python -m uvicorn app.main:app --reload
```

The default local address is `http://127.0.0.1:8000`. The same command can be
run without activation as:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

FastAPI's interactive documentation is available at `/docs`.

## API usage

### `GET /health`

Returns:

```json
{"status": "ok"}
```

PowerShell:

```powershell
curl.exe -sS "http://127.0.0.1:8000/health"
```

### `POST /upload`

Send an audio file as multipart form data in the field named `file`:

```powershell
curl.exe -sS -X POST "http://127.0.0.1:8000/upload" -F "file=@C:\path\to\audio.wav"
```

Successful response (`201 Created`):

```json
{
  "status": "accepted",
  "size_bytes": 123456,
  "extension": ".wav",
  "audio_format": "wav"
}
```

### `POST /transcribe`

The same multipart field is validated and transcribed locally:

```powershell
curl.exe -sS -X POST "http://127.0.0.1:8000/transcribe" -F "file=@C:\path\to\audio.wav"
```

Successful response (`200 OK`):

```json
{
  "text": "hello world",
  "segments": [
    {"start": 0.0, "end": 1.2, "text": "hello world"}
  ]
}
```

Timestamps are model-provided segment start and end times in seconds. The API
does not provide word-level timestamps or detected-language metadata.

## Supported audio and errors

The exact allowlist is `.aac`, `.flac`, `.m4a`, `.mp3`, `.ogg`, `.wav`, and
`.webm`. The extension is checked first, then PyAV must open the file, find an
audio stream, and decode at least one frame. A matching extension alone is not
enough.

Current error responses are:

- `400 Bad Request`: the file is empty.
- `413 Request Entity Too Large`: the file exceeds the configured 500 MB
  default limit.
- `415 Unsupported Media Type`: missing/unsupported extension, malformed audio,
  or a valid container with no audio stream.
- `422 Unprocessable Entity`: FastAPI request validation, such as a missing
  multipart `file` field.
- `500 Internal Server Error`: model loading or transcription failure. Internal
  paths and stack traces are not returned.

Uploads are copied to temporary files in 64 KiB chunks. The configured
500 MB limit is checked as the application copies those chunks into temporary
storage, before an over-limit chunk is written. The application therefore does
not create one complete in-memory bytes copy of the audio. Faster-Whisper
receives the temporary path and performs file-based decoding.

FastAPI/Starlette multipart parsing may still buffer or spool request data
before this application-level check runs. A production deployment should also
enforce an early request-body limit at the reverse proxy or server boundary;
that hardening is not implemented by this assessment project.

For long-audio verification, the project owner manually tested recordings
around one hour or longer. Those requests returned transcription text with
timestamped segments. This is a manual smoke-test result, not an automated
test guarantee. The current endpoint processes transcription synchronously,
so a long recording may take time and keep the HTTP request open.

Temporary files are removed after both successful and failed upload or
transcription requests. Audio and transcripts are not persisted.

## Tests and linting

Run the automated checks with the virtual environment activated:

```powershell
python -m pytest
ruff check .
```

Or use the environment directly:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
```

The current test suite contains 13 tests. The verified result is `13 passed`
with one non-blocking Starlette/HTTPX deprecation warning. The tests use
generated audio bytes, PyAV containers, and mocked transcription
services/models. In particular, transcription service tests do not download a
model or perform real inference. The automated suite does not replace the
manual long-audio smoke test described above.

## Limitations and future improvements

Current limitations:

- Transcription is synchronous in the request path. Long recordings can make
  the request slow and block the event loop.
- The model is reused within one process, but there is no explicit concurrency
  control for multiple workers or threads.
- There is no authentication, rate limiting, persistent job status, automatic
  retry, or durable recovery.
- Application-level size validation happens after multipart parsing may already
  have buffered or spooled request data.

Reasonable production improvements would be request-size limits at the proxy or
server boundary, background jobs for long recordings, explicit resource and
concurrency limits, persistent results, authentication, rate limiting, and a
defined retry policy. These are intentionally outside the simple assessment
implementation.
