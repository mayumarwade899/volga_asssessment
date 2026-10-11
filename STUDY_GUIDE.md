# Volga Partners Transcription Project Study Guide

This guide is based on the current repository implementation, not only the README or earlier plans.

## 1. Project overview

The project is a local HTTP service that accepts an audio file, validates it, temporarily stores it, transcribes it with Faster-Whisper, and returns JSON containing the full text plus timestamped segments.

The assessment demonstrates:

- API design with FastAPI.
- Audio upload validation.
- Support for multiple audio formats.
- Local speech-to-text using an open-source model.
- Timestamped transcription output.
- Chunked file handling for longer recordings.
- Temporary-file cleanup.
- Automated testing without downloading or running a real model.

Implemented:

- `GET /health`
- `POST /upload`
- `POST /transcribe`
- Extension and content validation
- Empty and oversized upload handling
- Temporary-file cleanup
- Lazy Faster-Whisper model loading
- Segment timestamps
- Mock-based tests

Not implemented:

- Persistent audio or transcript storage
- Background transcription jobs
- Authentication
- Rate limiting
- Automatic retries
- Multi-process model coordination
- Production monitoring
- Word-level timestamps

## 2. Repository structure

### Application files

- `app/` — application package.
- `app/main.py` — creates the FastAPI application and registers routes.
- `app/config.py` — typed environment-backed settings.
- `app/schemas.py` — public API response models.
- `app/api/routes.py` — health, upload, and transcription endpoints.
- `app/services/audio.py` — upload storage and audio validation.
- `app/services/transcription.py` — Faster-Whisper model loading and transcription.
- `__init__.py` files — mark the application, API, and services directories as Python packages.

### Tests

- `tests/` — automated tests.
- `tests/unit/test_audio.py` — low-level upload validation tests.
- `tests/unit/test_transcription.py` — mocked transcription service tests.
- `tests/integration/test_api.py` — API-level tests using FastAPI’s test client.

### Configuration and documentation

- `requirements.txt` — authoritative dependency installation list.
- `pyproject.toml` — package metadata, pytest configuration, and Ruff configuration.
- `.env.example` — example configuration values.
- `.gitignore` — ignores environments, caches, generated artifacts, and real audio files.
- `README.md` — setup, API usage, architecture, limitations, and design decisions.
- `samples/` — currently empty; intended only for carefully reviewed test fixtures.

There is currently no `scripts/` directory and no `PROJECT_PLAN.md`.

Generated folders such as `__pycache__`, `.pytest_cache`, `.ruff_cache`, and `volga_transcription.egg-info` are development artifacts, not application source.

## 3. Complete `/transcribe` request flow

```text
Client
  |
  | multipart/form-data field: file
  v
FastAPI route
  |
  | _validated_audio()
  v
store_and_validate_upload()
  |
  | read 64 KiB chunks
  | write temporary file
  | validate extension
  | validate PyAV container/audio stream
  v
StoredAudio(path=...)
  |
  | transcription_service.transcribe()
  v
TranscriptionService
  |
  | lazy WhisperModel creation
  | model.transcribe(file_path)
  v
TranscriptionResult
  |
  | map internal segments to response schema
  v
JSON response
  |
  | finally block deletes temporary file
  v
HTTP response
```

### Step 1: FastAPI receives the request

`app/main.py` creates the application:

```python
app = FastAPI(...)
app.include_router(router)
```

The router comes from `app/api/routes.py`.

### Step 2: The route receives the upload

`transcribe_audio` accepts:

```python
async def transcribe_audio(file: UploadFile = File(...))
```

The multipart field must be named `file`.

### Step 3: Shared validation runs

The route calls `_validated_audio`, which delegates to `store_and_validate_upload`.

This avoids duplicating upload validation between `/upload` and `/transcribe`.

### Step 4: The upload is written in chunks

`store_and_validate_upload()` creates a temporary file and repeatedly reads:

```python
UPLOAD_CHUNK_SIZE = 64 * 1024
```

