"""Utilities for transcript processing and display."""

from typing import Optional


def consolidate_segments(
    segments: list[dict],
    max_duration: float = 15.0,
    max_gap: float = 2.0,
) -> list[dict]:
    """
    Merge consecutive transcript segments from the same speaker into larger chunks.

    Rules:
    - Only merge segments from the same speaker (speaker_id or speaker field)
    - Only merge if gap between segments is less than max_gap seconds
    - Stop merging when total duration would exceed max_duration seconds
    - Preserve original start time, update end time, concatenate text with space

    Args:
        segments: List of segment dicts with start, end, text, speaker/speaker_id
        max_duration: Maximum duration in seconds for a consolidated chunk (default 15)
        max_gap: Maximum gap in seconds between segments to allow merging (default 2)

    Returns:
        List of consolidated segment dicts
    """
    if not segments:
        return []

    consolidated = []
    current_chunk: Optional[dict] = None

    for segment in segments:
        speaker = segment.get("speaker_id") or segment.get("speaker")
        start = segment.get("start", 0)
        end = segment.get("end", 0)
        text = segment.get("text", "")

        if current_chunk is None:
            # Start a new chunk
            current_chunk = {
                "type": segment.get("type", "segment"),
                "start": start,
                "end": end,
                "text": text,
                "speaker": segment.get("speaker"),
                "speaker_id": segment.get("speaker_id"),
            }
            continue

        current_speaker = current_chunk.get("speaker_id") or current_chunk.get("speaker")
        current_end = current_chunk.get("end", 0)
        current_start = current_chunk.get("start", 0)

        # Calculate gap between current chunk end and new segment start
        gap = start - current_end

        # Calculate what the new duration would be if we merged
        new_duration = end - current_start

        # Check if we can merge this segment
        can_merge = (
            speaker == current_speaker  # Same speaker
            and gap <= max_gap  # Gap is small enough
            and new_duration <= max_duration  # Won't exceed max duration
        )

        if can_merge:
            # Merge into current chunk
            current_chunk["end"] = end
            current_chunk["text"] = current_chunk["text"] + " " + text
        else:
            # Save current chunk and start a new one
            consolidated.append(current_chunk)
            current_chunk = {
                "type": segment.get("type", "segment"),
                "start": start,
                "end": end,
                "text": text,
                "speaker": segment.get("speaker"),
                "speaker_id": segment.get("speaker_id"),
            }

    # Don't forget the last chunk
    if current_chunk is not None:
        consolidated.append(current_chunk)

    return consolidated
