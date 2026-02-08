# Notetaker API

Base URL: `http://127.0.0.1:6684`

Content type: JSON (`Content-Type: application/json`)

Auth: none (local-only)

---

## Health

### GET `/api/health`
Returns server status and version.

Response:
```json
{"status":"ok","version":"v0.1.0.33"}
```

---

## Audio Devices

### GET `/api/audio/devices`
Lists available input devices.

Response:
```json
[
  {"index":0,"name":"MacBook Pro Microphone","max_input_channels":1,"default_samplerate":48000.0}
]
```

---

## Recording

### GET `/api/recording/status`
Returns current recording state.

Response:
```json
{
  "recording": false,
  "recording_id": null,
  "started_at": null,
  "file_path": null,
  "samplerate": null,
  "channels": null,
  "dtype": null
}
```

### POST `/api/recording/start`
Starts recording from a device.

Request:
```json
{
  "device_index": 0,
  "samplerate": 48000,
  "channels": 1
}
```

Response:
```json
{
  "recording": true,
  "recording_id": "uuid",
  "started_at": "2026-02-05T10:23:48.941414",
  "file_path": "/Users/chee/projects/notetaker/data/recordings/<file>.wav",
  "samplerate": 48000,
  "channels": 1,
  "dtype": "int16"
}
```

### POST `/api/recording/stop`
Stops recording.

Response:
```json
{
  "recording": true,
  "recording_id": "uuid",
  "started_at": "2026-02-05T10:23:48.941414",
  "file_path": "/Users/chee/projects/notetaker/data/recordings/<file>.wav",
  "samplerate": 48000,
  "channels": 1,
  "dtype": "int16"
}
```

---

## Transcription (final pass)

### POST `/api/transcribe`
Transcribes a WAV file and returns all segments.

Request:
```json
{
  "audio_path": "/absolute/path/to/file.wav",
  "model_size": "medium"
}
```

Response:
```json
{
  "language": "en",
  "duration": 12.5,
  "segments": [
    {"start":0.0,"end":2.4,"text":"hello there","speaker":null}
  ]
}
```

### POST `/api/transcribe/stream`
Streams segments via Server-Sent Events (SSE).

Request:
```json
{
  "audio_path": "/absolute/path/to/file.wav",
  "model_size": "medium"
}
```

SSE events (`text/event-stream`):
```
data: {"type":"meta","language":"en"}

data: {"type":"segment","start":0.0,"end":2.4,"text":"hello","speaker":null}

data: {"type":"done"}
```

---

## Live Transcription (during recording)

### POST `/api/transcribe/live`
Streams live segments while recording is running.

Request:
```json
{"model_size":"base","meeting_id":"<optional>"}
```

SSE events (`text/event-stream`):
```
data: {"type":"meta","language":"en"}

data: {"type":"segment","start":5.0,"end":7.2,"text":"next point","speaker":null}

data: {"type":"done"}
```

Notes:
- Returns `{"type":"error","message":"Not recording"}` if no active recording.
- Live stream is chunked (see `config.json` `transcription.live_chunk_seconds`).
- When `meeting_id` is provided, live segments are appended to the meeting transcript.

---

## Diarization Settings

### POST `/api/diarization/settings`
Enables or disables diarization and sets the Hugging Face token.

Request:
```json
{
  "enabled": true,
  "model": "pyannote/speaker-diarization-3.1",
  "hf_token": "hf_..."
}
```

Response:
```json
{"status":"ok"}
```

---

## Meetings (JSON storage)

### GET `/api/meetings`
Lists meetings stored in `data/meetings.json`.

### GET `/api/meetings/{meeting_id}`
Returns a single meeting.

### PATCH `/api/meetings/{meeting_id}`
Updates a meeting title.

Request:
```json
{"title":"Weekly Sync"}
```

### PATCH `/api/meetings/{meeting_id}/attendees`
Replaces the attendees list for a meeting.

Request:
```json
{
  "attendees": [
    {"id":"speaker_0","label":"SPEAKER_00","name":"Person 1"},
    {"id":"speaker_1","label":"SPEAKER_01","name":"Person 2"}
  ]
}
```

### PATCH `/api/meetings/{meeting_id}/attendees/{attendee_id}`
Updates a single attendee name.

Request:
```json
{"name":"Alex"}
```

### DELETE `/api/meetings/{meeting_id}`
Deletes a meeting.

Response:
```json
{"status":"ok"}
```

---

## Logs (errors only)

### GET `/api/logs/errors`
Returns latest error lines from server logs.

Response:
```json
{"lines":["[02:21:16] [notetaker.audio] ..."]}
```