Each chunk is written to disk. The application does not call `await file.read()` without a size limit.

The cumulative byte count is checked before the chunk is written:

```python
size_bytes += len(chunk)
if size_bytes > max_size_bytes:
    raise AudioTooLargeError(...)
```

The configured default is 500 MB.

The multipart framework may still buffer or spool some request data before application code receives it. Therefore, the application-level limit is not a complete protection against all pre-routing memory or disk usage.

### Step 5: Extension and content validation

`upload_extension()` checks the filename suffix against:

```python
{".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}
```

The filename is not used as a filesystem path. Only its normalized extension is used.

Then `_validate_audio_format()` opens the temporary file with PyAV and checks that:

1. The container can be opened.
2. At least one audio stream exists.
3. At least one audio frame can be decoded.

This prevents a valid-looking extension from being enough by itself.

### Step 6: A `StoredAudio` object is returned

`StoredAudio` contains:

- Temporary path
- Size in bytes
- Normalized extension
- Detected container format

The path is passed internally to the transcription service.

### Step 7: The model is loaded lazily

`TranscriptionService` starts with:

```python
self._model = None
```

The model is not loaded during application startup.

The first call to `_get_model()` creates:

```python
WhisperModel(
    self.model_name,
    device=self.device,
    compute_type=self.compute_type,
)
```

The current defaults are:

- Model: `base`
- Device: `cpu`
- Compute type: `int8`

The model is then retained and reused for later calls within that process.

### Step 8: Faster-Whisper receives a file path

The service calls:

```python
raw_segments, _ = model.transcribe(str(audio.path))
```

It passes the temporary file path, not a complete in-memory audio byte buffer.

No language is explicitly supplied, so Faster-Whisper performs automatic language detection.

### Step 9: Segment data is converted

Each raw Faster-Whisper segment becomes a `TranscriptionSegment`:

```python
TranscriptionSegment(
    start=float(segment.start),
    end=float(segment.end),
    text=segment.text.strip(),
)
```

The complete text is formed by joining segment text with spaces:

```python
text=" ".join(segment.text for segment in segments)
```

If Faster-Whisper produces no segments, the result is:

```python
text = ""
segments = ()
```

### Step 10: The API response is created

The route converts the internal result into a response like:

```json
{
  "text": "complete transcription",
  "segments": [
    {
      "start": 0.0,
      "end": 2.4,
      "text": "spoken text"
    }
  ]
}
```

Language metadata is not included in the current public response.

### Step 11: Cleanup runs

The route uses `finally`:

```python
finally:
    remove_temporary_audio(temporary_audio)
    await file.close()
```

This runs after success and after handled or unhandled exceptions.

`remove_temporary_audio()` suppresses operating-system cleanup errors. Therefore cleanup is attempted on every route path, but deletion is technically best effort if the operating system refuses the unlink operation.

## 4. Important modules

### `app/main.py`

Purpose: application entry point.

It:

1. Imports the router.
2. Reads the application name from settings.
3. Creates the FastAPI object.
4. Registers the routes.

It does not start Uvicorn itself. Uvicorn imports this module when launched from the command line.

### `app/config.py`

Purpose: central configuration.

`Settings` uses Pydantic Settings, which gives typed configuration values and validation.

Current settings include:

- `app_name`
- `environment`
- `host`
- `port`
- `model_size`
- `device`
- `compute_type`
- `max_upload_size_mb`
- `temp_dir`

Environment variables use the `TRANSCRIPTION_` prefix. For example:

```text
TRANSCRIPTION_MODEL_SIZE=base
TRANSCRIPTION_MAX_UPLOAD_SIZE_MB=500
```

The current code does not configure an explicit `.env` file through `env_file`. Therefore `.env.example` documents expected variables, but the application does not automatically load a local `.env` file unless the environment is otherwise configured.

`host` and `port` are defined settings, but the documented Uvicorn command currently controls host and port through command-line defaults rather than reading these two settings.

### `app/schemas.py`

Purpose: public response contracts.

`UploadResponse` describes `/upload`.

