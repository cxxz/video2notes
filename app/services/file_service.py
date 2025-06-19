"""
File service for handling file operations in Video2Notes application.
"""
import os
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import current_app

from ..utils.file_utils import (
    allowed_file, get_file_size_mb, get_file_info, 
    cleanup_old_uploads, create_output_zip, list_directory_contents
)
from ..utils.security import is_safe_path, validate_file_path_security, sanitize_filename


class FileService:
    """Service for handling file operations."""
    
    def __init__(self):
        self.upload_folder = current_app.config['UPLOAD_FOLDER']
    
    def handle_file_upload(self, file) -> Dict[str, Any]:
        """Handle video file upload."""
        try:
            # Clean up old uploads first
            cleanup_old_uploads()
            
            if not file:
                return {'success': False, 'error': 'No file provided'}
            
            if file.filename == '':
                return {'success': False, 'error': 'No file selected'}
            
            if not allowed_file(file.filename):
                allowed_exts = ', '.join(current_app.config['ALLOWED_EXTENSIONS'])
                return {
                    'success': False, 
                    'error': f'Invalid file type. Allowed types: {allowed_exts}'
                }
            
            # Generate secure filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_name = secure_filename(file.filename)
            name, ext = os.path.splitext(original_name)
            filename = f"{timestamp}_{name}{ext}"
            
            file_path = os.path.join(self.upload_folder, filename)
            
            # Save the file
            file.save(file_path)
            
            # Get file size for validation
            file_size_mb = get_file_size_mb(file_path)
            
            current_app.logger.info(f"Video uploaded: {filename} ({file_size_mb:.1f} MB)")
            
            return {
                'success': True,
                'file_path': file_path,
                'filename': filename,
                'original_name': original_name,
                'size_mb': round(file_size_mb, 1)
            }
            
        except Exception as e:
            current_app.logger.error(f"Upload error: {str(e)}")
            return {'success': False, 'error': f'Upload failed: {str(e)}'}
    
    def browse_files(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Browse files and directories on the server."""
        if path is None:
            path = self.upload_folder
        
        # Security check
        if not is_safe_path(path):
            return {'success': False, 'error': 'Access to this directory is not allowed'}
        
        if not os.path.exists(path):
            return {'success': False, 'error': 'Directory does not exist'}
        
        if not os.path.isdir(path):
            return {'success': False, 'error': 'Path is not a directory'}
        
        try:
            directory_contents = list_directory_contents(path)
            return {
                'success': True,
                **directory_contents
            }
        except PermissionError:
            return {'success': False, 'error': 'Permission denied'}
        except Exception as e:
            current_app.logger.error(f"Error browsing directory {path}: {e}")
            return {'success': False, 'error': 'Error reading directory'}
    
    def get_initial_browse_path(self) -> str:
        """Get the initial path for file browsing."""
        if is_safe_path(self.upload_folder) and os.path.exists(self.upload_folder):
            return self.upload_folder
        else:
            # Fall back to home directory if upload folder doesn't exist
            return os.path.expanduser('~')
    
    def find_most_recent_upload(self) -> Optional[str]:
        """Find the most recent uploaded video file."""
        try:
            upload_files = []
            for filename in os.listdir(self.upload_folder):
                file_path = os.path.join(self.upload_folder, filename)
                if os.path.isfile(file_path) and allowed_file(filename):
                    upload_files.append((file_path, os.path.getmtime(file_path)))
            
            if upload_files:
                # Sort by modification time (most recent first)
                upload_files.sort(key=lambda x: x[1], reverse=True)
                return upload_files[0][0]
            
            return None
        except Exception as e:
            current_app.logger.error(f"Error finding uploaded file: {e}")
            return None
    
    def validate_video_file(self, video_path: str) -> Tuple[bool, Optional[str]]:
        """Validate video file exists and has correct type."""
        if not video_path:
            return False, 'No video file path provided'
        
        if not os.path.exists(video_path):
            return False, f'Video file not found: {video_path}'
        
        if not allowed_file(video_path):
            return False, 'Invalid video file type'
        
        return True, None
    
    def prepare_download_file(self, output_dir: str, filename: str) -> Dict[str, Any]:
        """Prepare file for download with security checks."""
        if not output_dir:
            return {'success': False, 'error': 'No workflow output available'}
        
        # Construct the full file path
        file_path = os.path.join(output_dir, filename)
        
        # Security check: ensure the file is within the output directory
        if not validate_file_path_security(file_path, output_dir):
            current_app.logger.error(f"Download failed: Path traversal attempt - {filename}")
            return {'success': False, 'error': 'Invalid file path'}
        
        if not os.path.exists(file_path):
            current_app.logger.error(f"Download failed: File not found - {file_path}")
            current_app.logger.info(f"Output directory: {output_dir}")
            current_app.logger.info(f"Requested filename: {filename}")
            
            # List available files for debugging
            try:
                available_files = []
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        rel_path = os.path.relpath(os.path.join(root, file), output_dir)
                        available_files.append(rel_path)
                current_app.logger.info(f"Available files in output directory: {available_files}")
            except Exception as e:
                current_app.logger.error(f"Error listing files: {e}")
            
            return {'success': False, 'error': 'File not found'}
        
        current_app.logger.info(f"File ready for download: {file_path}")
        return {
            'success': True,
            'file_path': file_path,
            'filename': filename
        }
    
    def get_available_files(self, output_dir: str, workflow_state) -> List[Dict[str, Any]]:
        """Get list of available files for download."""
        if not output_dir or not os.path.exists(output_dir):
            return []
        
        available_files = []
        
        # Notes file - Only show the latest/most refined version
        latest_notes = self._find_latest_notes_file(output_dir, workflow_state)
        if latest_notes:
            available_files.append(latest_notes)
        
        # Slides metadata
        slides_metadata = self._find_slides_metadata(workflow_state)
        if slides_metadata:
            available_files.append(slides_metadata)
        
        # ZIP file with all outputs
        zip_filename = create_output_zip(output_dir)
        if zip_filename:
            available_files.append({
                'name': 'All Files (ZIP)',
                'filename': zip_filename,
                'icon': '📦',
                'description': 'Complete output folder as ZIP archive'
            })
        
        return available_files
    
    def _find_latest_notes_file(self, output_dir: str, workflow_state) -> Optional[Dict[str, Any]]:
        """Find the latest/most refined notes file."""
        video_name = workflow_state.video_name
        do_refine_notes = workflow_state.parameters.do_refine_notes
        notes_path = workflow_state.notes_path
        
        # Check for refined notes first (highest priority)
        if video_name and do_refine_notes:
            refined_notes_path = os.path.join(output_dir, f"refined_{video_name}_notes_with_speakernames.md")
            if not os.path.exists(refined_notes_path):
                refined_notes_path = os.path.join(output_dir, f"refined_{video_name}_notes.md")
            
            if os.path.exists(refined_notes_path):
                return {
                    'name': 'Notes (Refined)',
                    'filename': os.path.basename(refined_notes_path),
                    'icon': '✨',
                    'description': 'Final notes refined by LLM for clarity'
                }
        
        # If no refined notes, check for speaker-labeled notes (second priority)
        if notes_path:
            speaker_notes_path = notes_path.replace('.md', '_with_speakernames.md')
            if os.path.exists(speaker_notes_path):
                return {
                    'name': 'Notes (with Speaker Names)',
                    'filename': os.path.basename(speaker_notes_path),
                    'icon': '🎤',
                    'description': 'Notes with labeled speakers'
                }
        
        # If no speaker-labeled notes, use original notes (lowest priority)
        if notes_path and os.path.exists(notes_path):
            return {
                'name': 'Notes',
                'filename': os.path.basename(notes_path),
                'icon': '📄',
                'description': 'Generated notes from video'
            }
        
        return None
    
    def _find_slides_metadata(self, workflow_state) -> Optional[Dict[str, Any]]:
        """Find slides metadata file."""
        slides_dir = workflow_state.slides_dir
        if slides_dir and os.path.exists(slides_dir):
            slides_json_path = os.path.join(slides_dir, 'slides.json')
            if os.path.exists(slides_json_path):
                slides_dir_name = os.path.basename(slides_dir)
                return {
                    'name': 'Slides Metadata',
                    'filename': f"{slides_dir_name}/slides.json",
                    'icon': '🖼️',
                    'description': 'Selected slides metadata'
                }
        return None