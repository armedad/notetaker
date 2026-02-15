from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

# #region agent log
_DEBUG_LOG_PATH = os.path.join(os.getcwd(), "logs", "debug.log")


def _dbg_ndjson(*, location: str, message: str, data: dict, run_id: str, hypothesis_id: str) -> None:
    """Write one NDJSON debug line for this session. Best-effort only."""
    try:
        payload = {
            "id": f"log_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}",
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


# #endregion


class MeetingStore:
    def __init__(self, meetings_dir: str) -> None:
        self._meetings_dir = meetings_dir
        self._lock = threading.RLock()
        self._events_lock = threading.RLock()
        self._events: list[dict] = []
        self._events_condition = threading.Condition(self._events_lock)  # For push-based SSE
        self._logger = logging.getLogger("notetaker.meetings")
        self._trace = logging.getLogger("notetaker.trace")
        os.makedirs(self._meetings_dir, exist_ok=True)

    def _trace_log(self, stage: str, **fields) -> None:
        payload = " ".join(f"{k}={fields[k]!r}" for k in sorted(fields.keys()))
        self._trace.info("TRACE stage=%s ts=%s %s", stage, datetime.utcnow().isoformat(), payload)

    def _list_meeting_paths(self) -> list[str]:
        try:
            names = os.listdir(self._meetings_dir)
        except OSError as exc:
            self._logger.warning("Failed to list meetings dir: %s", exc)
            return []
        paths: list[str] = []
        for name in names:
            if not name.endswith(".json"):
                continue
            paths.append(os.path.join(self._meetings_dir, name))
        return sorted(paths)

    def _find_meeting_path(self, meeting_id: str) -> Optional[str]:
        suffix = f"__{meeting_id}.json"
        for path in self._list_meeting_paths():
            if os.path.basename(path).endswith(suffix):
                return path
        return None

    @staticmethod
    def _parse_created_at(created_at: str) -> datetime:
        # created_at is historically stored as naive UTC isoformat without timezone.
        dt = datetime.fromisoformat(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @classmethod
    def _format_local_filename_dt(cls, created_at: str) -> str:
        dt_utc = cls._parse_created_at(created_at)
        dt_local = dt_utc.astimezone()  # local tz
        # Example: 20260211T093012-0800
        return dt_local.strftime("%Y%m%dT%H%M%S%z")

    @classmethod
    def _meeting_filename(cls, created_at: str, meeting_id: str) -> str:
        return f"{cls._format_local_filename_dt(created_at)}__{meeting_id}.json"

    def _meeting_path_for_new(self, created_at: str, meeting_id: str) -> str:
        return os.path.join(self._meetings_dir, self._meeting_filename(created_at, meeting_id))

    def _read_meeting_file(self, path: str) -> Optional[dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError) as exc:
            self._logger.warning("Failed to read meeting file: %s error=%s", path, exc)
        return None

    def _write_meeting_file(self, path: str, meeting: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(meeting, f, indent=2)
        os.replace(temp_path, path)
        # #region agent log
        _dbg_ndjson(
            location="app/services/meeting_store.py:_write_meeting_file",
            message="meeting file written",
            data={
                "meeting_id": meeting.get("id"),
                "path_name": os.path.basename(path),
                "status": meeting.get("status"),
            },
            run_id="pre-fix",
            hypothesis_id="H4",
        )
        # #endregion

    def list_meetings(self) -> list[dict]:
        with self._lock:
            # #region agent log
            try:
                paths = self._list_meeting_paths()
                _dbg_ndjson(
                    location="app/services/meeting_store.py:list_meetings",
                    message="list_meetings paths",
                    data={
                        "meetings_dir": self._meetings_dir,
                        "path_count": len(paths),
                        "path_names": [os.path.basename(p) for p in paths[:20]],
                    },
                    run_id="pre-fix",
                    hypothesis_id="H2",
                )
            except Exception as exc:
                _dbg_ndjson(
                    location="app/services/meeting_store.py:list_meetings",
                    message="list_meetings paths error",
                    data={"exc_type": type(exc).__name__, "exc": str(exc)[:300]},
                    run_id="pre-fix",
                    hypothesis_id="H2",
                )
            # #endregion
            meetings: list[dict] = []
            for path in self._list_meeting_paths():
                meeting = self._read_meeting_file(path)
                if not meeting:
                    continue
                updated = False
                if not meeting.get("summary_state"):
                    meeting["summary_state"] = self._default_summary_state()
                    updated = True
                if "manual_notes" not in meeting:
                    meeting["manual_notes"] = ""
                    updated = True
                if "manual_summary" not in meeting:
                    meeting["manual_summary"] = ""
                    updated = True
                updated = self._ensure_title_fields(meeting) or updated
                if "schema_version" not in meeting:
                    meeting["schema_version"] = 1
                    updated = True
                if updated:
                    self._write_meeting_file(path, meeting)
                meetings.append(meeting)
            # #region agent log
            try:
                _dbg_ndjson(
                    location="app/services/meeting_store.py:list_meetings",
                    message="list_meetings result",
                    data={
                        "meeting_count": len(meetings),
                        "meeting_ids": [m.get("id") for m in meetings[:20]],
                    },
                    run_id="pre-fix",
                    hypothesis_id="H2",
                )
            except Exception:
                pass
            # #endregion
            return sorted(meetings, key=lambda m: m.get("created_at") or "", reverse=True)

    def get_storage_path(self) -> str:
        # Kept for compatibility with existing callers; now returns the directory.
        return self._meetings_dir

    def publish_event(
        self, event_type: str, meeting_id: Optional[str], data: Optional[dict] = None
    ) -> None:
        with self._events_condition:
            payload = {
                "type": event_type,
                "meeting_id": meeting_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
            if data:
                payload["data"] = data
            self._events.append(payload)
            if len(self._events) > 200:
                self._events = self._events[-100:]
            # Wake up any waiting SSE connections immediately
            self._events_condition.notify_all()

    def publish_finalization_status(
        self,
        meeting_id: str,
        status_text: str,
        progress: Optional[float] = None,
    ) -> None:
        """Publish a finalization status update for a meeting.
        
        Args:
            meeting_id: The meeting being finalized
            status_text: Human-readable status text (e.g., "Analyzing speakers...")
            progress: Optional progress percentage (0.0 to 1.0)
        """
        with self._events_condition:
            payload = {
                "type": "finalization_status",
                "meeting_id": meeting_id,
                "status_text": status_text,
                "progress": progress,
                "timestamp": datetime.utcnow().isoformat(),
            }
            self._events.append(payload)
            if len(self._events) > 200:
                self._events = self._events[-100:]
            # Wake up any waiting SSE connections immediately
            self._events_condition.notify_all()
        
        # Also update the meeting's finalization_status field
        self.update_finalization_status(meeting_id, status_text, progress)

    def update_finalization_status(
        self,
        meeting_id: str,
        status_text: str,
        progress: Optional[float] = None,
    ) -> Optional[dict]:
        """Update the finalization_status field in the meeting file.
        
        This persists the status so clients can poll for it.
        """
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            
            meeting["finalization_status"] = {
                "status_text": status_text,
                "progress": progress,
                "updated_at": datetime.utcnow().isoformat(),
            }
            self._write_meeting_file(path, meeting)
            return meeting

    def clear_finalization_status(self, meeting_id: str) -> Optional[dict]:
        """Clear the finalization_status field when finalization completes."""
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            
            if "finalization_status" in meeting:
                del meeting["finalization_status"]
            self._write_meeting_file(path, meeting)
            return meeting

    def get_events_since(self, cursor: int) -> tuple[list[dict], int]:
        with self._events_condition:
            events = self._events[cursor:]
            return events, len(self._events)

    def wait_for_events(self, cursor: int, timeout: float = 5.0) -> tuple[list[dict], int]:
        """Block until new events are available or timeout expires.
        
        This enables true push-based SSE - the caller blocks until notified
        that new events exist, rather than polling.
        
        Args:
            cursor: Current position in the events list
            timeout: Max seconds to wait (for heartbeat/keepalive)
            
        Returns:
            Tuple of (new events since cursor, new cursor position)
        """
        with self._events_condition:
            # Check if events already available
            if cursor < len(self._events):
                events = self._events[cursor:]
                return events, len(self._events)
            
            # Wait for notification or timeout
            self._events_condition.wait(timeout=timeout)
            
            # Return whatever events are now available
            events = self._events[cursor:]
            return events, len(self._events)

    def get_meeting(self, meeting_id: str) -> Optional[dict]:
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            # #region agent log
            _dbg_ndjson(
                location="app/services/meeting_store.py:get_meeting",
                message="get_meeting path lookup",
                data={
                    "meeting_id": meeting_id,
                    "path_found": bool(path),
                    "path_name": os.path.basename(path) if path else None,
                },
                run_id="pre-fix",
                hypothesis_id="H2",
            )
            # #endregion
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            updated = False
            if not meeting.get("summary_state"):
                meeting["summary_state"] = self._default_summary_state()
                updated = True
            if "manual_notes" not in meeting:
                meeting["manual_notes"] = ""
                updated = True
            if "manual_summary" not in meeting:
                meeting["manual_summary"] = ""
                updated = True
            updated = self._ensure_title_fields(meeting) or updated
            if "schema_version" not in meeting:
                meeting["schema_version"] = 1
                updated = True
            if updated:
                self._write_meeting_file(path, meeting)
            return meeting

    def get_meeting_by_audio_path(self, audio_path: str) -> Optional[dict]:
        with self._lock:
            for path in self._list_meeting_paths():
                meeting = self._read_meeting_file(path)
                if not meeting:
                    continue
                if meeting.get("audio_path") == audio_path:
                    updated = False
                    if not meeting.get("summary_state"):
                        meeting["summary_state"] = self._default_summary_state()
                        updated = True
                    if "manual_notes" not in meeting:
                        meeting["manual_notes"] = ""
                        updated = True
                    if "manual_summary" not in meeting:
                        meeting["manual_summary"] = ""
                        updated = True
                    updated = self._ensure_title_fields(meeting) or updated
                    if "schema_version" not in meeting:
                        meeting["schema_version"] = 1
                        updated = True
                    if updated:
                        self._write_meeting_file(path, meeting)
                    return meeting
            return None

    def create_from_recording(self, recording: dict, status: str = "in_progress") -> dict:
        with self._lock:
            meeting_id = recording.get("recording_id") or str(uuid.uuid4())
            session_id = recording.get("session_id") or meeting_id  # Use recording_id as session_id for mic
            existing_path = self._find_meeting_path(meeting_id)
            if existing_path:
                existing = self._read_meeting_file(existing_path) or {}
                existing["schema_version"] = existing.get("schema_version", 1)
                existing["audio_path"] = recording.get("file_path")
                existing["recording_id"] = recording.get("recording_id")
                existing["session_id"] = existing.get("session_id") or session_id
                existing["samplerate"] = recording.get("samplerate")
                existing["channels"] = recording.get("channels")
                existing["status"] = status
                if not existing.get("summary_state"):
                    existing["summary_state"] = self._default_summary_state()
                if "manual_notes" not in existing:
                    existing["manual_notes"] = ""
                if "manual_summary" not in existing:
                    existing["manual_summary"] = ""
                if status == "completed":
                    existing["ended_at"] = datetime.utcnow().isoformat()
                if status == "in_progress":
                    existing["ended_at"] = None
                self._ensure_title_fields(existing)
                self._write_meeting_file(existing_path, existing)
                # #region agent log
                _dbg_ndjson(
                    location="app/services/meeting_store.py:create_from_recording",
                    message="create_from_recording updated existing",
                    data={
                        "meeting_id": meeting_id,
                        "path_name": os.path.basename(existing_path),
                        "status": status,
                    },
                    run_id="pre-fix",
                    hypothesis_id="H4",
                )
                # #endregion
                self.publish_event(
                    "meeting_completed" if status == "completed" else "meeting_started",
                    existing.get("id"),
                )
                return existing

            created_at = recording.get("started_at") or datetime.utcnow().isoformat()
            meeting = {
                "schema_version": 1,
                "id": meeting_id,
                "title": f"Meeting {created_at}",
                "title_source": "default",
                "title_generated_at": None,
                "created_at": created_at,
                "audio_path": recording.get("file_path"),
                "recording_id": recording.get("recording_id"),
                "session_id": session_id,
                "samplerate": recording.get("samplerate"),
                "channels": recording.get("channels"),
                "status": status,
                "ended_at": None,
                "attendees": [],
                "transcript": None,
                "summary": None,
                "action_items": [],
                "summary_state": self._default_summary_state(),
                "manual_notes": "",
                "manual_summary": "",
            }
            if status == "completed":
                meeting["ended_at"] = datetime.utcnow().isoformat()
            path = self._meeting_path_for_new(created_at, meeting_id)
            self._write_meeting_file(path, meeting)
            # #region agent log
            _dbg_ndjson(
                location="app/services/meeting_store.py:create_from_recording",
                message="create_from_recording created new",
                data={
                    "meeting_id": meeting_id,
                    "path_name": os.path.basename(path),
                    "status": status,
                },
                run_id="pre-fix",
                hypothesis_id="H4",
            )
            # #endregion
            self._logger.info("Meeting created: id=%s session_id=%s", meeting_id, session_id)
            self.publish_event(
                "meeting_completed" if status == "completed" else "meeting_started",
                meeting_id,
            )
            return meeting

    def create_file_meeting(
        self,
        audio_path: str,
        samplerate: Optional[int] = None,
        channels: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """Create a meeting from a file input.
        
        Args:
            audio_path: Path to the audio file (should be WAV after conversion)
            samplerate: Audio sample rate (from conversion, matches mic format)
            channels: Audio channel count (from conversion, matches mic format)
            session_id: Optional session ID from AudioDataSource (generated if not provided)
        """
        with self._lock:
            meeting_id = str(uuid.uuid4())
            created_at = datetime.utcnow().isoformat()
            meeting = {
                "schema_version": 1,
                "id": meeting_id,
                "title": f"Meeting {created_at}",
                "title_source": "default",
                "title_generated_at": None,
                "created_at": created_at,
                "audio_path": audio_path,
                "recording_id": None,
                "session_id": session_id or str(uuid.uuid4()),
                "samplerate": samplerate,
                "channels": channels,
                "status": "in_progress",
                "ended_at": None,
                "attendees": [],
                "transcript": None,
                "summary": None,
                "action_items": [],
                "summary_state": self._default_summary_state(),
                "manual_notes": "",
                "manual_summary": "",
            }
            path = self._meeting_path_for_new(created_at, meeting_id)
            self._write_meeting_file(path, meeting)
            self._logger.info("File meeting created: id=%s audio=%s session_id=%s", meeting_id, audio_path, meeting["session_id"])
            self.publish_event("meeting_started", meeting_id)
            return meeting

    def add_transcript(
        self, audio_path: str, language: Optional[str], segments: list[dict]
    ) -> Optional[dict]:
        with self._lock:
            meeting = self.get_meeting_by_audio_path(audio_path)
            meeting_path = None
            if meeting:
                meeting_path = self._find_meeting_path(meeting.get("id", ""))

            if not meeting or not meeting_path:
                meeting_id = str(uuid.uuid4())
                created_at = datetime.utcnow().isoformat()
                meeting = {
                    "schema_version": 1,
                    "id": meeting_id,
                    "title": "Meeting (transcribed)",
                    "title_source": "default",
                    "title_generated_at": None,
                    "created_at": created_at,
                    "audio_path": audio_path,
                    "recording_id": None,
                    "samplerate": None,
                    "channels": None,
                    "status": "completed",
                    "ended_at": datetime.utcnow().isoformat(),
                    "attendees": [],
                    "transcript": None,
                    "summary": None,
                    "action_items": [],
                    "summary_state": self._default_summary_state(),
                    "manual_notes": "",
                    "manual_summary": "",
                }
                meeting_path = self._meeting_path_for_new(created_at, meeting_id)

            attendees, normalized_segments = self._assign_attendees(
                meeting.get("attendees", []), segments
            )
            meeting["attendees"] = attendees
            meeting["transcript"] = {
                "language": language,
                "segments": normalized_segments,
                "updated_at": datetime.utcnow().isoformat(),
            }
            if not meeting.get("summary_state"):
                meeting["summary_state"] = self._default_summary_state()
            if "manual_notes" not in meeting:
                meeting["manual_notes"] = ""
            if "manual_summary" not in meeting:
                meeting["manual_summary"] = ""
            self._ensure_title_fields(meeting)
            if meeting.get("status") != "in_progress":
                meeting["status"] = "completed"
                meeting["ended_at"] = meeting.get("ended_at") or datetime.utcnow().isoformat()
            self._write_meeting_file(meeting_path, meeting)
            self._logger.info("Transcript saved: id=%s", meeting.get("id"))
            self.publish_event("meeting_updated", meeting.get("id"))
            return meeting

    def add_summary(
        self,
        meeting_id: str,
        summary: str,
        action_items: list[dict],
        provider: str,
    ) -> Optional[dict]:
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            normalized_items: list[dict] = []
            for item in action_items:
                if isinstance(item, str):
                    normalized_items.append({"description": item})
                    continue
                if isinstance(item, dict):
                    normalized_items.append(item)
            meeting["summary"] = {
                "text": summary,
                "provider": provider,
                "updated_at": datetime.utcnow().isoformat(),
            }
            meeting["action_items"] = normalized_items
            self._write_meeting_file(path, meeting)
            self._logger.info("Summary saved: id=%s", meeting_id)
            return meeting

    def maybe_auto_title(
        self,
        meeting_id: str,
        summary_text: str,
        summarization_service,
        provider_override: Optional[str] = None,
        force: bool = False,
    ) -> Optional[dict]:
        # #region agent log
        _dbg_ndjson(
            location="meeting_store.py:maybe_auto_title",
            message="maybe_auto_title_enter",
            data={"meeting_id": meeting_id, "force": force, "summary_len": len(summary_text) if summary_text else 0},
            run_id="bugs-debug",
            hypothesis_id="H1b",
        )
        # #endregion
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                # #region agent log
                _dbg_ndjson(
                    location="meeting_store.py:maybe_auto_title",
                    message="maybe_auto_title_path_not_found",
                    data={"meeting_id": meeting_id},
                    run_id="bugs-debug",
                    hypothesis_id="H1b",
                )
                # #endregion
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            self._ensure_title_fields(meeting)
            if meeting.get("title_source") == "manual":
                # #region agent log
                _dbg_ndjson(
                    location="meeting_store.py:maybe_auto_title",
                    message="maybe_auto_title_skip_manual",
                    data={"meeting_id": meeting_id, "current_title": meeting.get("title", "")[:50]},
                    run_id="bugs-debug",
                    hypothesis_id="H1b",
                )
                # #endregion
                return meeting
            # Only generate once (unless forced).
            if meeting.get("title_generated_at") and not force:
                # #region agent log
                _dbg_ndjson(
                    location="meeting_store.py:maybe_auto_title",
                    message="maybe_auto_title_skip_already_generated",
                    data={"meeting_id": meeting_id, "title_generated_at": meeting.get("title_generated_at")},
                    run_id="bugs-debug",
                    hypothesis_id="H1b",
                )
                # #endregion
                return meeting
            if not force:
                try:
                    if not summarization_service.is_meaningful_summary(
                        summary_text, provider_override=provider_override
                    ):
                        # #region agent log
                        _dbg_ndjson(
                            location="meeting_store.py:maybe_auto_title",
                            message="maybe_auto_title_skip_not_meaningful",
                            data={"meeting_id": meeting_id},
                            run_id="bugs-debug",
                            hypothesis_id="H1c",
                        )
                        # #endregion
                        return meeting
                except Exception as exc:
                    self._logger.warning("Meaningful summary check failed: %s", exc)
                    # #region agent log
                    _dbg_ndjson(
                        location="meeting_store.py:maybe_auto_title",
                        message="maybe_auto_title_meaningful_check_error",
                        data={"meeting_id": meeting_id, "exc_type": type(exc).__name__, "exc": str(exc)[:300]},
                        run_id="bugs-debug",
                        hypothesis_id="H1c",
                    )
                    # #endregion
                    return meeting
            # #region agent log
            _dbg_ndjson(
                location="meeting_store.py:maybe_auto_title",
                message="maybe_auto_title_calling_generate",
                data={"meeting_id": meeting_id, "summary_len": len(summary_text) if summary_text else 0},
                run_id="bugs-debug",
                hypothesis_id="H1b",
            )
            # #endregion
            try:
                title = summarization_service.generate_title(
                    summary_text, provider_override=provider_override
                )
            except Exception as exc:
                # #region agent log
                _dbg_ndjson(
                    location="meeting_store.py:maybe_auto_title",
                    message="maybe_auto_title_generate_error",
                    data={"meeting_id": meeting_id, "exc_type": type(exc).__name__, "exc": str(exc)[:500]},
                    run_id="bugs-debug",
                    hypothesis_id="H1b",
                )
                # #endregion
                self._logger.warning("generate_title failed: %s", exc)
                return meeting
            # #region agent log
            _dbg_ndjson(
                location="meeting_store.py:maybe_auto_title",
                message="maybe_auto_title_title_generated",
                data={"meeting_id": meeting_id, "new_title": title[:100] if title else None},
                run_id="bugs-debug",
                hypothesis_id="H1b",
            )
            # #endregion
            meeting["title"] = title
            meeting["title_source"] = "auto"
            meeting["title_generated_at"] = datetime.utcnow().isoformat()
            self._write_meeting_file(path, meeting)
            self._logger.info("Auto title saved: id=%s", meeting_id)
            self.publish_event("title_updated", meeting_id, {"title": title, "source": "auto"})
            return meeting

    def update_title(
        self, meeting_id: str, title: str, source: str = "manual"
    ) -> Optional[dict]:
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            meeting["title"] = title
            if source == "auto":
                meeting["title_source"] = "auto"
                meeting["title_generated_at"] = datetime.utcnow().isoformat()
            else:
                meeting["title_source"] = "manual"
                meeting["title_generated_at"] = None
            self._write_meeting_file(path, meeting)
            self.publish_event("title_updated", meeting_id, {"title": title, "source": source})
            return meeting

    def update_attendees(self, meeting_id: str, attendees: list[dict]) -> Optional[dict]:
        with self._lock:
            # #region agent log
            _dbg_ndjson(
                location="meeting_store.py:update_attendees",
                message="update_attendees called",
                data={
                    "meeting_id": meeting_id,
                    "attendees_count": len(attendees),
                    "attendee_ids": [a.get("id") for a in attendees[:5]],
                },
                run_id="attendee-debug",
                hypothesis_id="H3",
            )
            # #endregion
            path = self._find_meeting_path(meeting_id)
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            meeting["attendees"] = attendees
            self._write_meeting_file(path, meeting)
            # #region agent log
            _dbg_ndjson(
                location="meeting_store.py:update_attendees:event",
                message="publishing attendees_updated event",
                data={"meeting_id": meeting_id, "attendees_count": len(attendees)},
                run_id="attendee-debug",
                hypothesis_id="H3",
            )
            # #endregion
            self.publish_event("attendees_updated", meeting_id, {"attendees": attendees})
            return meeting

    def update_status(self, meeting_id: str, status: str) -> Optional[dict]:
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                # #region agent log
                _dbg_ndjson(
                    location="app/services/meeting_store.py:update_status",
                    message="update_status path not found",
                    data={"meeting_id": meeting_id, "new_status": status},
                    run_id="pre-fix",
                    hypothesis_id="STATUS1",
                )
                # #endregion
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                # #region agent log
                _dbg_ndjson(
                    location="app/services/meeting_store.py:update_status",
                    message="update_status meeting read empty",
                    data={"meeting_id": meeting_id, "new_status": status, "path": os.path.basename(path)},
                    run_id="pre-fix",
                    hypothesis_id="STATUS1",
                )
                # #endregion
                return None
            prev_status = meeting.get("status")
            prev_ended_at = meeting.get("ended_at")
            meeting["status"] = status
            if status == "in_progress":
                meeting["ended_at"] = None
            if status == "completed":
                meeting["ended_at"] = datetime.utcnow().isoformat()
            self._write_meeting_file(path, meeting)
            # #region agent log
            _dbg_ndjson(
                location="app/services/meeting_store.py:update_status",
                message="update_status wrote",
                data={
                    "meeting_id": meeting_id,
                    "path": os.path.basename(path),
                    "prev_status": prev_status,
                    "new_status": status,
                    "prev_ended_at": prev_ended_at,
                    "new_ended_at": meeting.get("ended_at"),
                },
                run_id="pre-fix",
                hypothesis_id="STATUS1",
            )
            # #endregion
            self.publish_event(
                "status_updated",
                meeting_id,
                {"status": status, "ended_at": meeting.get("ended_at")},
            )
            return meeting

    def update_transcript_speakers(
        self, meeting_id: str, segments: list[dict]
    ) -> Optional[dict]:
        """Update speaker labels in transcript segments after diarization.
        
        Also creates/updates attendees based on speaker labels found in segments.
        """
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            transcript = meeting.get("transcript", {})
            if isinstance(transcript, dict):
                existing_segments = transcript.get("segments", [])
                segment_map = {s["start"]: s.get("speaker") for s in segments}
                for seg in existing_segments:
                    if seg["start"] in segment_map:
                        seg["speaker"] = segment_map[seg["start"]]
                meeting["transcript"] = transcript
                
                # Create/update attendees from speaker labels
                existing_attendees = meeting.get("attendees", [])
                attendees, normalized_segments = self._assign_attendees(
                    existing_attendees, existing_segments
                )
                meeting["attendees"] = attendees
                meeting["transcript"]["segments"] = normalized_segments
                
                # #region agent log
                _dbg_ndjson(
                    location="meeting_store.py:update_transcript_speakers",
                    message="attendees_assigned",
                    data={
                        "meeting_id": meeting_id,
                        "existing_attendees_count": len(existing_attendees),
                        "new_attendees_count": len(attendees),
                        "attendee_ids": [a.get("id") for a in attendees[:5]],
                    },
                    run_id="post-fix",
                    hypothesis_id="H1",
                )
                # #endregion
                
                self._write_meeting_file(path, meeting)
                # Emit full transcript update after diarization
                self.publish_event("transcript_updated", meeting_id, {"segments": normalized_segments})
                # Also emit attendees update
                self.publish_event("attendees_updated", meeting_id, {"attendees": attendees})
            return meeting

    def reconcile_speakers(
        self, meeting_id: str, annotations: list
    ) -> int:
        """Reconcile stored transcript segments against new diarization annotations.
        
        For each annotation, finds stored segments whose start time falls within
        the annotation's time range. If the stored segment has a different speaker
        (especially "unknown"), updates it to the annotation's speaker.
        
        Args:
            meeting_id: The meeting ID
            annotations: List of dicts with {start, end, speaker} from diarization
            
        Returns:
            Number of segments that were updated
        """
        if not annotations:
            return 0
        
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                return 0
            meeting = self._read_meeting_file(path)
            if not meeting:
                return 0
            
            transcript = meeting.get("transcript", {})
            if not isinstance(transcript, dict):
                return 0
            segments = transcript.get("segments", [])
            if not segments:
                return 0
            
            updated_count = 0
            for ann in annotations:
                ann_start = ann.get("start")
                ann_end = ann.get("end")
                ann_speaker = ann.get("speaker")
                if ann_start is None or ann_end is None or not ann_speaker:
                    continue
                
                for seg in segments:
                    seg_start = seg.get("start")
                    if seg_start is None:
                        continue
                    # Check if segment's start falls within annotation range
                    if ann_start <= seg_start < ann_end:
                        current_speaker = seg.get("speaker")
                        if current_speaker != ann_speaker:
                            seg["speaker"] = ann_speaker
                            # Also update speaker_id if present
                            if "speaker_id" in seg:
                                seg["speaker_id"] = ann_speaker
                            updated_count += 1
            
            if updated_count == 0:
                return 0
            
            # Ensure attendees exist for any new speaker labels
            existing_attendees = meeting.get("attendees", [])
            existing_ids = {att.get("id") for att in existing_attendees}
            existing_labels = {att.get("label") for att in existing_attendees}
            
            for ann in annotations:
                speaker = ann.get("speaker")
                if speaker and speaker not in existing_ids and speaker not in existing_labels:
                    new_attendee = {
                        "id": speaker,
                        "label": speaker,
                        "name": speaker.replace("speaker", "Speaker ").replace("_", " ").title(),
                    }
                    existing_attendees.append(new_attendee)
            
            meeting["attendees"] = existing_attendees
            meeting["transcript"]["segments"] = segments
            self._write_meeting_file(path, meeting)
            
            # Publish events so frontend updates
            self.publish_event("transcript_updated", meeting_id, {"segments": segments})
            self.publish_event("attendees_updated", meeting_id, {"attendees": existing_attendees})
            
            _dbg_ndjson(
                location="meeting_store.py:reconcile_speakers",
                message="speakers_reconciled",
                data={
                    "meeting_id": meeting_id,
                    "annotations_checked": len(annotations),
                    "segments_updated": updated_count,
                    "total_attendees": len(existing_attendees),
                },
                run_id="reconcile",
                hypothesis_id="RECONCILE",
            )
            
            return updated_count

    def update_attendee_name(
        self,
        meeting_id: str,
        attendee_id: str,
        name: str,
        source: Optional[str] = None,
        confidence: Optional[str] = None,
    ) -> Optional[dict]:
        """Update or create an attendee with a name.
        
        Args:
            meeting_id: The meeting ID
            attendee_id: The attendee/speaker ID (e.g., "SPEAKER_00")
            name: The name to assign
            source: Optional source of the name ("manual", "llm", etc.)
            confidence: Optional confidence level ("high", "medium", "low")
        """
        # #region agent log
        _dbg_ndjson(
            location="meeting_store.py:update_attendee_name",
            message="update_attendee_name called",
            data={
                "meeting_id": meeting_id,
                "attendee_id": attendee_id,
                "name": name,
                "source": source,
            },
            run_id="attendee-debug",
            hypothesis_id="H3",
        )
        # #endregion
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            attendees = meeting.get("attendees", [])
            
            # Find existing attendee or create new one
            found = False
            for attendee in attendees:
                if attendee.get("id") == attendee_id:
                    attendee["name"] = name
                    if source:
                        attendee["name_source"] = source
                    if confidence:
                        attendee["name_confidence"] = confidence
                    found = True
                    break
            
            if not found:
                # Create new attendee entry
                new_attendee = {"id": attendee_id, "name": name}
                if source:
                    new_attendee["name_source"] = source
                if confidence:
                    new_attendee["name_confidence"] = confidence
                attendees.append(new_attendee)
                meeting["attendees"] = attendees
            
            self._write_meeting_file(path, meeting)
            self.publish_event("meeting_updated", meeting_id)
            return meeting

    def update_manual_buffers(
        self, meeting_id: str, manual_notes: str, manual_summary: str
    ) -> Optional[dict]:
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            meeting["manual_notes"] = manual_notes or ""
            meeting["manual_summary"] = manual_summary or ""
            self._write_meeting_file(path, meeting)
            self.publish_event("meeting_updated", meeting_id)
            return meeting

    def delete_meeting(self, meeting_id: str) -> bool:
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                # #region agent log
                _dbg_ndjson(
                    location="app/services/meeting_store.py:delete_meeting",
                    message="delete_meeting path missing",
                    data={"meeting_id": meeting_id},
                    run_id="pre-fix",
                    hypothesis_id="H1",
                )
                # #endregion
                return False
            try:
                os.unlink(path)
                # #region agent log
                _dbg_ndjson(
                    location="app/services/meeting_store.py:delete_meeting",
                    message="delete_meeting success",
                    data={"meeting_id": meeting_id, "path_name": os.path.basename(path)},
                    run_id="pre-fix",
                    hypothesis_id="H1",
                )
                # #endregion
                return True
            except OSError as exc:
                self._logger.warning("Failed to delete meeting file: %s error=%s", path, exc)
                # #region agent log
                _dbg_ndjson(
                    location="app/services/meeting_store.py:delete_meeting",
                    message="delete_meeting error",
                    data={
                        "meeting_id": meeting_id,
                        "path_name": os.path.basename(path),
                        "exc_type": type(exc).__name__,
                        "exc": str(exc)[:300],
                    },
                    run_id="pre-fix",
                    hypothesis_id="H1",
                )
                # #endregion
                return False

    def append_live_segment(
        self, meeting_id: str, segment: dict, language: Optional[str]
    ) -> Optional[dict]:
        with self._lock:
            # #region agent log
            _dbg_ndjson(
                location="meeting_store.py:append_live_segment:entry",
                message="append_live_segment called",
                data={
                    "meeting_id": meeting_id,
                    "segment_speaker": segment.get("speaker"),
                    "segment_speaker_id": segment.get("speaker_id"),
                    "segment_text_preview": (segment.get("text", "") or "")[:50],
                },
                run_id="attendee-debug",
                hypothesis_id="H1,H2",
            )
            # #endregion
            self._trace_log(
                "meeting_append_live_segment_enter",
                meeting_id=meeting_id,
                segment_start=segment.get("start"),
                segment_end=segment.get("end"),
                text_len=len(segment.get("text", "") or ""),
            )
            path = self._find_meeting_path(meeting_id)
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            transcript = meeting.get("transcript") or {
                "language": language,
                "segments": [],
            }
            if not transcript.get("language") and language:
                transcript["language"] = language
            transcript["segments"] = transcript.get("segments") or []
            transcript["segments"].append(segment)
            transcript["updated_at"] = datetime.utcnow().isoformat()
            meeting["transcript"] = transcript
            
            # Create/update attendee for every segment (real-time diarization)
            speaker_label = segment.get("speaker")
            # #region agent log
            _dbg_ndjson(
                location="meeting_store.py:append_live_segment:speaker_check",
                message="segment speaker label",
                data={
                    "meeting_id": meeting_id,
                    "speaker_label": speaker_label,
                    "has_speaker": bool(speaker_label),
                    "segment_start": segment.get("start"),
                    "text_preview": (segment.get("text") or "")[:40],
                },
                run_id="rt-attendee-debug",
                hypothesis_id="H_NOSPEAKER",
            )
            # #endregion
            if not speaker_label:
                # Segment has no speaker label — assign to an "Unknown" attendee
                speaker_label = "unknown"
                segment["speaker"] = speaker_label
            if speaker_label:
                existing_attendees = meeting.get("attendees", [])
                attendee_exists = any(
                    att.get("label") == speaker_label or att.get("id") == speaker_label
                    for att in existing_attendees
                )
                # #region agent log
                _dbg_ndjson(
                    location="meeting_store.py:append_live_segment:attendee_check",
                    message="attendee existence check",
                    data={
                        "meeting_id": meeting_id,
                        "speaker_label": speaker_label,
                        "attendee_exists": attendee_exists,
                        "existing_ids": [a.get("id") for a in existing_attendees],
                        "existing_labels": [a.get("label") for a in existing_attendees],
                        "segment_start": segment.get("start"),
                    },
                    run_id="rt-attendee-debug",
                    hypothesis_id="H_CREATION",
                )
                # #endregion
                if not attendee_exists:
                    # Create new attendee for this speaker
                    new_attendee = {
                        "id": speaker_label,
                        "label": speaker_label,
                        "name": speaker_label.replace("speaker", "Speaker ").replace("_", " ").title(),
                    }
                    existing_attendees.append(new_attendee)
                    meeting["attendees"] = existing_attendees
                    # #region agent log
                    _dbg_ndjson(
                        location="meeting_store.py:append_live_segment:attendee_created",
                        message="created attendee from real-time diarization",
                        data={
                            "meeting_id": meeting_id,
                            "speaker_label": speaker_label,
                            "attendee_id": new_attendee["id"],
                            "total_attendees": len(existing_attendees),
                        },
                        run_id="rt-attendee-fix",
                        hypothesis_id="H1",
                    )
                    # #endregion
                    # Emit attendees_updated event for real-time UI update
                    self.publish_event("attendees_updated", meeting_id, {"attendees": existing_attendees})
            
            summary_state = meeting.get("summary_state") or self._default_summary_state()
            segment_text = segment.get("text", "").strip()
            if segment_text:
                # SPEC WORKFLOW STEP 1 logs
                self._trace_log(
                    "spec_step_1_append_segment_to_streaming_start",
                    meeting_id=meeting_id,
                    incoming_text_len=len(segment_text),
                    streaming_len_before=len(summary_state.get("streaming_text", "") or ""),
                )
                streaming_text = summary_state.get("streaming_text", "")
                summary_state["streaming_text"] = (
                    f"{streaming_text} {segment_text}".strip()
                    if streaming_text
                    else segment_text
                )
                summary_state["last_processed_segment_index"] = len(transcript["segments"])
                summary_state["updated_at"] = datetime.utcnow().isoformat()
                meeting["summary_state"] = summary_state
                self._trace_log(
                    "spec_step_1_append_segment_to_streaming_end",
                    meeting_id=meeting_id,
                    streaming_len_after=len(summary_state.get("streaming_text", "") or ""),
                    last_processed_segment_index=summary_state.get("last_processed_segment_index"),
                )
            self._write_meeting_file(path, meeting)
            self._trace_log(
                "meeting_append_live_segment_exit",
                meeting_id=meeting_id,
                streaming_len=len((meeting.get("summary_state") or {}).get("streaming_text", "") or ""),
                draft_len=len((meeting.get("summary_state") or {}).get("draft_text", "") or ""),
                done_len=len((meeting.get("summary_state") or {}).get("done_text", "") or ""),
                summarized_len=len((meeting.get("summary_state") or {}).get("summarized_summary", "") or ""),
                interim_len=len((meeting.get("summary_state") or {}).get("interim_summary", "") or ""),
            )
            # Emit event for new transcript segment
            self.publish_event("transcript_segment", meeting_id, {"segment": segment})
            return meeting

    def append_live_meta(self, meeting_id: str, language: Optional[str]) -> Optional[dict]:
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                return None
            meeting = self._read_meeting_file(path)
            if not meeting:
                return None
            transcript = meeting.get("transcript") or {
                "language": language,
                "segments": [],
            }
            if not transcript.get("language") and language:
                transcript["language"] = language
            transcript["updated_at"] = datetime.utcnow().isoformat()
            meeting["transcript"] = transcript
            self._write_meeting_file(path, meeting)
            return meeting

    def step_summary_state(self, meeting_id: str, summarization_service) -> dict:
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                raise ValueError("Meeting not found")
            meeting = self._read_meeting_file(path)
            if not meeting:
                raise ValueError("Meeting not found")
            summary_state = meeting.get("summary_state") or self._default_summary_state()
            t0 = time.perf_counter()
            self._trace_log(
                "summary_tick_start",
                meeting_id=meeting_id,
                streaming_len=len(summary_state.get("streaming_text", "") or ""),
                draft_len=len(summary_state.get("draft_text", "") or ""),
                done_len=len(summary_state.get("done_text", "") or ""),
                summarized_len=len(summary_state.get("summarized_summary", "") or ""),
                interim_len=len(summary_state.get("interim_summary", "") or ""),
            )
            streaming_text = summary_state.get("streaming_text", "")
            # IMPORTANT (matches spec intent, fixes practical behavior):
            # Whisper/live transcripts often contain little/no punctuation, which makes
            # "extract full sentences" on raw text a no-op forever. Instead:
            # 1) Run cleanup on streaming_text to normalize punctuation
            # 2) Extract complete sentences from the cleaned output
            # 3) Move only whole sentences into draft_text, keep remainder in streaming_text
            if streaming_text.strip():
                try:
                    t_clean = time.perf_counter()
                    # SPEC WORKFLOW STEP 3:
                    # Send extracted text to LLM for cleanup (transcription error correction).
                    # (Implementation detail: we clean the streaming buffer first to add punctuation.)
                    self._trace_log(
                        "spec_step_3_llm_cleanup_start",
                        meeting_id=meeting_id,
                        input_len=len(streaming_text),
                    )
                    cleaned_streaming = summarization_service.cleanup_transcript(streaming_text)
                    self._trace_log(
                        "spec_step_3_llm_cleanup_end",
                        meeting_id=meeting_id,
                        elapsed_s=round(time.perf_counter() - t_clean, 3),
                        output_len=len(cleaned_streaming or ""),
                    )
                except Exception as exc:
                    # Spec: If cleanup fails, skip update and keep streams unchanged.
                    self._logger.warning("Summary cleanup failed: %s", exc)
                    self._trace_log("spec_step_3_llm_cleanup_error", meeting_id=meeting_id, error=str(exc))
                    return summary_state

                # SPEC WORKFLOW STEP 2:
                # Extract full sentences from the top of `streaming_text`; keep remainder in streaming.
                completed_text, remainder = self._extract_complete_sentences(cleaned_streaming or "")
                self._trace_log(
                    "spec_step_2_extract_full_sentences",
                    meeting_id=meeting_id,
                    completed_len=len(completed_text or ""),
                    remainder_len=len(remainder or ""),
                )

                if completed_text.strip():
                    # SPEC WORKFLOW STEP 4:
                    # Append cleaned text to `draft_text`.
                    self._trace_log(
                        "spec_step_4_append_to_draft_start",
                        meeting_id=meeting_id,
                        append_len=len(completed_text),
                        draft_len_before=len(summary_state.get("draft_text", "") or ""),
                    )
                    draft_text = summary_state.get("draft_text", "")
                    summary_state["draft_text"] = (
                        f"{draft_text}\n{completed_text}".strip()
                        if draft_text
                        else completed_text.strip()
                    )
                    self._trace_log(
                        "spec_step_4_append_to_draft_end",
                        meeting_id=meeting_id,
                        draft_len_after=len(summary_state.get("draft_text", "") or ""),
                    )
                else:
                    self._trace_log(
                        "spec_step_4_append_to_draft_skipped",
                        meeting_id=meeting_id,
                        reason="no_complete_sentences",
                    )

                # Keep remainder in streaming. Note this is now "cleaned remainder";
                # new raw segments will append to it; that's acceptable for a working stream.
                summary_state["streaming_text"] = (remainder or "").lstrip()
            else:
                self._trace_log(
                    "spec_step_2_extract_full_sentences_skipped",
                    meeting_id=meeting_id,
                    reason="streaming_text_empty",
                )

            summary_state["updated_at"] = datetime.utcnow().isoformat()

            draft_text = summary_state.get("draft_text", "").strip()
            if draft_text:
                try:
                    t_seg = time.perf_counter()
                    # SPEC WORKFLOW STEP 5:
                    # Send `draft_text` to LLM to detect topic boundaries and summarize each topic.
                    self._trace_log(
                        "spec_step_5_llm_segment_topics_start",
                        meeting_id=meeting_id,
                        input_len=len(draft_text),
                    )
                    topics = summarization_service.segment_topics(draft_text)
                    self._trace_log(
                        "spec_step_5_llm_segment_topics_end",
                        meeting_id=meeting_id,
                        elapsed_s=round(time.perf_counter() - t_seg, 3),
                        topics=len(topics) if topics else 0,
                    )
                except Exception as exc:
                    self._logger.warning("Topic segmentation failed: %s", exc)
                    self._trace_log("spec_step_5_llm_segment_topics_error", meeting_id=meeting_id, error=str(exc))
                    meeting["summary_state"] = summary_state
                    self._write_meeting_file(path, meeting)
                    self.publish_event("meeting_updated", meeting_id)
                    return summary_state

                if topics:
                    # SPEC WORKFLOW STEP 6:
                    # For each topic except the last (in-progress topic), move transcript+summary to done/summarized.
                    self._trace_log(
                        "spec_step_6_finalize_topics_start",
                        meeting_id=meeting_id,
                        topics_total=len(topics),
                    )
                    for topic in topics[:-1]:
                        summary_text = str(topic.get("summary", "")).strip()
                        transcript_text = str(topic.get("transcript", "")).strip()
                        if summary_text:
                            summarized = summary_state.get("summarized_summary", "")
                            summary_state["summarized_summary"] = (
                                f"{summarized}\n\n{summary_text}".strip()
                                if summarized
                                else summary_text
                            )
                        if transcript_text:
                            done_text = summary_state.get("done_text", "")
                            summary_state["done_text"] = (
                                f"{done_text}\n{transcript_text}".strip()
                                if done_text
                                else transcript_text
                            )
                    last_topic = topics[-1]
                    interim_summary = str(last_topic.get("summary", "")).strip()
                    interim_transcript = str(last_topic.get("transcript", "")).strip()
                    if interim_summary:
                        summary_state["interim_summary"] = interim_summary
                    if interim_transcript:
                        summary_state["draft_text"] = interim_transcript
                    self._trace_log(
                        "spec_step_6_finalize_topics_end",
                        meeting_id=meeting_id,
                        done_len=len(summary_state.get("done_text", "") or ""),
                        summarized_len=len(summary_state.get("summarized_summary", "") or ""),
                    )

                    # SPEC WORKFLOW STEP 7:
                    # Keep last topic in draft_text and its summary in interim_summary.
                    self._trace_log(
                        "spec_step_7_keep_last_topic_in_progress",
                        meeting_id=meeting_id,
                        draft_len=len(summary_state.get("draft_text", "") or ""),
                        interim_len=len(summary_state.get("interim_summary", "") or ""),
                    )
                else:
                    self._trace_log(
                        "spec_step_6_finalize_topics_skipped",
                        meeting_id=meeting_id,
                        reason="topics_empty",
                    )
            else:
                self._trace_log(
                    "spec_step_5_llm_segment_topics_skipped",
                    meeting_id=meeting_id,
                    reason="draft_text_empty",
                )

            meeting["summary_state"] = summary_state
            self._write_meeting_file(path, meeting)
            self.publish_event("meeting_updated", meeting_id)
            self._trace_log(
                "summary_tick_end",
                meeting_id=meeting_id,
                elapsed_s=round(time.perf_counter() - t0, 3),
                streaming_len=len(summary_state.get("streaming_text", "") or ""),
                draft_len=len(summary_state.get("draft_text", "") or ""),
                done_len=len(summary_state.get("done_text", "") or ""),
                summarized_len=len(summary_state.get("summarized_summary", "") or ""),
                interim_len=len(summary_state.get("interim_summary", "") or ""),
            )
            return summary_state

    def _extract_complete_sentences(self, text: str) -> tuple[str, str]:
        if not text:
            return "", ""
        matches = list(re.finditer(r"[.!?](\s|$)", text))
        if not matches:
            return "", text
        last_match = matches[-1]
        end_index = last_match.end()
        return text[:end_index].strip(), text[end_index:].strip()

    def export_markdown(self, meeting_id: str) -> Optional[str]:
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            return None
        title = meeting.get("title") or "Meeting"
        created_at = meeting.get("created_at") or ""
        summary_text = meeting.get("summary", {}).get("text") if meeting.get("summary") else ""
        action_items = meeting.get("action_items") or []
        attendees = meeting.get("attendees") or []
        attendee_lookup = {attendee.get("id"): attendee for attendee in attendees}
        transcript_segments = (
            meeting.get("transcript", {}).get("segments")
            if isinstance(meeting.get("transcript"), dict)
            else []
        )

        lines = [
            f"# {title}",
            "",
            f"**Date:** {created_at}",
            "",
        ]
        if summary_text:
            lines.extend(["## Summary", "", summary_text, ""])
        if action_items:
            lines.append("## Action Items")
            for item in action_items:
                description = item.get("description") or ""
                assignee = item.get("assignee") or ""
                due_date = item.get("due_date") or ""
                suffix = ""
                if assignee or due_date:
                    suffix = f" ({assignee} {due_date})".strip()
                lines.append(f"- {description}{suffix}")
            lines.append("")
        if attendees:
            lines.append("## Attendees")
            for attendee in attendees:
                name = attendee.get("name") or attendee.get("label") or attendee.get("id")
                if name:
                    lines.append(f"- {name}")
            lines.append("")
        if transcript_segments:
            lines.append("## Transcript")
            for segment in transcript_segments:
                start = segment.get("start")
                end = segment.get("end")
                speaker_id = segment.get("speaker_id") or segment.get("speaker")
                speaker = attendee_lookup.get(speaker_id, {}).get("name") if speaker_id else None
                text = segment.get("text", "")
                speaker_prefix = f"[{speaker}] " if speaker else ""
                lines.append(f"[{start}-{end}] {speaker_prefix}{text}")
        return "\n".join(lines)

    def _assign_attendees(
        self, existing_attendees: list[dict], segments: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        attendees = list(existing_attendees or [])
        label_lookup = {attendee.get("label"): attendee for attendee in attendees if attendee.get("label")}
        id_lookup = {attendee.get("id"): attendee for attendee in attendees if attendee.get("id")}

        speaker_labels = sorted(
            {segment.get("speaker") for segment in segments if segment.get("speaker")}
        )
        needs_unknown = any(segment.get("speaker") is None for segment in segments)

        next_index = self._next_person_index(attendees)

        def ensure_attendee(label: Optional[str]) -> dict:
            nonlocal next_index
            if label and label in label_lookup:
                return label_lookup[label]
            if label and label in id_lookup:
                return id_lookup[label]

            attendee_id = label or f"unknown-{next_index}"
            name = f"Person {next_index}"
            attendee = {
                "id": attendee_id,
                "label": label,
                "name": name,
            }
            attendees.append(attendee)
            if label:
                label_lookup[label] = attendee
            id_lookup[attendee_id] = attendee
            next_index += 1
            return attendee

        if not speaker_labels and needs_unknown:
            default_attendee = ensure_attendee(None)
            normalized_segments = []
            for segment in segments:
                normalized = dict(segment)
                normalized["speaker_id"] = default_attendee.get("id")
                normalized_segments.append(normalized)
            return attendees, normalized_segments

        if needs_unknown:
            ensure_attendee(None)

        for label in speaker_labels:
            ensure_attendee(label)

        normalized_segments = []
        for segment in segments:
            speaker = segment.get("speaker")
            normalized = dict(segment)
            if speaker:
                normalized["speaker_id"] = speaker
            else:
                unknown_attendee = next(
                    (att for att in attendees if not att.get("label")), None
                )
                normalized["speaker_id"] = unknown_attendee.get("id") if unknown_attendee else None
            normalized_segments.append(normalized)
        return attendees, normalized_segments

    def _next_person_index(self, attendees: list[dict]) -> int:
        used = set()
        for attendee in attendees:
            name = attendee.get("name") or ""
            match = re.match(r"^Person (\d+)$", name)
            if match:
                used.add(int(match.group(1)))
        index = 1
        while index in used:
            index += 1
        return index

    def _default_summary_state(self) -> dict:
        return {
            "streaming_text": "",
            "draft_text": "",
            "done_text": "",
            "interim_summary": "",
            "summarized_summary": "",
            "last_processed_segment_index": 0,
            "updated_at": datetime.utcnow().isoformat(),
        }

    def _ensure_title_fields(self, meeting: dict) -> bool:
        updated = False
        if "title_source" not in meeting:
            meeting["title_source"] = "default"
            updated = True
        if "title_generated_at" not in meeting:
            meeting["title_generated_at"] = None
            updated = True
        return updated

    # ---- Chat history persistence ----

    def get_chat_history(self, meeting_id: str) -> list:
        """Read chat_history from a meeting's JSON (default [])."""
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            return []
        return meeting.get("chat_history", [])

    def save_chat_history(self, meeting_id: str, messages: list) -> bool:
        """Write chat_history into a meeting's JSON. Returns True on success."""
        with self._lock:
            path = self._find_meeting_path(meeting_id)
            if not path:
                return False
            meeting = self._read_meeting_file(path)
            if not meeting:
                return False
            meeting["chat_history"] = messages
            self._write_meeting_file(path, meeting)
            return True