`TranscriptionSegmentResponse` describes one timestamped segment.

`TranscriptionResponse` describes `/transcribe`.

Pydantic validates and serializes these objects into JSON. The public transcription response intentionally contains only:

- Full text
- Segment start
- Segment end
- Segment text

### `app/services/audio.py`

Purpose: safely store and validate uploaded audio.

Important design points:

- Uses `NamedTemporaryFile`.
- Uses `delete=False` so PyAV and Faster-Whisper can open the path.
- Reads chunks of 64 KiB.
- Enforces the configured cumulative size limit.
- Validates both extension and actual content.
- Removes temporary files when validation fails.
- Returns metadata through `StoredAudio`.

PyAV is used for decoding and format inspection. The current implementation does not require a separately installed system FFmpeg executable.

### `app/services/transcription.py`

Purpose: isolate Faster-Whisper behavior from the API layer.

Important types:

- `TranscriptionSegment`
- `TranscriptionResult`
- `TranscriptionError`

The service catches all internal transcription exceptions and exposes only:

```text
Transcription failed.
```

This avoids returning local paths, stack traces, model errors, or other implementation details to API clients.

One important limitation is that the global service has no explicit lock. If multiple requests reach an uninitialized service at the same time, duplicate model initialization may be possible. Inference also runs synchronously.

### `app/api/routes.py`

Purpose: HTTP behavior and error mapping.

It contains:

- `health()`
- `upload_audio()`
- `transcribe_audio()`
- `_validated_audio()`

The route layer translates internal upload exceptions into HTTP statuses:

- Empty file: `400`
- Too large: `413`
- Invalid or unsupported audio: `415`
- Transcription failure: `500`
- Missing multipart field: normally FastAPI validation `422`

The API layer does not expose internal filesystem paths.

## 5. Engineering decisions

### FastAPI

Chosen because it provides:

- Straightforward route declarations.
- Multipart upload support.
- Automatic request validation.
- Pydantic response serialization.
- Easy testing with `TestClient`.

Alternative: Flask or Django. Those would also work, but would require more manual setup for this small API.

### Faster-Whisper

Chosen because it is an open-source implementation suitable for local inference and provides segment timestamps.

Alternative: a hosted speech API. That could reduce local resource requirements but would introduce cost, network dependency, credentials, privacy concerns, and external availability risks.

Training a speech model would be far beyond the scope of this assessment.

### Multilingual `base` model

The `base` model is multilingual and can detect languages automatically. It is a reasonable compromise between:

- Better quality than the smallest models.
- Lower resource use than larger models.
- Practical CPU execution on a developer machine.

The code configures CPU and INT8 by default:

```text
device=cpu
compute_type=int8
```

This avoids assuming a GPU.

The trade-off is that CPU transcription may be slow, especially for long recordings.

### Temporary file plus path-based processing

The upload is written to a temporary file and Faster-Whisper receives its path.

This avoids creating one large application-level `bytes` object for the entire recording and allows PyAV and Faster-Whisper to open the same file.

Alternative: load the entire upload into memory. That is simpler for tiny files but has worse memory behavior for long recordings.

The current approach is better suited to long recordings, although the multipart framework may buffer or spool request data before the route-level chunk loop.

### Size limit

The limit is configured through:

```text
TRANSCRIPTION_MAX_UPLOAD_SIZE_MB=500
```

The route converts this to bytes and passes it to the audio service.

The service checks the running total during chunked reading. This prevents the application from continuing to write an oversized upload after the limit is crossed.

### Timestamps

Faster-Whisper supplies segment `start` and `end` values in seconds. The service converts them to Python floats and returns them unchanged through the public response.

The implementation does not independently verify:

- Segment ordering
- Gaps or overlaps
- Final timestamp against the actual duration
- Word-level timestamps

The mocked tests verify the mapping of known values, but not real model timing accuracy.

### Synchronous endpoint

The route is declared `async`, but it directly calls the synchronous transcription method:

```python
result = transcription_service.transcribe(temporary_audio)
```

