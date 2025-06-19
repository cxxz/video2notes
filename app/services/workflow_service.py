"""
Workflow service for orchestrating the Video2Notes workflow.
"""
import os
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional
from flask import current_app
import logging

from ..models.workflow_state import WorkflowState, WorkflowStatus, WorkflowParameters, InteractiveStage
from ..utils.command_executor import execute_command
from .slide_service import SlideService
from .speaker_service import SpeakerService


class WorkflowService:
    """Service for orchestrating the main video2notes workflow."""
    
    def __init__(self, workflow_state: WorkflowState):
        self.workflow_state = workflow_state
        self.slide_service = SlideService()
        self.speaker_service = SpeakerService()
        self.app = None
        self.logger = logging.getLogger(__name__)
    
    def start_workflow(self, parameters: WorkflowParameters) -> Dict[str, Any]:
        """Start the workflow with given parameters."""
        if self.workflow_state.status == WorkflowStatus.RUNNING:
            return {'success': False, 'error': 'Workflow is already running'}
        
        # Reset workflow state
        self.workflow_state.reset()
        self.workflow_state.parameters = parameters
        
        # Capture the current app for the thread
        self.app = current_app._get_current_object()
        
        # Start workflow in background thread
        workflow_thread = threading.Thread(target=self._run_workflow)
        workflow_thread.daemon = True
        workflow_thread.start()
        self.workflow_state.workflow_thread = workflow_thread
        
        # Set initial status
        self.workflow_state.status = WorkflowStatus.RUNNING
        self.workflow_state.current_step = 'Initializing workflow...'
        self._log_message("🚀 Video2Notes workflow started")
        self._log_message(f"📹 Processing video: {os.path.basename(parameters.video_path)}")
        
        return {'success': True}
    
    def stop_workflow(self) -> Dict[str, Any]:
        """Stop the current workflow."""
        self.workflow_state.status = WorkflowStatus.STOPPED
        self._log_message("🛑 Workflow stopped by user")
        return {'success': True}
    
    def get_workflow_status(self) -> Dict[str, Any]:
        """Get current workflow status."""
        status_data = self.workflow_state.to_dict()
        
        # Add available files for download when workflow is completed
        if self.workflow_state.status == WorkflowStatus.COMPLETED and self.workflow_state.output_dir:
            from .file_service import FileService
            file_service = FileService()
            available_files = file_service.get_available_files(
                self.workflow_state.output_dir, 
                self.workflow_state
            )
            status_data['available_files'] = available_files
        
        return status_data
    
    def _run_workflow(self) -> None:
        """Execute the complete video2notes workflow."""
        with self.app.app_context():
            try:
                self.workflow_state.status = WorkflowStatus.RUNNING
                self.workflow_state.progress = 0
                params = self.workflow_state.parameters
                
                # Setup paths
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                video_path = params.video_path
                base_dir = os.path.dirname(video_path)
                video_name = os.path.splitext(os.path.basename(video_path))[0]
                output_dir = os.path.join(base_dir, f"{video_name}_output_{timestamp}")
                
                os.makedirs(output_dir, exist_ok=True)
                
                self.workflow_state.output_dir = output_dir
                self.workflow_state.video_path = video_path
                self.workflow_state.video_name = video_name
                
                self._log_message(f"📁 Output directory: {output_dir}")
                
                # Step 0: Split video (optional)
                if params.do_split:
                    if not self._split_video(video_path, params.timestamp_file):
                        raise Exception("Video splitting failed")
                
                # Step 1: Preprocess
                if not self._preprocess_video(video_path, output_dir, params):
                    raise Exception("Video preprocessing failed")
                
                # Step 2: Extract slides
                if not self._extract_slides(video_path, video_name, output_dir, timestamp):
                    raise Exception("Slide extraction failed")
                
                # Step 3: Wait for slide selection
                if not self._handle_slide_selection():
                    return  # Workflow stopped during slide selection
                
                # Step 4: Transcribe
                audio_path = self._find_audio_file(output_dir, video_name)
                if not audio_path:
                    raise Exception("No audio file found. Please ensure audio extraction was successful.")
                
                self.workflow_state.audio_path = audio_path
                if not self._transcribe_audio(audio_path, video_name, output_dir):
                    raise Exception("Audio transcription failed")
                
                # Step 5: Generate notes
                notes_path = self._generate_notes(video_name, output_dir)
                if not notes_path:
                    raise Exception("Note generation failed")
                
                # Step 6: Label speakers (optional)
                if params.do_label_speakers:
                    notes_path = self._handle_speaker_labeling(audio_path, notes_path) or notes_path
                
                # Step 7: Refine notes (optional)
                if params.do_refine_notes:
                    if not self._refine_notes(notes_path, output_dir, params.refine_notes_llm):
                        raise Exception("Note refinement failed")
                
                # Workflow completed
                self.workflow_state.current_step = 'Completed'
                self.workflow_state.progress = 100
                self.workflow_state.status = WorkflowStatus.COMPLETED
                self._log_message("🎉 Workflow completed successfully!")
                self._log_message(f"📁 Results saved in: {output_dir}")
                
            except Exception as e:
                self.workflow_state.status = WorkflowStatus.ERROR
                self._log_message(f"💥 Workflow failed: {str(e)}")
                self.logger.error(f"Workflow error: {str(e)}")
    
    def _split_video(self, video_path: str, timestamp_file: str) -> bool:
        """Split video using timestamp file."""
        self.workflow_state.current_step = 'Splitting video'
        self.workflow_state.progress = 5
        
        return execute_command(
            ["python", "scripts/split-video.py", video_path, timestamp_file],
            "Splitting video",
            log_callback=self._log_message
        )
    
    def _preprocess_video(self, video_path: str, output_dir: str, params: WorkflowParameters) -> bool:
        """Preprocess video to extract audio and ROI."""
        self.workflow_state.current_step = 'Preprocessing video'
        self.workflow_state.progress = 15
        
        preprocess_cmd = [
            "python", "scripts/preprocess-video.py",
            "-i", video_path,
            "-o", output_dir
        ]
        
        if params.extract_audio:
            preprocess_cmd.append("-a")
        if params.skip_roi:
            preprocess_cmd.append("-s")
        if params.roi_timestamp:
            preprocess_cmd.extend(["-t", str(params.roi_timestamp)])
        
        return execute_command(preprocess_cmd, "Preprocessing video", log_callback=self._log_message)
    
    def _extract_slides(self, video_path: str, video_name: str, output_dir: str, timestamp: str) -> bool:
        """Extract slides from video."""
        self.workflow_state.current_step = 'Extracting slides'
        self.workflow_state.progress = 30
        
        rois_path = os.path.join(output_dir, f"{video_name}_rois.json")
        slides_dir = os.path.join(output_dir, f"slides_{video_name}_{timestamp}")
        self.workflow_state.slides_dir = slides_dir
        os.makedirs(slides_dir, exist_ok=True)
        
        # Extract slides
        success = execute_command(
            ["python", "scripts/extract-slides.py", 
             "-i", video_path,
             "-j", rois_path,
             "-o", slides_dir],
            "Extracting slides",
            log_callback=self._log_message
        )
        
        if success:
            # Initialize slide selector
            if not self.slide_service.initialize_slide_selector(slides_dir):
                raise Exception("Failed to initialize slide selector")
            
            # Rename original slides.json for user selection
            slides_json = os.path.join(slides_dir, "slides.json")
            original_slides_json = os.path.join(slides_dir, "slides_original.json")
            if os.path.exists(slides_json):
                os.rename(slides_json, original_slides_json)
                self._log_message("Renamed original slides.json to slides_original.json")
        
        return success
    
    def _handle_slide_selection(self) -> bool:
        """Handle slide selection interactive stage."""
        slides_dir = self.workflow_state.slides_dir
        slides_json = os.path.join(slides_dir, "slides.json")
        
        # Wait for slide selection
        self.workflow_state.interactive_stage = InteractiveStage.SLIDES
        self.workflow_state.interactive_ready = True
        self._log_message("🖱️ Slide selection interface is ready")
        self._log_message("Please use the 'Open Slide Selector' button to select slides")
        self._log_message("⏳ Workflow paused - waiting for slide selection...")
        
        # Wait for slides to be selected (user creates new slides.json)
        self._log_message(f"Waiting for slides.json at: {slides_json}")
        while not os.path.exists(slides_json):
            time.sleep(2)
            if self.workflow_state.status != WorkflowStatus.RUNNING:
                self._log_message("Workflow stopped during slide selection")
                return False
            # Log every 10 seconds to show we're still waiting
            if int(time.time()) % 10 == 0:
                self._log_message("Still waiting for slide selection...")
        
        self.workflow_state.interactive_stage = None
        self.workflow_state.interactive_ready = False
        self._log_message("✅ Slide selection completed")
        return True
    
    def _find_audio_file(self, output_dir: str, video_name: str) -> Optional[str]:
        """Find extracted audio file."""
        audio_extensions = ['.m4a', '.mp3']
        for ext in audio_extensions:
            audio_path = os.path.join(output_dir, f"{video_name}{ext}")
            if os.path.exists(audio_path):
                return audio_path
        return None
    
    def _transcribe_audio(self, audio_path: str, video_name: str, output_dir: str) -> bool:
        """Transcribe audio using the transcription service."""
        self.workflow_state.current_step = 'Transcribing audio'
        self.workflow_state.progress = 50
        
        slides_dir = self.workflow_state.slides_dir
        transcript_dir = os.path.join(output_dir, "transcript")
        os.makedirs(transcript_dir, exist_ok=True)
        
        transcript_command = [
            "python", "scripts/transcribe-audio.py",
            "-a", audio_path,
            "-s", slides_dir,
            "-o", transcript_dir,
            "-f", "json"
        ]
        
        # Add model parameters if configured
        whisper_model = current_app.config.get('LOCAL_WHISPER_MODEL')
        if whisper_model:
            transcript_command.extend(["--whisper_model", whisper_model])
        
        diarize_model = current_app.config.get('LOCAL_DIARIZE_MODEL')
        if diarize_model:
            transcript_command.extend(["--diarize_model", diarize_model])
        
        return execute_command(transcript_command, "Transcribing audio", log_callback=self._log_message)
    
    def _generate_notes(self, video_name: str, output_dir: str) -> Optional[str]:
        """Generate notes from transcript and slides."""
        self.workflow_state.current_step = 'Generating notes'
        self.workflow_state.progress = 70
        
        transcript_json = os.path.join(output_dir, "transcript", f"{video_name}.json")
        slides_json = os.path.join(self.workflow_state.slides_dir, "slides.json")
        notes_path = os.path.join(output_dir, f"{video_name}_notes.md")
        
        success = execute_command(
            ["python", "scripts/generate-notes.py",
             "-t", transcript_json,
             "-s", slides_json,
             "-o", notes_path],
            "Generating notes",
            log_callback=self._log_message
        )
        
        if success:
            self.workflow_state.notes_path = notes_path
            return notes_path
        return None
    
    def _handle_speaker_labeling(self, audio_path: str, notes_path: str) -> Optional[str]:
        """Handle speaker labeling interactive stage."""
        self.workflow_state.current_step = 'Labeling speakers'
        self.workflow_state.progress = 80
        
        # Initialize speaker labeler
        if self.speaker_service.initialize_speaker_labeler(audio_path, notes_path):
            self.workflow_state.interactive_stage = InteractiveStage.SPEAKERS
            self.workflow_state.interactive_ready = True
            self._log_message("🎤 Speaker labeling interface is ready")
            self._log_message("Please use the 'Open Speaker Labeler' button to label speakers")
            
            # Wait for speaker labeling to complete
            from ..models.speaker_labeler import speaker_labeler_state
            speaker_labeled_notes = notes_path.replace(".md", "_with_speakernames.md")
            
            while speaker_labeler_state.active:
                time.sleep(2)
                if self.workflow_state.status != WorkflowStatus.RUNNING:
                    return None
            
            if os.path.exists(speaker_labeled_notes):
                self._log_message("✅ Speaker labeling completed")
                return speaker_labeled_notes
            else:
                self._log_message("ℹ️ Speaker labeling skipped or failed, using original notes")
        else:
            self._log_message("⚠️ Failed to initialize speaker labeler, using original notes")
        
        self.workflow_state.interactive_stage = None
        self.workflow_state.interactive_ready = False
        return None
    
    def _refine_notes(self, notes_path: str, output_dir: str, llm_model: str) -> bool:
        """Refine notes using AI."""
        self.workflow_state.current_step = 'Refining notes'
        self.workflow_state.progress = 90
        
        refine_notes_command = [
            "python", "scripts/refine-notes.py",
            "-i", notes_path,
            "-o", output_dir
        ]
        
        # Use specified model or fall back to config/default
        model = llm_model or current_app.config.get('REFINE_NOTES_LLM', 'openai/gpt-4o-2024-08-06')
        if model:
            refine_notes_command.extend(["-m", model])
            self._log_message(f"🤖 Using LLM model for note refinement: {model}")
        else:
            self._log_message("⚠️ No LLM model specified, using default model")
        
        return execute_command(refine_notes_command, "Refining notes with AI", log_callback=self._log_message)
    
    def _log_message(self, message: str) -> None:
        """Add a message to the workflow logs."""
        self.workflow_state.add_log(message)
        # Use app logger if in app context, otherwise use standard logger
        if self.app and self.app.app_context:
            try:
                self.app.logger.info(message)
            except RuntimeError:
                self.logger.info(message)
        else:
            self.logger.info(message)