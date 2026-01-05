"""
Speaker labeler state management.
"""
import os
import threading
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pydub import AudioSegment


@dataclass
class Utterance:
    """Represents a speaker utterance."""
    speaker_id: str
    timestamp_str: str
    start_ms: int
    end_ms: int = 0
    match_start: int = 0
    match_end: int = 0
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Utterance':
        """Create Utterance from dictionary."""
        return cls(
            speaker_id=data['speaker_id'],
            timestamp_str=data['timestamp_str'],
            start_ms=data['start_ms'],
            end_ms=data.get('end_ms', 0),
            match_start=data.get('match_start', 0),
            match_end=data.get('match_end', 0)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert utterance to dictionary."""
        return {
            'speaker_id': self.speaker_id,
            'timestamp_str': self.timestamp_str,
            'start_ms': self.start_ms,
            'end_ms': self.end_ms,
            'match_start': self.match_start,
            'match_end': self.match_end
        }


class SpeakerLabelerState:
    """Manages the state of the speaker labeler."""
    
    def __init__(self):
        self._audio_file: Optional[AudioSegment] = None
        self._audio_duration_ms = 0
        self._transcript_content = ""
        self._utterances: List[Utterance] = []
        self._speaker_occurrences: Dict[str, List[Utterance]] = {}
        self._speaker_segments: Dict[str, List[Utterance]] = {}
        self._speaker_ids: List[str] = []
        self._speaker_mapping: Dict[str, str] = {}
        self._current_index = 0
        self._output_transcript_path = ""
        self._active = False
        self._temp_files: List[str] = []  # Track temp audio files for cleanup
        self._lock = threading.Lock()
    
    @property
    def audio_file(self) -> Optional[AudioSegment]:
        """Get audio file."""
        with self._lock:
            return self._audio_file
    
    @audio_file.setter
    def audio_file(self, value: Optional[AudioSegment]) -> None:
        """Set audio file."""
        with self._lock:
            self._audio_file = value
            if value:
                self._audio_duration_ms = len(value)
            else:
                self._audio_duration_ms = 0
    
    @property
    def audio_duration_ms(self) -> int:
        """Get audio duration in milliseconds."""
        with self._lock:
            return self._audio_duration_ms
    
    @property
    def transcript_content(self) -> str:
        """Get transcript content."""
        with self._lock:
            return self._transcript_content
    
    @transcript_content.setter
    def transcript_content(self, value: str) -> None:
        """Set transcript content."""
        with self._lock:
            self._transcript_content = value
    
    @property
    def utterances(self) -> List[Utterance]:
        """Get utterances list.

        Returns a copy for thread safety. Cache the result if accessing multiple times.
        """
        with self._lock:
            return self._utterances.copy()
    
    @utterances.setter
    def utterances(self, value: List[Utterance]) -> None:
        """Set utterances list."""
        with self._lock:
            self._utterances = value.copy() if value else []
    
    @property
    def speaker_occurrences(self) -> Dict[str, List[Utterance]]:
        """Get speaker occurrences.

        Returns a deep copy for thread safety. Cache the result if accessing multiple times.
        """
        with self._lock:
            return {k: v.copy() for k, v in self._speaker_occurrences.items()}
    
    @speaker_occurrences.setter
    def speaker_occurrences(self, value: Dict[str, List[Utterance]]) -> None:
        """Set speaker occurrences."""
        with self._lock:
            self._speaker_occurrences = {k: v.copy() for k, v in value.items()} if value else {}
    
    @property
    def speaker_segments(self) -> Dict[str, List[Utterance]]:
        """Get speaker segments.

        Returns a deep copy for thread safety. Cache the result if accessing multiple times.
        """
        with self._lock:
            return {k: v.copy() for k, v in self._speaker_segments.items()}
    
    @speaker_segments.setter
    def speaker_segments(self, value: Dict[str, List[Utterance]]) -> None:
        """Set speaker segments."""
        with self._lock:
            self._speaker_segments = {k: v.copy() for k, v in value.items()} if value else {}
    
    @property
    def speaker_ids(self) -> List[str]:
        """Get speaker IDs list.

        Returns a copy for thread safety. Cache the result if accessing multiple times.
        """
        with self._lock:
            return self._speaker_ids.copy()
    
    @speaker_ids.setter
    def speaker_ids(self, value: List[str]) -> None:
        """Set speaker IDs list."""
        with self._lock:
            self._speaker_ids = value.copy() if value else []
    
    @property
    def speaker_mapping(self) -> Dict[str, str]:
        """Get speaker mapping.

        Returns a copy for thread safety. Cache the result if accessing multiple times.
        """
        with self._lock:
            return self._speaker_mapping.copy()
    
    @speaker_mapping.setter
    def speaker_mapping(self, value: Dict[str, str]) -> None:
        """Set speaker mapping."""
        with self._lock:
            self._speaker_mapping = value.copy() if value else {}
    
    def add_speaker_mapping(self, speaker_id: str, name: str) -> None:
        """Add speaker mapping."""
        with self._lock:
            self._speaker_mapping[speaker_id] = name
    
    @property
    def current_index(self) -> int:
        """Get current speaker index."""
        with self._lock:
            return self._current_index
    
    @current_index.setter
    def current_index(self, value: int) -> None:
        """Set current speaker index."""
        with self._lock:
            self._current_index = value
    
    def increment_current_index(self) -> None:
        """Increment current speaker index."""
        with self._lock:
            self._current_index += 1
    
    @property
    def current_speaker_id(self) -> Optional[str]:
        """Get current speaker ID."""
        with self._lock:
            if 0 <= self._current_index < len(self._speaker_ids):
                return self._speaker_ids[self._current_index]
            return None
    
    @property
    def is_completed(self) -> bool:
        """Check if all speakers have been processed."""
        with self._lock:
            return self._current_index >= len(self._speaker_ids)
    
    @property
    def output_transcript_path(self) -> str:
        """Get output transcript path."""
        with self._lock:
            return self._output_transcript_path
    
    @output_transcript_path.setter
    def output_transcript_path(self, value: str) -> None:
        """Set output transcript path."""
        with self._lock:
            self._output_transcript_path = value
    
    @property
    def active(self) -> bool:
        """Get active status."""
        with self._lock:
            return self._active
    
    @active.setter
    def active(self, value: bool) -> None:
        """Set active status."""
        with self._lock:
            self._active = value
    
    def get_segments_for_speaker(self, speaker_id: str) -> List[Utterance]:
        """Get segments for a specific speaker."""
        with self._lock:
            return self._speaker_segments.get(speaker_id, []).copy()

    def add_temp_file(self, path: str) -> None:
        """Track a temporary file for cleanup."""
        with self._lock:
            self._temp_files.append(path)

    def _cleanup_temp_files(self) -> None:
        """Remove all tracked temporary files."""
        for path in self._temp_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass  # Best effort cleanup
        self._temp_files.clear()

    def reset(self) -> None:
        """Reset state to initial values and cleanup temp files."""
        with self._lock:
            # Cleanup temp files first
            self._cleanup_temp_files()

            self._audio_file = None
            self._audio_duration_ms = 0
            self._transcript_content = ""
            self._utterances.clear()
            self._speaker_occurrences.clear()
            self._speaker_segments.clear()
            self._speaker_ids.clear()
            self._speaker_mapping.clear()
            self._current_index = 0
            self._output_transcript_path = ""
            self._active = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for API responses."""
        with self._lock:
            total = len(self._speaker_ids)
            return {
                'active': self._active,
                'current_index': self._current_index,
                'total_speakers': total,
                'is_completed': self._current_index >= total,
                'speaker_mapping': self._speaker_mapping,
                'output_transcript_path': self._output_transcript_path
            }


# Global speaker labeler state instance
speaker_labeler_state = SpeakerLabelerState()