This is simple and easy to explain. The limitation is that long inference can block the event loop and delay other requests handled by the same process.

A production alternative would be a worker queue or thread/process execution strategy. That is intentionally outside this assessment’s scope.

### Error handling

Client-correctable upload errors are mapped to specific HTTP statuses.

Unexpected transcription failures become a generic `500` response. This protects internal paths and stack traces.

### Cleanup

The route’s `finally` block ensures cleanup is attempted after both successful and failed transcription.

The audio service also cleans up temporary files if validation fails before returning a `StoredAudio`.

## 6. Tests and verification

### `tests/unit/test_audio.py`

Covers:

- Empty upload.
- Unsupported extension.
- Upload exceeding the configured limit.

These tests focus on the audio service without starting FastAPI.

### `tests/unit/test_transcription.py`

Uses a mocked `WhisperModel`.

It verifies:

- Lazy model loading.
- Model reuse.
- Segment and text mapping.
- Empty transcription results.
- Safe conversion of internal exceptions into `TranscriptionError`.

The mocked model prevents model downloads, network calls, and real inference.

### `tests/integration/test_api.py`

Uses FastAPI’s `TestClient`.

It covers:

- Successful `/upload`.
- Malformed audio.
- Media container without an audio stream.
- Oversized upload.
- Successful `/transcribe`.
- Invalid audio submitted to `/transcribe`.
- Transcription failure.
- Temporary-file cleanup.

The transcription service is replaced with a mock. One test confirms the temporary path exists while the transcription service is executing, then confirms it is removed afterward.

### What the tests prove

They provide good coverage for:

- Request routing.
- Error status mapping.
- Temporary-file lifecycle.
- Model mocking.
- Basic response serialization.
- Empty transcription handling.

### What they do not prove

They do not prove:

- Real Faster-Whisper transcription quality.
- Every supported audio format.
- Real long-audio performance.
- Timestamp accuracy from the actual model.
- Concurrent model initialization behavior.
- Multipart framework buffering behavior.
- Production-scale memory or CPU usage.

Previous validation was reported as 13 passing tests and clean Ruff checks, but those results are historical reports. No test or transcription command was run while creating this guide.

## 7. Assessment requirements checklist

| Requirement | Implementation | Verification | Limitation |
|---|---|---|---|
| Accept an audio file through an API | `POST /upload` and `POST /transcribe` in `app/api/routes.py` | API integration tests | Missing-field behavior relies on FastAPI’s default validation |
| Transcribe speech | Faster-Whisper in `app/services/transcription.py` | Mocked service tests; real smoke test was previously reported | Real inference is not part of automated tests |
| Return full text | `TranscriptionResult.text` and `TranscriptionResponse.text` | Successful transcription API test | Text is formed by joining segment text |
| Return timestamps | `TranscriptionSegment` and response schema | Mocked timestamp assertions | No independent validation of timing continuity |
| Support multiple formats | Extension allowlist plus PyAV validation in `app/services/audio.py` | WAV, malformed WAV, and video-only WebM tests | Every allowed extension is not tested with a valid fixture |
| Handle long recordings | Chunked temporary upload and path-based inference | Code inspection; long recordings were previously reported manually | Synchronous processing can block and be slow |
| Reject empty files | `EmptyAudioError` mapped to `400` | Unit and API tests | None significant for assessment scope |
| Reject unsupported files | Extension and PyAV checks mapped to `415` | Unit and API tests | Framework-level buffering can happen before validation |
| Enforce upload size | Configured 500 MB default and cumulative chunk check | API size-limit test | Not an early server/proxy limit before multipart parsing |
| Clean up temporary files | `finally` blocks and service cleanup | API tests verify empty temp directories | Cleanup errors are suppressed and therefore best effort |
| Avoid exposing sensitive errors | Generic transcription error response | Failure test checks internal path is not returned | Server-side logging is not implemented |
| Explain architecture and limitations | `README.md` | Documentation inspection | README cannot replace runtime verification |
| Explain concurrent uploads, storage, retries, and API exposure | README limitations/design sections | Documentation | Automatic retries and persistent jobs are not implemented |

