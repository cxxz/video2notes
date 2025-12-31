"""
Speaker service for handling speaker labeling functionality.
"""
import os
import re
from typing import List, Dict, Any, Optional, Tuple
from flask import current_app
from pydub import AudioSegment

from ..models.speaker_labeler import speaker_labeler_state, Utterance
from ..models.workflow_state import workflow_state


class SpeakerService:
    """Service for handling speaker labeling operations."""
    
    def __init__(self):
        self.state = speaker_labeler_state
    
    def initialize_speaker_labeler(self, audio_path: str, transcript_path: str) -> bool:
        """Initialize speaker labeler with audio and transcript."""
        try:
            if not os.path.exists(audio_path):
                current_app.logger.error(f"Audio file not found: {audio_path}")
                return False
                
            if not os.path.exists(transcript_path):
                current_app.logger.error(f"Transcript file not found: {transcript_path}")
                return False
            
            # Load audio file
            audio = AudioSegment.from_file(audio_path)
            self.state.audio_file = audio
            self.state.output_transcript_path = transcript_path.replace('.md', '_with_speakernames.md')
            
            # Load transcript
            if not self._load_transcript_for_labeling(transcript_path):
                return False
            
            self.state.active = True
            workflow_state.add_log(f"Speaker labeler initialized with {len(self.state.speaker_ids)} speakers")
            return True
            
        except Exception as e:
            current_app.logger.error(f"Error initializing speaker labeler: {e}")
            return False
    
    def get_current_speaker_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the current speaker being labeled."""
        if not self.state.active or self.state.is_completed:
            return None
        
        current_speaker_id = self.state.current_speaker_id
        if not current_speaker_id:
            return None
        
        segments = self.state.get_segments_for_speaker(current_speaker_id)
        
        return {
            'speaker_id': current_speaker_id,
            'current_index': self.state.current_index,
            'total_speakers': len(self.state.speaker_ids),
            'segments': [segment.to_dict() for segment in segments],
            'progress_percentage': (self.state.current_index / len(self.state.speaker_ids)) * 100
        }
    
    def label_speaker(self, speaker_id: str, speaker_name: str) -> Dict[str, Any]:
        """Label a speaker and move to the next one."""
        if not self.state.active:
            return {'success': False, 'error': 'Speaker labeler not active'}
        
        try:
            # Update speaker mapping
            if speaker_name.strip():
                self.state.add_speaker_mapping(speaker_id, speaker_name.strip())
                workflow_state.add_log(f"Labeled {speaker_id} as '{speaker_name.strip()}'")
            else:
                workflow_state.add_log(f"Skipped labeling for {speaker_id}")
            
            # Move to next speaker
            self.state.increment_current_index()
            
            completed = self.state.is_completed
            
            if completed:
                # Generate updated transcript
                updated_transcript = self._update_transcript_with_labels()
                output_path = self.state.output_transcript_path
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(updated_transcript)
                
                workflow_state.add_log(f"✅ Speaker labeling completed. Updated transcript saved to: {output_path}")
                self.state.active = False
            
            return {
                'success': True,
                'completed': completed,
                'current_index': self.state.current_index,
                'total_speakers': len(self.state.speaker_ids)
            }
            
        except Exception as e:
            current_app.logger.error(f"Error labeling speaker: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_speaker_audio_segment(self, speaker_id: str, segment_index: int) -> Optional[str]:
        """Generate and return path to audio segment for a speaker."""
        if not self.state.active:
            return None
        
        try:
            segments = self.state.get_segments_for_speaker(speaker_id)
            if segment_index >= len(segments):
                return None
                
            segment = segments[segment_index]
            audio = self.state.audio_file
            
            # Extract audio segment with some padding
            start_ms = max(0, segment.start_ms - 500)  # 0.5s before
            end_ms = min(len(audio), segment.end_ms + 500)  # 0.5s after
            
            audio_segment = audio[start_ms:end_ms]
            
            # Export to temporary file
            temp_path = f"/tmp/speaker_{speaker_id}_segment_{segment_index}.mp3"
            audio_segment.export(temp_path, format="mp3")
            
            return temp_path
            
        except Exception as e:
            current_app.logger.error(f"Error serving speaker audio: {e}")
            return None
    
    def get_labeling_results(self) -> Dict[str, Any]:
        """Get speaker labeling results."""
        mapping = self.state.speaker_mapping
        output_path = self.state.output_transcript_path
        
        return {
            'speaker_mapping': mapping,
            'output_transcript_path': output_path,
            'total_speakers': len(self.state.speaker_ids),
            'labeled_speakers': len(mapping)
        }
    
    def reset_labeler(self) -> None:
        """Reset the speaker labeler state."""
        self.state.reset()
    
    def _load_transcript_for_labeling(self, transcript_path: str) -> bool:
        """Load and parse transcript for speaker labeling."""
        try:
            with open(transcript_path, 'r', encoding='utf-8') as f:
                transcript_content = f.read()
        except Exception as e:
            current_app.logger.error(f"Error loading transcript: {e}")
            return False
        
        # Regex to match utterance headers like: **SPEAKER_09 [00:02.692]:**
        pattern = re.compile(r'\*\*(SPEAKER_\d{2}) \[([0-9:.]+)\]:\*\*')
        utterances = []
        
        for match in pattern.finditer(transcript_content):
            speaker_id = match.group(1)
            timestamp_str = match.group(2)
            start_ms = self._parse_timestamp(timestamp_str)
            
            utterances.append(Utterance(
                speaker_id=speaker_id,
                timestamp_str=timestamp_str,
                start_ms=start_ms,
                match_start=match.start(),
                match_end=match.end()
            ))
        
        if not utterances:
            current_app.logger.error("No speaker utterances found in transcript")
            return False
        
        # Ensure utterances are in the order they appear in the transcript
        utterances.sort(key=lambda u: u.match_start)
        
        # Set the end time for each utterance
        for i in range(len(utterances)):
            if i < len(utterances) - 1:
                utterances[i].end_ms = utterances[i + 1].start_ms
            else:
                utterances[i].end_ms = utterances[i].start_ms + 30000  # Default 30 seconds
        
        # Group utterances by speaker ID
        speaker_occurrences = {}
        for utt in utterances:
            speaker_id = utt.speaker_id
            if speaker_id not in speaker_occurrences:
                speaker_occurrences[speaker_id] = []
            speaker_occurrences[speaker_id].append(utt)
        
        # Create an ordered list of unique speaker IDs
        speaker_ids = sorted(speaker_occurrences.keys(), 
                           key=lambda spk: speaker_occurrences[spk][0].start_ms)
        
        # Choose segments for each speaker (first 3 occurrences)
        speaker_segments = {}
        for spk, occ_list in speaker_occurrences.items():
            speaker_segments[spk] = occ_list[:3]
        
        # Update state
        self.state.transcript_content = transcript_content
        self.state.utterances = utterances
        self.state.speaker_occurrences = speaker_occurrences
        self.state.speaker_segments = speaker_segments
        self.state.speaker_ids = speaker_ids
        self.state.current_index = 0
        
        return True
    
    def _parse_timestamp(self, ts_str: str) -> int:
        """Convert a timestamp string to milliseconds."""
        try:
            parts = ts_str.split(':')
            if len(parts) == 2:
                minutes, seconds = parts
                return int(float(minutes) * 60 * 1000 + float(seconds) * 1000)
            elif len(parts) == 3:
                hours, minutes, seconds = parts
                return int(float(hours) * 3600 * 1000 + float(minutes) * 60 * 1000 + float(seconds) * 1000)
            else:
                return int(float(ts_str) * 1000)
        except Exception as e:
            current_app.logger.error(f"Error parsing timestamp '{ts_str}': {e}")
            return 0
    
    def _update_transcript_with_labels(self) -> str:
        """Replace speaker headers with user-provided names."""
        updated_content = self.state.transcript_content
        speaker_mapping = self.state.speaker_mapping

        # Debug logging
        workflow_state.add_log(f"DEBUG: update_transcript_with_labels called with mapping: {speaker_mapping}")

        pattern = re.compile(r'\*\*(SPEAKER_\d{2})( \[[0-9:.]+\]:\*\*)')

        replacements_made = []

        def replace_func(match):
            speaker_id = match.group(1)
            timestamp_part = match.group(2)

            if speaker_id in speaker_mapping:
                new_name = speaker_mapping[speaker_id]
                replacement = f"**{new_name}{timestamp_part}"
                replacements_made.append(f"{speaker_id} -> {new_name}")
                return replacement
            else:
                return match.group(0)  # No replacement

        updated_content = pattern.sub(replace_func, updated_content)

        # Debug logging
        workflow_state.add_log(f"DEBUG: Made {len(replacements_made)} replacements:")
        for replacement in replacements_made:
            workflow_state.add_log(f"DEBUG: {replacement}")

        return updated_content

    def apply_speaker_labels_to_file(self, input_path: str, output_path: str) -> bool:
        """Apply the current speaker mapping to a transcript file.

        This is used for post-processing refined transcripts after speaker labeling
        is complete but refinement used generic SPEAKER_XX identifiers.

        Args:
            input_path: Path to transcript file with SPEAKER_XX identifiers
            output_path: Path to save the transcript with speaker names

        Returns:
            True if successful, False otherwise
        """
        try:
            speaker_mapping = self.state.speaker_mapping

            if not speaker_mapping:
                # No mapping to apply, just copy the file
                workflow_state.add_log("No speaker mapping available, copying file unchanged")
                with open(input_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True

            with open(input_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Same regex pattern as _update_transcript_with_labels
            pattern = re.compile(r'\*\*(SPEAKER_\d{2})( \[[0-9:.]+\]:\*\*)')
            replacements_made = []

            def replace_func(match):
                speaker_id = match.group(1)
                timestamp_part = match.group(2)

                if speaker_id in speaker_mapping:
                    new_name = speaker_mapping[speaker_id]
                    replacements_made.append(f"{speaker_id} -> {new_name}")
                    return f"**{new_name}{timestamp_part}"
                return match.group(0)

            updated_content = pattern.sub(replace_func, content)

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)

            workflow_state.add_log(f"Applied {len(replacements_made)} speaker label replacements to refined transcript")
            return True

        except Exception as e:
            current_app.logger.error(f"Error applying speaker labels to file: {e}")
            workflow_state.add_log(f"⚠️ Error applying speaker labels to refined transcript: {str(e)}")
            return False