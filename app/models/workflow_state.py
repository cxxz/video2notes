"""
Workflow state management for Video2Notes application.
"""
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class WorkflowStatus(Enum):
    """Workflow status enumeration."""
    IDLE = 'idle'
    RUNNING = 'running' 
    COMPLETED = 'completed'
    ERROR = 'error'
    STOPPED = 'stopped'


class InteractiveStage(Enum):
    """Interactive workflow stages."""
    SLIDES = 'slides'
    SPEAKERS = 'speakers'


@dataclass
class WorkflowParameters:
    """Parameters for workflow execution."""
    video_path: str = ''
    do_split: bool = False
    timestamp_file: str = ''
    extract_audio: bool = True
    skip_roi: bool = True
    roi_timestamp: Optional[float] = None
    do_label_speakers: bool = True
    do_refine_notes: bool = False
    refine_notes_llm: str = ''
    skip_slide_selection: bool = True  # Default: skip manual slide selection


class WorkflowState:
    """Manages the state of the video2notes workflow."""
    
    def __init__(self):
        self._status = WorkflowStatus.IDLE
        self._current_step = ''
        self._progress = 0
        self._logs: List[str] = []
        self._output_dir = ''
        self._video_path = ''
        self._video_name = ''
        self._slides_dir = ''
        self._audio_path = ''
        self._notes_path = ''
        self._workflow_thread: Optional[threading.Thread] = None
        self._interactive_stage: Optional[InteractiveStage] = None
        self._interactive_ready = False
        self._parameters = WorkflowParameters()
        self._debug_logged = False
        # Thread tracking for parallel refinement
        self._refinement_thread: Optional[threading.Thread] = None
        self._refinement_complete: bool = False
        self._refined_notes_path: Optional[str] = None
        self._lock = threading.Lock()
    
    @property
    def status(self) -> WorkflowStatus:
        """Get current workflow status."""
        with self._lock:
            return self._status
    
    @status.setter
    def status(self, value: WorkflowStatus) -> None:
        """Set workflow status."""
        with self._lock:
            self._status = value
    
    @property
    def current_step(self) -> str:
        """Get current workflow step."""
        with self._lock:
            return self._current_step
    
    @current_step.setter
    def current_step(self, value: str) -> None:
        """Set current workflow step."""
        with self._lock:
            self._current_step = value
    
    @property
    def progress(self) -> int:
        """Get workflow progress (0-100)."""
        with self._lock:
            return self._progress
    
    @progress.setter
    def progress(self, value: int) -> None:
        """Set workflow progress."""
        with self._lock:
            self._progress = max(0, min(100, value))
    
    @property
    def logs(self) -> List[str]:
        """Get workflow logs."""
        with self._lock:
            return self._logs.copy()
    
    def add_log(self, message: str) -> None:
        """Add a log message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        with self._lock:
            self._logs.append(log_entry)
    
    def clear_logs(self) -> None:
        """Clear all logs."""
        with self._lock:
            self._logs.clear()
    
    @property
    def output_dir(self) -> str:
        """Get output directory."""
        with self._lock:
            return self._output_dir
    
    @output_dir.setter
    def output_dir(self, value: str) -> None:
        """Set output directory."""
        with self._lock:
            self._output_dir = value
    
    @property
    def video_path(self) -> str:
        """Get video path."""
        with self._lock:
            return self._video_path
    
    @video_path.setter
    def video_path(self, value: str) -> None:
        """Set video path."""
        with self._lock:
            self._video_path = value
    
    @property
    def video_name(self) -> str:
        """Get video name."""
        with self._lock:
            return self._video_name
    
    @video_name.setter
    def video_name(self, value: str) -> None:
        """Set video name."""
        with self._lock:
            self._video_name = value
    
    @property
    def slides_dir(self) -> str:
        """Get slides directory."""
        with self._lock:
            return self._slides_dir
    
    @slides_dir.setter
    def slides_dir(self, value: str) -> None:
        """Set slides directory."""
        with self._lock:
            self._slides_dir = value
    
    @property
    def audio_path(self) -> str:
        """Get audio path."""
        with self._lock:
            return self._audio_path
    
    @audio_path.setter
    def audio_path(self, value: str) -> None:
        """Set audio path."""
        with self._lock:
            self._audio_path = value
    
    @property
    def notes_path(self) -> str:
        """Get notes path."""
        with self._lock:
            return self._notes_path
    
    @notes_path.setter
    def notes_path(self, value: str) -> None:
        """Set notes path."""
        with self._lock:
            self._notes_path = value
    
    @property
    def workflow_thread(self) -> Optional[threading.Thread]:
        """Get workflow thread."""
        with self._lock:
            return self._workflow_thread
    
    @workflow_thread.setter
    def workflow_thread(self, value: Optional[threading.Thread]) -> None:
        """Set workflow thread."""
        with self._lock:
            self._workflow_thread = value
    
    @property
    def interactive_stage(self) -> Optional[InteractiveStage]:
        """Get interactive stage."""
        with self._lock:
            return self._interactive_stage
    
    @interactive_stage.setter  
    def interactive_stage(self, value: Optional[InteractiveStage]) -> None:
        """Set interactive stage."""
        with self._lock:
            self._interactive_stage = value
    
    @property
    def interactive_ready(self) -> bool:
        """Get interactive ready status."""
        with self._lock:
            return self._interactive_ready
    
    @interactive_ready.setter
    def interactive_ready(self, value: bool) -> None:
        """Set interactive ready status."""
        with self._lock:
            self._interactive_ready = value
    
    @property
    def parameters(self) -> WorkflowParameters:
        """Get workflow parameters."""
        with self._lock:
            return self._parameters
    
    @parameters.setter
    def parameters(self, value: WorkflowParameters) -> None:
        """Set workflow parameters."""
        with self._lock:
            self._parameters = value
    
    @property
    def debug_logged(self) -> bool:
        """Get debug logged status."""
        with self._lock:
            return self._debug_logged
    
    @debug_logged.setter
    def debug_logged(self, value: bool) -> None:
        """Set debug logged status."""
        with self._lock:
            self._debug_logged = value

    @property
    def refinement_thread(self) -> Optional[threading.Thread]:
        """Get refinement thread."""
        with self._lock:
            return self._refinement_thread

    @refinement_thread.setter
    def refinement_thread(self, value: Optional[threading.Thread]) -> None:
        """Set refinement thread."""
        with self._lock:
            self._refinement_thread = value

    @property
    def refinement_complete(self) -> bool:
        """Get refinement completion status."""
        with self._lock:
            return self._refinement_complete

    @refinement_complete.setter
    def refinement_complete(self, value: bool) -> None:
        """Set refinement completion status."""
        with self._lock:
            self._refinement_complete = value

    @property
    def refined_notes_path(self) -> Optional[str]:
        """Get refined notes path."""
        with self._lock:
            return self._refined_notes_path

    @refined_notes_path.setter
    def refined_notes_path(self, value: Optional[str]) -> None:
        """Set refined notes path."""
        with self._lock:
            self._refined_notes_path = value

    def reset(self) -> None:
        """Reset workflow state to initial values."""
        with self._lock:
            self._status = WorkflowStatus.IDLE
            self._current_step = ''
            self._progress = 0
            self._logs.clear()
            self._interactive_stage = None
            self._interactive_ready = False
            self._debug_logged = False
            self._refinement_thread = None
            self._refinement_complete = False
            self._refined_notes_path = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for API responses."""
        with self._lock:
            return {
                'status': self._status.value,
                'current_step': self._current_step,
                'progress': self._progress,
                'interactive_stage': self._interactive_stage.value if self._interactive_stage else None,
                'interactive_ready': self._interactive_ready,
                'output_dir': self._output_dir,
                'log_count': len(self._logs),
                'thread_alive': self._workflow_thread.is_alive() if self._workflow_thread else None
            }


# Global workflow state instance
workflow_state = WorkflowState()