## 8. Architecture diagram

```text
FastAPI application
│
├── main.py
│   └── registers API router
│
├── api/routes.py
│   ├── GET /health
│   ├── POST /upload
│   └── POST /transcribe
│       ├── calls audio service
│       ├── calls transcription service
│       └── builds response schema
│
├── services/audio.py
│   ├── chunked temporary-file storage
│   ├── extension validation
│   └── PyAV validation
│
├── services/transcription.py
│   ├── lazy Faster-Whisper model loading
│   ├── file-path transcription
│   └── segment mapping
│
└── schemas.py
    └── JSON response models
```

## 9. Five-to-seven-minute learning plan

1. Start with `app/api/routes.py`. Understand the three endpoints and the `/transcribe` request flow.
2. Study `app/services/audio.py`. Focus on chunking, size checks, PyAV validation, and cleanup.
3. Study `app/services/transcription.py`. Focus on lazy model loading, path-based transcription, and segment conversion.
4. Study `app/schemas.py`. Understand how Python objects become JSON responses.
5. Study `app/config.py`. Review model, CPU, INT8, upload-size, and temporary-directory settings.
6. Read `tests/integration/test_api.py`. This shows the complete behavior from the API consumer’s perspective.
7. Finish with `README.md` and `pyproject.toml` for setup, tooling, and limitations.

## 10. Likely reviewer questions

1. **Why use a temporary file?**  
   To avoid holding the entire recording in an application-level bytes buffer and to provide a file path to PyAV and Faster-Whisper.

2. **Why validate both the extension and file contents?**  
   Extensions are easy to fake. PyAV verifies that the content is an openable container with an audio stream.

3. **Why is the model loaded lazily?**  
   Startup stays fast, and model files are loaded only when transcription is actually requested.

4. **Why use the `base` model?**  
   It is a practical multilingual compromise between quality, CPU speed, and memory use.

5. **Why CPU and INT8?**  
   The assessment should work without assuming a GPU.

6. **How are long uploads handled?**  
   Upload data is read in 64 KiB chunks and written to a temporary file. Faster-Whisper receives the file path.

7. **Does the application support concurrent transcription well?**  
   It supports multiple HTTP requests functionally, but synchronous inference can block the event loop and there is no explicit model lock.

8. **What happens if transcription fails?**  
   The client receives a generic `500` response, while the temporary file is still cleaned up.

9. **What does `/upload` do compared with `/transcribe`?**  
   `/upload` validates an audio file and returns metadata. `/transcribe` validates the file and runs inference.

10. **Do automated tests run Faster-Whisper?**  
    No. The model is mocked so tests do not download a model or perform real inference.

## 11. Concepts to understand deeply

1. **Temporary-file lifecycle** — when the file is created, retained, passed to transcription, and deleted.
2. **Lazy model loading** — why `_model` starts as `None` and how the first request initializes it.
3. **Multipart upload versus application-level chunking** — the application reads chunks, but the framework may already buffer or spool multipart data.
4. **Timestamped segments** — each segment has independent start and end times in seconds.
5. **Synchronous work inside an async route** — why a route can be declared `async` while still blocking during CPU-heavy inference.

## 12. Claims to avoid

Do not claim that:

- The service is fully production-ready.
- Upload size is rejected before any multipart buffering occurs.
- Transcription runs in the background.
- The service supports automatic retries.
- Audio or transcripts are persisted.
- Authentication or rate limiting exists.
- All supported formats have been tested with valid real files.
- Timestamps have been independently verified for continuity.
- The model is thread-safe under concurrent first requests.
- The service guarantees cleanup even if the operating system refuses deletion.
- Automated tests prove real transcription quality.
- Faster-Whisper always completes long recordings quickly.
- The API returns detected language metadata.

## Recommended first study point

Open `app/api/routes.py` first.

Study `transcribe_audio` first, then follow its calls into `store_and_validate_upload` and `TranscriptionService.transcribe`.
