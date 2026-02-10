import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Optional


class MeetingStore:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._events_lock = threading.RLock()
        self._events: list[dict] = []
        self._logger = logging.getLogger("notetaker.meetings")
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        if not os.path.exists(self._path):
            self._write({"meetings": []})

    def list_meetings(self) -> list[dict]:
        with self._lock:
            data = self._read()
            meetings = data.get("meetings", [])
            updated = False
            for meeting in meetings:
                if not meeting.get("summary_state"):
                    meeting["summary_state"] = self._default_summary_state()
                    updated = True
                updated = self._ensure_title_fields(meeting) or updated
            if updated:
                self._write({"meetings": meetings})
            return sorted(
                meetings,
                key=lambda meeting: meeting.get("created_at") or "",
                reverse=True,
            )

    def get_storage_path(self) -> str:
        return self._path

    def publish_event(self, event_type: str, meeting_id: Optional[str]) -> None:
        with self._events_lock:
            payload = {
                "type": event_type,
                "meeting_id": meeting_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
            self._events.append(payload)
            if len(self._events) > 200:
                self._events = self._events[-100:]

    def get_events_since(self, cursor: int) -> tuple[list[dict], int]:
        with self._events_lock:
            events = self._events[cursor:]
            return events, len(self._events)

    def get_meeting(self, meeting_id: str) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") == meeting_id:
                    if not meeting.get("summary_state"):
                        meeting["summary_state"] = self._default_summary_state()
                        self._write(data)
                    if self._ensure_title_fields(meeting):
                        self._write(data)
                    return meeting
            return None

    def get_meeting_by_audio_path(self, audio_path: str) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("audio_path") == audio_path:
                    if not meeting.get("summary_state"):
                        meeting["summary_state"] = self._default_summary_state()
                        self._write(data)
                    if self._ensure_title_fields(meeting):
                        self._write(data)
                    return meeting
            return None

    def create_from_recording(self, recording: dict, status: str = "in_progress") -> dict:
        with self._lock:
            meeting_id = recording.get("recording_id") or str(uuid.uuid4())
            meetings = self._read().get("meetings", [])
            existing = next(
                (meeting for meeting in meetings if meeting.get("id") == meeting_id),
                None,
            )
            if existing:
                existing["audio_path"] = recording.get("file_path")
                existing["recording_id"] = recording.get("recording_id")
                existing["samplerate"] = recording.get("samplerate")
                existing["channels"] = recording.get("channels")
                existing["status"] = status
                if not existing.get("summary_state"):
                    existing["summary_state"] = self._default_summary_state()
                if status == "completed":
                    existing["ended_at"] = datetime.utcnow().isoformat()
                if status == "in_progress":
                    existing["ended_at"] = None
                self._write({"meetings": meetings})
                self.publish_event(
                    "meeting_completed" if status == "completed" else "meeting_started",
                    existing.get("id"),
                )
                return existing

            created_at = recording.get("started_at") or datetime.utcnow().isoformat()
            meeting = {
                "id": meeting_id,
                "title": f"Meeting {created_at}",
                "title_source": "default",
                "title_generated_at": None,
                "created_at": created_at,
                "audio_path": recording.get("file_path"),
                "recording_id": recording.get("recording_id"),
                "samplerate": recording.get("samplerate"),
                "channels": recording.get("channels"),
                "status": status,
                "ended_at": None,
                "attendees": [],
                "transcript": None,
                "summary": None,
                "action_items": [],
                "summary_state": self._default_summary_state(),
            }
            if status == "completed":
                meeting["ended_at"] = datetime.utcnow().isoformat()
            meetings.append(meeting)
            self._write({"meetings": meetings})
            self._logger.info("Meeting created: id=%s", meeting_id)
            self.publish_event(
                "meeting_completed" if status == "completed" else "meeting_started",
                meeting_id,
            )
            return meeting

    def create_simulated_meeting(self, audio_path: str) -> dict:
        with self._lock:
            meeting_id = str(uuid.uuid4())
            created_at = datetime.utcnow().isoformat()
            meeting = {
                "id": meeting_id,
                "title": f"Meeting {created_at}",
                "title_source": "default",
                "title_generated_at": None,
                "created_at": created_at,
                "audio_path": audio_path,
                "recording_id": None,
                "samplerate": None,
                "channels": None,
                "status": "in_progress",
                "ended_at": None,
                "attendees": [],
                "transcript": None,
                "summary": None,
                "action_items": [],
                "summary_state": self._default_summary_state(),
                "simulated": True,
            }
            data = self._read()
            meetings = data.get("meetings", [])
            meetings.append(meeting)
            self._write({"meetings": meetings})
            self._logger.info("Simulated meeting created: id=%s", meeting_id)
            self.publish_event("meeting_started", meeting_id)
            return meeting

    def add_transcript(
        self, audio_path: str, language: Optional[str], segments: list[dict]
    ) -> Optional[dict]:
        with self._lock:
            data = self._read()
            meetings = data.get("meetings", [])
            meeting = next(
                (item for item in meetings if item.get("audio_path") == audio_path),
                None,
            )
            if not meeting:
                meeting = {
                    "id": str(uuid.uuid4()),
                    "title": "Meeting (transcribed)",
                "title_source": "default",
                "title_generated_at": None,
                    "created_at": datetime.utcnow().isoformat(),
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
                }
                meetings.append(meeting)

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
            self._ensure_title_fields(meeting)
            if meeting.get("status") != "in_progress":
                meeting["status"] = "completed"
                meeting["ended_at"] = meeting.get("ended_at") or datetime.utcnow().isoformat()
            self._write({"meetings": meetings})
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
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") == meeting_id:
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
                    self._write(data)
                    self._logger.info("Summary saved: id=%s", meeting_id)
                    return meeting
            return None

    def maybe_auto_title(
        self,
        meeting_id: str,
        summary_text: str,
        summarization_service,
        provider_override: Optional[str] = None,
        force: bool = False,
    ) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") != meeting_id:
                    continue
                self._ensure_title_fields(meeting)
                if meeting.get("title_source") == "manual":
                    return meeting
                if meeting.get("title_generated_at") and not force:
                    return meeting
                if not force:
                    try:
                        if not summarization_service.is_meaningful_summary(
                            summary_text, provider_override=provider_override
                        ):
                            return meeting
                    except Exception as exc:
                        self._logger.warning("Meaningful summary check failed: %s", exc)
                        return meeting
                title = summarization_service.generate_title(
                    summary_text, provider_override=provider_override
                )
                meeting["title"] = title
                meeting["title_source"] = "auto"
                meeting["title_generated_at"] = datetime.utcnow().isoformat()
                self._write(data)
                self._logger.info("Auto title saved: id=%s", meeting_id)
                self.publish_event("meeting_updated", meeting_id)
                return meeting
            return None

    def update_title(
        self, meeting_id: str, title: str, source: str = "manual"
    ) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") == meeting_id:
                    meeting["title"] = title
                    if source == "auto":
                        meeting["title_source"] = "auto"
                        meeting["title_generated_at"] = datetime.utcnow().isoformat()
                    else:
                        meeting["title_source"] = "manual"
                        meeting["title_generated_at"] = None
                    self._write(data)
                    return meeting
            return None

    def update_attendees(self, meeting_id: str, attendees: list[dict]) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") == meeting_id:
                    meeting["attendees"] = attendees
                    self._write(data)
                    return meeting
            return None

    def update_status(self, meeting_id: str, status: str) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") == meeting_id:
                    meeting["status"] = status
                    if status == "in_progress":
                        meeting["ended_at"] = None
                    if status == "completed":
                        meeting["ended_at"] = datetime.utcnow().isoformat()
                    self._write(data)
                    self.publish_event(
                        "meeting_completed"
                        if status == "completed"
                        else "meeting_started"
                        if status == "in_progress"
                        else "meeting_updated",
                        meeting_id,
                    )
                    return meeting
            return None

    def update_transcript_speakers(
        self, meeting_id: str, segments: list[dict]
    ) -> Optional[dict]:
        """Update speaker labels in transcript segments after diarization."""
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") == meeting_id:
                    transcript = meeting.get("transcript", {})
                    if isinstance(transcript, dict):
                        existing_segments = transcript.get("segments", [])
                        # Match by start time and update speaker
                        segment_map = {s["start"]: s.get("speaker") for s in segments}
                        for seg in existing_segments:
                            if seg["start"] in segment_map:
                                seg["speaker"] = segment_map[seg["start"]]
                        self._write(data)
                        self.publish_event("meeting_updated", meeting_id)
                    return meeting
            return None

    def update_attendee_name(
        self, meeting_id: str, attendee_id: str, name: str
    ) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") == meeting_id:
                    attendees = meeting.get("attendees", [])
                    for attendee in attendees:
                        if attendee.get("id") == attendee_id:
                            attendee["name"] = name
                            self._write(data)
                            return meeting
                    return None
            return None

    def delete_meeting(self, meeting_id: str) -> bool:
        with self._lock:
            data = self._read()
            meetings = data.get("meetings", [])
            filtered = [meeting for meeting in meetings if meeting.get("id") != meeting_id]
            if len(filtered) == len(meetings):
                return False
            self._write({"meetings": filtered})
            return True

    def append_live_segment(
        self, meeting_id: str, segment: dict, language: Optional[str]
    ) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") == meeting_id:
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
                    summary_state = meeting.get("summary_state") or self._default_summary_state()
                    segment_text = segment.get("text", "").strip()
                    if segment_text:
                        streaming_text = summary_state.get("streaming_text", "")
                        summary_state["streaming_text"] = (
                            f"{streaming_text} {segment_text}".strip()
                            if streaming_text
                            else segment_text
                        )
                        summary_state["last_processed_segment_index"] = len(
                            transcript["segments"]
                        )
                        summary_state["updated_at"] = datetime.utcnow().isoformat()
                        meeting["summary_state"] = summary_state
                    self._write(data)
                    return meeting
            return None

    def append_live_meta(self, meeting_id: str, language: Optional[str]) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") == meeting_id:
                    transcript = meeting.get("transcript") or {
                        "language": language,
                        "segments": [],
                    }
                    if not transcript.get("language") and language:
                        transcript["language"] = language
                    transcript["updated_at"] = datetime.utcnow().isoformat()
                    meeting["transcript"] = transcript
                    self._write(data)
                    return meeting
            return None

    def step_summary_state(self, meeting_id: str, summarization_service) -> dict:
        with self._lock:
            data = self._read()
            for meeting in data.get("meetings", []):
                if meeting.get("id") == meeting_id:
                    summary_state = meeting.get("summary_state") or self._default_summary_state()
                    self._logger.info("Summary tick start: id=%s", meeting_id)
                    streaming_text = summary_state.get("streaming_text", "")
                    completed_text, remainder = self._extract_complete_sentences(
                        streaming_text
                    )
                    if completed_text.strip():
                        try:
                            cleaned = summarization_service.cleanup_transcript(
                                completed_text
                            )
                        except Exception as exc:
                            self._logger.warning("Summary cleanup failed: %s", exc)
                            return summary_state
                        if cleaned.strip():
                            draft_text = summary_state.get("draft_text", "")
                            summary_state["draft_text"] = (
                                f"{draft_text}\n{cleaned}".strip()
                                if draft_text
                                else cleaned.strip()
                            )
                        summary_state["streaming_text"] = remainder.lstrip()
                    summary_state["updated_at"] = datetime.utcnow().isoformat()

                    draft_text = summary_state.get("draft_text", "").strip()
                    if draft_text:
                        try:
                            topics = summarization_service.segment_topics(draft_text)
                        except Exception as exc:
                            self._logger.warning("Topic segmentation failed: %s", exc)
                            meeting["summary_state"] = summary_state
                            self._write(data)
                            self.publish_event("meeting_updated", meeting_id)
                            return summary_state

                        if topics:
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
                            interim_transcript = str(
                                last_topic.get("transcript", "")
                            ).strip()
                            if interim_summary:
                                summary_state["interim_summary"] = interim_summary
                            if interim_transcript:
                                summary_state["draft_text"] = interim_transcript

                    meeting["summary_state"] = summary_state
                    self._write(data)
                    self.publish_event("meeting_updated", meeting_id)
                    self._logger.info("Summary tick complete: id=%s", meeting_id)
                    return summary_state
            raise ValueError("Meeting not found")

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

    def _read(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            self._logger.exception("Failed to read meetings file: %s", exc)
            return {"meetings": []}

    def _write(self, data: dict) -> None:
        temp_path = f"{self._path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
        os.replace(temp_path, self._path)

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
