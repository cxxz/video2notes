import os
import subprocess
import threading
import time
import json
import zipfile
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file, Response, render_template_string, send_from_directory
from werkzeug.utils import secure_filename
import logging
from dotenv import load_dotenv
import shutil
load_dotenv()

# Import utilities for slide selector
from utils import initialize_client, get_llm_response

# Additional imports for speaker labeler
import re
import io
from pydub import AudioSegment

# Import SharePoint downloader
from sharepoint_downloader import SharePointDownloader

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', '/tmp/video2notes_uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_SIZE', 2 * 1024 * 1024 * 1024))  # 2GB default

# Allowed video file extensions
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpg', 'mpeg'}

# Safe directories for browsing (add more as needed)
SAFE_BROWSE_DIRS = [
    os.path.expanduser('~'),  # User home directory
    '/tmp',
    '/Users',  # macOS users directory
    '/home',   # Linux users directory
    '/local',
    '/lustre',
    app.config['UPLOAD_FOLDER']  # Upload folder
]

LOCAL_SERVER = os.getenv('LOCAL_SERVER', 'false')

def get_server_host():
    app.logger.info(f"Whether to use local server: {LOCAL_SERVER}")
    if LOCAL_SERVER == 'true':
        return 'localhost'

    """Get the server host/IP address from the request"""
    # Try to get the host from the request
    host = request.host.split(':')[0]  # Remove port if present
    
    # If it's localhost or 127.0.0.1, try to get actual IP
    if host in ['localhost', '127.0.0.1', '0.0.0.0']:
        # Try to get from X-Forwarded-Host header (if behind proxy)
        forwarded_host = request.headers.get('X-Forwarded-Host')
        if forwarded_host:
            return forwarded_host.split(':')[0]
        
        # Try to get from Host header
        if request.headers.get('Host'):
            return request.headers.get('Host').split(':')[0]
        
        # If still localhost, try to get actual server IP
        import socket
        try:
            # Connect to a remote address to get local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                return local_ip
        except Exception:
            # Fall back to localhost if all else fails
            return 'localhost'
    
    return host

MAIN_APP_PORT = os.getenv('MAIN_APP_PORT', 5100)

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    """Check if file has an allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_size_mb(file_path):
    """Get file size in MB"""
    return os.path.getsize(file_path) / (1024 * 1024)

def cleanup_old_uploads():
    """Clean up old uploaded files (older than 24 hours)"""
    import time
    current_time = time.time()
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.isfile(file_path):
            file_age = current_time - os.path.getmtime(file_path)
            if file_age > 24 * 3600:  # 24 hours
                try:
                    os.remove(file_path)
                    app.logger.info(f"Cleaned up old upload: {filename}")
                except Exception as e:
                    app.logger.error(f"Error cleaning up {filename}: {e}")

def is_safe_path(path):
    """Check if a path is safe to browse (within allowed directories)"""
    try:
        real_path = os.path.realpath(path)
        for safe_dir in SAFE_BROWSE_DIRS:
            safe_real_path = os.path.realpath(safe_dir)
            if real_path.startswith(safe_real_path):
                return True
        return False
    except Exception:
        return False

def get_file_info(file_path):
    """Get file information for display"""
    try:
        stat_info = os.stat(file_path)
        size = stat_info.st_size
        modified = datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M')
        
        # Format file size
        if size < 1024:
            size_str = f"{size} B"
        elif size < 1024 * 1024:
            size_str = f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            size_str = f"{size / (1024 * 1024):.1f} MB"
        else:
            size_str = f"{size / (1024 * 1024 * 1024):.1f} GB"
        
        return {
            'size': size,
            'size_str': size_str,
            'modified': modified
        }
    except Exception:
        return {
            'size': 0,
            'size_str': 'Unknown',
            'modified': 'Unknown'
        }

def create_output_zip(output_dir):
    """Create a ZIP file of the entire output directory"""
    try:
        # Create ZIP filename based on output directory name
        output_basename = os.path.basename(output_dir)
        zip_filename = f"{output_basename}.zip"
        zip_path = os.path.join(output_dir, zip_filename)
        
        # Don't recreate if already exists and is recent
        if os.path.exists(zip_path):
            zip_age = time.time() - os.path.getmtime(zip_path)
            if zip_age < 60:  # If ZIP is less than 1 minute old, reuse it
                return zip_filename
        
        # Create the ZIP file
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    # Skip the ZIP file itself
                    if file == zip_filename:
                        continue
                    
                    file_path = os.path.join(root, file)
                    # Create relative path for inside the ZIP
                    arcname = os.path.relpath(file_path, output_dir)
                    zipf.write(file_path, arcname)
        
        app.logger.info(f"Created ZIP file: {zip_path}")
        return zip_filename
        
    except Exception as e:
        app.logger.error(f"Error creating ZIP file: {e}")
        return None

# Global variables for workflow state
workflow_state = {
    'status': 'idle',  # idle, running, completed, error
    'current_step': '',
    'progress': 0,
    'logs': [],
    'output_dir': '',
    'video_path': '',
    'video_name': '',
    'slides_dir': '',
    'audio_path': '',
    'notes_path': '',
    'workflow_thread': None,
    'interactive_stage': None,  # 'slides' or 'speakers'
    'interactive_ready': False,
    'parameters': {}
}

# Global variables for slide selector
slide_selector_state = {
    'folder_path': '',
    'slides': [],
    'active': False
}

# Global variables for speaker labeler
speaker_labeler_state = {
    'audio_file': None,
    'audio_duration_ms': 0,
    'transcript_content': "",
    'utterances': [],
    'speaker_occurrences': {},
    'speaker_segments': {},
    'speaker_ids': [],
    'speaker_mapping': {},
    'current_index': 0,
    'output_transcript_path': "",
    'active': False
}

# Global variables for SharePoint downloader
sharepoint_state = {
    'downloader': None,
    'video_files': [],
    'selected_file': None,
    'downloading': False,
    'download_progress': 0,
    'active': False
}

def log_message(message):
    """Add a message to the workflow logs with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    workflow_state['logs'].append(log_entry)
    app.logger.info(log_entry)

def execute_command(command, description):
    """Execute a command and capture output in real-time"""
    log_message(f"Starting: {description}")
    log_message(f"Command: {' '.join(command)}")
    
    try:
        process = subprocess.Popen(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True,
            universal_newlines=True
        )
        
        # Read output line by line
        for line in process.stdout:
            line = line.strip()
            if line:
                log_message(line)
        
        return_code = process.wait()
        
        if return_code == 0:
            log_message(f"✅ {description} completed successfully")
            return True
        else:
            log_message(f"❌ {description} failed with return code {return_code}")
            return False
            
    except Exception as e:
        log_message(f"❌ Error executing {description}: {str(e)}")
        return False

def execute_command_with_env(command, description, env):
    """Execute a command with environment variables and capture output in real-time"""
    log_message(f"Starting: {description}")
    log_message(f"Command: {' '.join(command)}")
    
    try:
        process = subprocess.Popen(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True,
            universal_newlines=True,
            env=env
        )
        
        # Read output line by line
        for line in process.stdout:
            line = line.strip()
            if line:
                log_message(line)
        
        return_code = process.wait()
        
        if return_code == 0:
            log_message(f"✅ {description} completed successfully")
            return True
        else:
            log_message(f"❌ {description} failed with return code {return_code}")
            return False
            
    except Exception as e:
        log_message(f"❌ Error executing {description}: {str(e)}")
        return False

def run_workflow():
    """Execute the complete video2notes workflow"""
    try:
        workflow_state['status'] = 'running'
        workflow_state['progress'] = 0
        params = workflow_state['parameters']
        
        # Setup paths
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_path = params['video_path']
        base_dir = os.path.dirname(video_path)
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        output_dir = os.path.join(base_dir, f"{video_name}_output_{timestamp}")
        
        os.makedirs(output_dir, exist_ok=True)
        
        workflow_state['output_dir'] = output_dir
        workflow_state['video_path'] = video_path
        workflow_state['video_name'] = video_name
        
        log_message(f"📁 Output directory: {output_dir}")
        
        # Step 0: Split video (optional)
        if params.get('do_split', False):
            workflow_state['current_step'] = 'Splitting video'
            workflow_state['progress'] = 5
            
            if not execute_command(
                ["python", "split-video.py", video_path, params['timestamp_file']],
                "Splitting video"
            ):
                raise Exception("Video splitting failed")
        
        # Step 1: Preprocess
        workflow_state['current_step'] = 'Preprocessing video'
        workflow_state['progress'] = 15
        
        preprocess_cmd = [
            "python", "preprocess-video.py",
            "-i", video_path,
            "-o", output_dir
        ]
        
        if params.get('extract_audio', True):
            preprocess_cmd.append("-a")
        if params.get('skip_roi', True):
            preprocess_cmd.append("-s")
        if params.get('roi_timestamp'):
            preprocess_cmd.extend(["-t", str(params['roi_timestamp'])])
        
        if not execute_command(preprocess_cmd, "Preprocessing video"):
            raise Exception("Video preprocessing failed")
        
        # Step 2: Extract slides
        workflow_state['current_step'] = 'Extracting slides'
        workflow_state['progress'] = 30
        
        rois_path = os.path.join(output_dir, f"{video_name}_rois.json")
        slides_dir = os.path.join(output_dir, f"slides_{video_name}_{timestamp}")
        workflow_state['slides_dir'] = slides_dir
        os.makedirs(slides_dir, exist_ok=True)
        
        # Extract slides without the --select flag (no separate Flask app)
        if not execute_command(
            ["python", "extract-slides.py", 
             "-i", video_path,
             "-j", rois_path,
             "-o", slides_dir],
            "Extracting slides"
        ):
            raise Exception("Slide extraction failed")
        
        # Initialize integrated slide selector
        if not initialize_slide_selector(slides_dir):
            raise Exception("Failed to initialize slide selector")
        
        # Rename the original slides.json to indicate user needs to select
        slides_json = os.path.join(slides_dir, "slides.json")
        original_slides_json = os.path.join(slides_dir, "slides_original.json")
        if os.path.exists(slides_json):
            os.rename(slides_json, original_slides_json)
            log_message(f"Renamed original slides.json to slides_original.json")
        
        # Wait for slide selection
        workflow_state['interactive_stage'] = 'slides'
        workflow_state['interactive_ready'] = True
        log_message("🖱️ Slide selection interface is ready")
        log_message("Please use the 'Open Slide Selector' button to select slides")
        log_message("⏳ Workflow paused - waiting for slide selection...")
        
        # Wait for slides to be selected (user creates new slides.json)
        while not os.path.exists(slides_json):
            time.sleep(2)
            if workflow_state['status'] != 'running':
                log_message("Workflow stopped during slide selection")
                return
        
        workflow_state['interactive_stage'] = None
        workflow_state['interactive_ready'] = False
        log_message("✅ Slide selection completed")
        
        # Step 3: Transcribe
        workflow_state['current_step'] = 'Transcribing audio'
        workflow_state['progress'] = 50
        
        # the audio can either be .m4a or .mp3, just check which file exists
        audio_path_1 = os.path.join(output_dir, f"{video_name}.m4a")
        audio_path_2 = os.path.join(output_dir, f"{video_name}.mp3")
        if os.path.exists(audio_path_1):
            audio_path = audio_path_1
        elif os.path.exists(audio_path_2):
            audio_path = audio_path_2
        else:
            raise Exception("No audio file found. Please ensure audio extraction was successful.")
        
        workflow_state['audio_path'] = audio_path
        transcript_dir = os.path.join(output_dir, "transcript")
        os.makedirs(transcript_dir, exist_ok=True)

        transcript_command = ["python", "transcribe-audio.py",
             "-a", audio_path,
             "-s", slides_dir,
             "-o", transcript_dir,
             "-f", "json"]

        whisper_model = os.getenv('LOCAL_WHISPER_MODEL', None)
        if whisper_model:
            transcript_command.extend(["--whisper_model", whisper_model])
        diarize_model = os.getenv('LOCAL_DIARIZE_MODEL', None)
        if diarize_model:
            transcript_command.extend(["--diarize_model", diarize_model])

        if not execute_command(
            transcript_command,
            "Transcribing audio"
        ):
            raise Exception("Audio transcription failed")
        
        # Step 4: Generate notes
        workflow_state['current_step'] = 'Generating notes'
        workflow_state['progress'] = 70
        
        transcript_json = os.path.join(transcript_dir, f"{video_name}.json")
        slides_json = os.path.join(slides_dir, "slides.json")
        notes_path = os.path.join(output_dir, f"{video_name}_notes.md")
        workflow_state['notes_path'] = notes_path
        
        if not execute_command(
            ["python", "generate-notes.py",
             "-t", transcript_json,
             "-s", slides_json,
             "-o", notes_path],
            "Generating notes"
        ):
            raise Exception("Note generation failed")
        
        # Step 5: Label speakers (optional)
        notes_for_refinement = notes_path
        
        if params.get('do_label_speakers', True):
            workflow_state['current_step'] = 'Labeling speakers'
            workflow_state['progress'] = 80
            
            # Initialize integrated speaker labeler
            if initialize_speaker_labeler(audio_path, notes_path):
                workflow_state['interactive_stage'] = 'speakers'
                workflow_state['interactive_ready'] = True
                log_message("🎤 Speaker labeling interface is ready")
                log_message("Please use the 'Open Speaker Labeler' button to label speakers")
                
                # Wait for speaker labeling to complete
                speaker_labeled_notes = notes_path.replace(".md", "_with_speakernames.md")
                while speaker_labeler_state['active']:
                    time.sleep(2)
                    if workflow_state['status'] != 'running':
                        return
                
                if os.path.exists(speaker_labeled_notes):
                    notes_for_refinement = speaker_labeled_notes
                    log_message("✅ Speaker labeling completed")
                else:
                    log_message("ℹ️ Speaker labeling skipped or failed, using original notes")
            else:
                log_message("⚠️ Failed to initialize speaker labeler, using original notes")
            
            workflow_state['interactive_stage'] = None
            workflow_state['interactive_ready'] = False
        
        # Step 6: Refine notes (optional)
        if params.get('do_refine_notes', False):
            workflow_state['current_step'] = 'Refining notes'
            workflow_state['progress'] = 90
            
            refine_notes_command = ["python", "refine-notes.py",
                 "-i", notes_for_refinement,
                 "-o", output_dir]
            
            # Use the selected model from the form, fallback to environment variable, then to default
            refine_notes_llm = params.get('refine_notes_llm') or os.getenv('REFINE_NOTES_LLM', 'openai/gpt-4o-2024-08-06')

            if refine_notes_llm:
                refine_notes_command.extend(["-m", refine_notes_llm])
                log_message(f"🤖 Using LLM model for note refinement: {refine_notes_llm}")
            else:
                log_message("⚠️ No LLM model specified, using default model")

            if not execute_command(
                refine_notes_command,
                "Refining notes with AI"
            ):
                raise Exception("Note refinement failed")
        
        # Workflow completed
        workflow_state['current_step'] = 'Completed'
        workflow_state['progress'] = 100
        workflow_state['status'] = 'completed'
        log_message("🎉 Workflow completed successfully!")
        log_message(f"📁 Results saved in: {output_dir}")
        
    except Exception as e:
        workflow_state['status'] = 'error'
        log_message(f"💥 Workflow failed: {str(e)}")
        app.logger.error(f"Workflow error: {str(e)}")

@app.route('/browse_files')
def browse_files():
    """Browse files and directories on the server"""
    path = request.args.get('path', app.config['UPLOAD_FOLDER'])
    
    # Security check
    if not is_safe_path(path):
        return jsonify({'error': 'Access to this directory is not allowed'}), 403
    
    if not os.path.exists(path):
        return jsonify({'error': 'Directory does not exist'}), 404
    
    if not os.path.isdir(path):
        return jsonify({'error': 'Path is not a directory'}), 400
    
    try:
        items = []
        
        # Add parent directory option (except for root)
        parent_path = os.path.dirname(path)
        if parent_path != path and is_safe_path(parent_path):
            items.append({
                'name': '..',
                'path': parent_path,
                'type': 'directory',
                'is_parent': True
            })
        
        # List directory contents
        for item_name in sorted(os.listdir(path)):
            item_path = os.path.join(path, item_name)
            
            try:
                if os.path.isdir(item_path):
                    items.append({
                        'name': item_name,
                        'path': item_path,
                        'type': 'directory',
                        'is_parent': False
                    })
                elif os.path.isfile(item_path):
                    file_info = get_file_info(item_path)
                    is_video = allowed_file(item_name)
                    
                    items.append({
                        'name': item_name,
                        'path': item_path,
                        'type': 'file',
                        'is_video': is_video,
                        'size_str': file_info['size_str'],
                        'modified': file_info['modified'],
                        'is_parent': False
                    })
            except PermissionError:
                # Skip items we can't access
                continue
        
        return jsonify({
            'current_path': path,
            'items': items
        })
        
    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        app.logger.error(f"Error browsing directory {path}: {e}")
        return jsonify({'error': 'Error reading directory'}), 500

@app.route('/get_initial_browse_path')
def get_initial_browse_path():
    """Get the initial path for file browsing"""
    # Use upload folder as the default initial path
    upload_dir = app.config['UPLOAD_FOLDER']
    if is_safe_path(upload_dir) and os.path.exists(upload_dir):
        return jsonify({'path': upload_dir})
    else:
        # Fall back to home directory if upload folder doesn't exist
        home_dir = os.path.expanduser('~')
        return jsonify({'path': home_dir})

@app.route('/')
def index():
    """Main page with workflow configuration form"""
    return render_template('index.html')

@app.route('/start_workflow', methods=['POST'])
def start_workflow():
    """Start the workflow with user parameters"""
    if workflow_state['status'] == 'running':
        return jsonify({'error': 'Workflow is already running'}), 400
    
    # Reset workflow state
    workflow_state.update({
        'status': 'idle',
        'current_step': '',
        'progress': 0,
        'logs': [],
        'interactive_stage': None,
        'interactive_ready': False
    })
    
    # Get parameters from form
    input_method = request.form.get('input_method', '').strip()
    video_path = request.form.get('video_path', '').strip()
    
    # Handle upload method - find the most recent uploaded file
    if input_method == 'upload' and not video_path:
        try:
            # Get the most recent file from upload directory
            upload_files = []
            for filename in os.listdir(app.config['UPLOAD_FOLDER']):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.isfile(file_path) and allowed_file(filename):
                    upload_files.append((file_path, os.path.getmtime(file_path)))
            
            if upload_files:
                # Sort by modification time (most recent first)
                upload_files.sort(key=lambda x: x[1], reverse=True)
                video_path = upload_files[0][0]
                app.logger.info(f"Using uploaded file: {video_path}")
            else:
                app.logger.error("No uploaded video files found")
                return jsonify({'error': 'No uploaded video file found. Please upload a video first.'}), 400
                
        except Exception as e:
            app.logger.error(f"Error finding uploaded file: {e}")
            return jsonify({'error': 'Error accessing uploaded file'}), 400
    
    # Handle SharePoint method - use the downloaded file
    elif input_method == 'sharepoint' and not video_path:
        if sharepoint_state.get('selected_file'):
            # Find the downloaded file in the upload folder
            filename = sharepoint_state['selected_file']['FileLeafRef']
            video_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(video_path):
                app.logger.info(f"Using SharePoint downloaded file: {video_path}")
            else:
                app.logger.error(f"Downloaded SharePoint file not found: {video_path}")
                return jsonify({'error': 'Downloaded SharePoint file not found. Please download a video first.'}), 400
        else:
            app.logger.error("No SharePoint file selected")
            return jsonify({'error': 'No SharePoint video file selected. Please select and download a video first.'}), 400
    
    params = {
        'video_path': video_path,
        'do_split': request.form.get('do_split') == 'on',
        'timestamp_file': request.form.get('timestamp_file', '').strip(),
        'extract_audio': request.form.get('extract_audio', 'on') == 'on',
        'skip_roi': request.form.get('skip_roi', 'on') == 'on',
        'roi_timestamp': request.form.get('roi_timestamp', '').strip(),
        'do_label_speakers': request.form.get('do_label_speakers', 'on') == 'on',
        'do_refine_notes': request.form.get('do_refine_notes') == 'on',
        'refine_notes_llm': request.form.get('refine_notes_llm', '').strip()
    }
    
    # Debug logging
    app.logger.info(f"Input method: '{input_method}'")
    app.logger.info(f"Final video_path: '{params['video_path']}'")
    app.logger.info(f"Refine notes LLM: '{params['refine_notes_llm']}'")
    app.logger.info(f"All form fields: {dict(request.form)}")
    
    # Validation
    if not params['video_path']:
        app.logger.error("No video path provided")
        return jsonify({'error': 'No video file selected or path provided'}), 400
    
    if not os.path.exists(params['video_path']):
        app.logger.error(f"Video path does not exist: {params['video_path']}")
        return jsonify({'error': f'Video file not found: {params["video_path"]}'}), 400
    
    # Additional validation for file type
    if not allowed_file(params['video_path']):
        app.logger.error(f"Invalid file type: {params['video_path']}")
        return jsonify({'error': 'Invalid video file type'}), 400
    
    if params['do_split'] and (not params['timestamp_file'] or not os.path.exists(params['timestamp_file'])):
        return jsonify({'error': 'Timestamp file required for video splitting'}), 400
    
    if params['roi_timestamp']:
        try:
            params['roi_timestamp'] = float(params['roi_timestamp'])
        except ValueError:
            return jsonify({'error': 'Invalid ROI timestamp'}), 400
    
    # Validate refine notes LLM model if specified
    if params.get('do_refine_notes') and params.get('refine_notes_llm'):
        allowed_models = [
            'openai/gpt-4o-2024-08-06',
            'bedrock/claude-4-sonnet',
            'openai/gpt-4.1-mini',
        ]
        if params['refine_notes_llm'] not in allowed_models:
            return jsonify({'error': f'Invalid LLM model selection: {params["refine_notes_llm"]}'}), 400
    
    workflow_state['parameters'] = params
    
    # Start workflow in background thread
    workflow_thread = threading.Thread(target=run_workflow)
    workflow_thread.daemon = True
    workflow_thread.start()
    workflow_state['workflow_thread'] = workflow_thread
    
    # Set initial status
    workflow_state['status'] = 'running'
    workflow_state['current_step'] = 'Initializing workflow...'
    log_message("🚀 Video2Notes workflow started")
    log_message(f"📹 Processing video: {os.path.basename(params['video_path'])}")
    
    return redirect(url_for('workflow_progress'))

@app.route('/workflow')
def workflow_progress():
    """Workflow progress page"""
    return render_template('workflow.html')

@app.route('/progress_stream')
def progress_stream():
    """Server-sent events for real-time progress updates"""
    def generate():
        last_log_count = 0
        while True:
            # Send current status
            data = {
                'status': workflow_state['status'],
                'current_step': workflow_state['current_step'],
                'progress': workflow_state['progress'],
                'interactive_stage': workflow_state['interactive_stage'],
                'interactive_ready': workflow_state['interactive_ready'],
                'new_logs': workflow_state['logs'][last_log_count:]
            }
            
            yield f"data: {json.dumps(data)}\n\n"
            last_log_count = len(workflow_state['logs'])
            
            if workflow_state['status'] in ['completed', 'error', 'stopped']:
                # Send one final update after a short delay to ensure frontend receives it
                time.sleep(0.5)
                yield f"data: {json.dumps(data)}\n\n"
                break
                
            time.sleep(1)
    
    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Cache-Control'
    return response


@app.route('/open_slides')
def open_slides():
    """Redirect to slide selector"""
    if workflow_state['interactive_stage'] != 'slides' or not workflow_state['interactive_ready']:
        return jsonify({'error': 'Slide selector not ready'}), 400
    
    return redirect(url_for('select_slides_index'))

@app.route('/open_speakers')
def open_speakers():
    """Redirect to speaker labeler"""
    if workflow_state['interactive_stage'] != 'speakers' or not workflow_state['interactive_ready']:
        return jsonify({'error': 'Speaker labeler not ready'}), 400
    
    return redirect(url_for('label_speakers_index'))

@app.route('/status')
def status():
    """Get current workflow status"""
    status_data = {
        'status': workflow_state['status'],
        'current_step': workflow_state['current_step'],
        'progress': workflow_state['progress'],
        'interactive_stage': workflow_state['interactive_stage'],
        'interactive_ready': workflow_state['interactive_ready'],
        'output_dir': workflow_state['output_dir']
    }
    
    # Add available files for download when workflow is completed
    if workflow_state['status'] == 'completed' and workflow_state['output_dir']:
        available_files = []
        # Only log detailed debug info on first completion check
        if not hasattr(workflow_state, '_debug_logged'):
            app.logger.info(f"DEBUG: Checking available files. Status: {workflow_state['status']}, Output dir: {workflow_state['output_dir']}")
            app.logger.info(f"DEBUG: Notes path: {workflow_state.get('notes_path')}, exists: {os.path.exists(workflow_state.get('notes_path', '')) if workflow_state.get('notes_path') else 'N/A'}")
            workflow_state['_debug_logged'] = True
        
        # Notes file - Only show the latest/most refined version
        latest_notes = None
        
        # Check for refined notes first (highest priority)
        if workflow_state.get('video_name') and workflow_state['parameters'].get('do_refine_notes'):
            refined_notes_path = os.path.join(workflow_state['output_dir'], f"refined_{workflow_state['video_name']}_notes_with_speakernames.md")
            if not os.path.exists(refined_notes_path):
                refined_notes_path = os.path.join(workflow_state['output_dir'], f"refined_{workflow_state['video_name']}_notes.md")
            
            if os.path.exists(refined_notes_path):
                latest_notes = {
                    'name': 'Notes (Refined)',
                    'filename': os.path.basename(refined_notes_path),
                    'icon': '✨',
                    'description': 'Final notes refined by LLM for clarity'
                }
        
        # If no refined notes, check for speaker-labeled notes (second priority)
        if not latest_notes and workflow_state.get('notes_path'):
            speaker_notes_path = workflow_state['notes_path'].replace('.md', '_with_speakernames.md')
            if os.path.exists(speaker_notes_path):
                latest_notes = {
                    'name': 'Notes (with Speaker Names)',
                    'filename': os.path.basename(speaker_notes_path),
                    'icon': '🎤',
                    'description': 'Notes with labeled speakers'
                }
        
        # If no speaker-labeled notes, use original notes (lowest priority)
        if not latest_notes and workflow_state.get('notes_path'):
            if os.path.exists(workflow_state['notes_path']):
                latest_notes = {
                    'name': 'Notes',
                    'filename': os.path.basename(workflow_state['notes_path']),
                    'icon': '📄',
                    'description': 'Generated notes from video'
                }
        
        # Add the latest notes to available files
        if latest_notes:
            available_files.append(latest_notes)
            if not workflow_state.get('_debug_logged'):
                app.logger.info(f"DEBUG: Added latest notes file: {latest_notes['name']} - {latest_notes['filename']}")
        elif not workflow_state.get('_debug_logged'):
            app.logger.info(f"DEBUG: No notes file found")
        
                # Slides directory (as ZIP if we want to compress it)
        if workflow_state.get('slides_dir') and os.path.exists(workflow_state['slides_dir']):
            slides_json_path = os.path.join(workflow_state['slides_dir'], 'slides.json')
            if os.path.exists(slides_json_path):
                slides_dir_name = os.path.basename(workflow_state['slides_dir'])
                available_files.append({
                    'name': 'Slides Metadata',
                    'filename': f"{slides_dir_name}/slides.json",
                    'icon': '🖼️',
                    'description': 'Selected slides metadata'
                })
        
        # ZIP file with all outputs
        zip_filename = create_output_zip(workflow_state['output_dir'])
        if zip_filename:
            available_files.append({
                'name': 'All Files (ZIP)',
                'filename': zip_filename,
                'icon': '📦',
                'description': 'Complete output folder as ZIP archive'
            })
        
        status_data['available_files'] = available_files
        if not workflow_state.get('_debug_logged'):
            app.logger.info(f"DEBUG: Final available_files list has {len(available_files)} items: {[f['name'] for f in available_files]}")
    
    return jsonify(status_data)

@app.route('/download/<path:filename>')
def download_file(filename):
    """Download generated files"""
    if not workflow_state['output_dir']:
        app.logger.error("Download failed: No workflow output available")
        return jsonify({'error': 'No workflow output available'}), 404
    
    # Construct the full file path
    file_path = os.path.join(workflow_state['output_dir'], filename)
    
    # Security check: ensure the file is within the output directory
    real_output_dir = os.path.realpath(workflow_state['output_dir'])
    real_file_path = os.path.realpath(file_path)
    
    if not real_file_path.startswith(real_output_dir):
        app.logger.error(f"Download failed: Path traversal attempt - {filename}")
        return jsonify({'error': 'Invalid file path'}), 403
    
    if not os.path.exists(file_path):
        app.logger.error(f"Download failed: File not found - {file_path}")
        app.logger.info(f"Output directory: {workflow_state['output_dir']}")
        app.logger.info(f"Requested filename: {filename}")
        
        # List available files for debugging
        try:
            available_files = []
            for root, dirs, files in os.walk(workflow_state['output_dir']):
                for file in files:
                    rel_path = os.path.relpath(os.path.join(root, file), workflow_state['output_dir'])
                    available_files.append(rel_path)
            app.logger.info(f"Available files in output directory: {available_files}")
        except Exception as e:
            app.logger.error(f"Error listing files: {e}")
        
        return jsonify({'error': 'File not found'}), 404
    
    app.logger.info(f"Downloading file: {file_path}")
    
    # Handle ZIP files with proper content type
    if filename.lower().endswith('.zip'):
        return send_file(file_path, as_attachment=True, mimetype='application/zip')
    else:
        return send_file(file_path, as_attachment=True)

@app.route('/stop_workflow', methods=['POST'])
def stop_workflow():
    """Stop the current workflow"""
    workflow_state['status'] = 'stopped'
    log_message("🛑 Workflow stopped by user")
    return jsonify({'success': True})

@app.route('/debug')
def debug():
    """Debug endpoint to check workflow state"""
    return jsonify({
        'workflow_state': {
            'status': workflow_state['status'],
            'current_step': workflow_state['current_step'],
            'progress': workflow_state['progress'],
            'interactive_stage': workflow_state['interactive_stage'],
            'interactive_ready': workflow_state['interactive_ready'],
            'log_count': len(workflow_state['logs']),
            'last_3_logs': workflow_state['logs'][-3:] if workflow_state['logs'] else [],
            'thread_alive': workflow_state['workflow_thread'].is_alive() if workflow_state['workflow_thread'] else None
        }
    })

@app.route('/debug/services')
def debug_services():
    """Debug endpoint to check service availability"""
    services = {
        'slide_selector': {
            'integrated': True,
            'active': slide_selector_state['active'],
            'slides_count': len(slide_selector_state['slides']) if slide_selector_state['slides'] else 0
        },
        'speaker_labeler': {
            'integrated': True,
            'active': speaker_labeler_state['active'],
            'speakers_count': len(speaker_labeler_state['speaker_ids']) if speaker_labeler_state['speaker_ids'] else 0
        }
    }
    
    return jsonify({
        'services': services,
        'architecture': 'integrated',
        'workflow_interactive_stage': workflow_state.get('interactive_stage'),
        'workflow_interactive_ready': workflow_state.get('interactive_ready')
    })

@app.route('/debug_form', methods=['POST'])
def debug_form():
    """Debug endpoint to check form submission data"""
    form_data = dict(request.form)
    files_data = {key: file.filename for key, file in request.files.items()}
    
    return jsonify({
        'form_data': form_data,
        'files_data': files_data,
        'video_path': request.form.get('video_path', ''),
        'video_path_exists': os.path.exists(request.form.get('video_path', '')) if request.form.get('video_path') else False
    })

@app.route('/upload_video', methods=['POST'])
def upload_video():
    """Handle video file upload"""
    try:
        # Clean up old uploads first
        cleanup_old_uploads()
        
        if 'video_file' not in request.files:
            return jsonify({'error': 'No file selected'}), 400
        
        file = request.files['video_file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': f'Invalid file type. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'}), 400
        
        # Generate secure filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_name = secure_filename(file.filename)
        name, ext = os.path.splitext(original_name)
        filename = f"{timestamp}_{name}{ext}"
        
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Save the file
        file.save(file_path)
        
        # Get file size for validation
        file_size_mb = get_file_size_mb(file_path)
        
        app.logger.info(f"Video uploaded: {filename} ({file_size_mb:.1f} MB)")
        
        return jsonify({
            'success': True,
            'file_path': file_path,
            'filename': filename,
            'original_name': original_name,
            'size_mb': round(file_size_mb, 1)
        })
        
    except Exception as e:
        app.logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

# SharePoint Downloader Routes
@app.route('/sharepoint/list_videos', methods=['GET'])
def sharepoint_list_videos():
    """Get list of video files from SharePoint"""
    try:
        # Initialize SharePoint downloader
        download_dir = app.config['UPLOAD_FOLDER']
        sharepoint_url = os.getenv('SHAREPOINT_URL', None)
        if not sharepoint_url:
            return jsonify({'error': 'SHAREPOINT_URL environment variable not set'}), 500
        
        downloader = SharePointDownloader(
            sharepoint_url=sharepoint_url,
            output_dir=download_dir
        )

        # Get video files from SharePoint
        video_files = downloader.get_video_files()
        
        # Store in global state
        sharepoint_state['downloader'] = downloader
        sharepoint_state['video_files'] = video_files
        sharepoint_state['active'] = True
        
        # Prepare simplified file list for frontend
        file_list = []
        for i, video_file in enumerate(video_files[:10]):  # Show max 10 files
            file_info = {
                'index': i,
                'filename': video_file['FileLeafRef'],
                'modified': video_file.get('Modified.', 'Unknown'),
                'size': video_file.get('FileSizeDisplay', 'Unknown')
            }
            file_list.append(file_info)
        
        app.logger.info(f"Found {len(video_files)} SharePoint video files")
        
        return jsonify({
            'success': True,
            'files': file_list,
            'total_count': len(video_files)
        })
        
    except Exception as e:
        app.logger.error(f"SharePoint list error: {str(e)}")
        return jsonify({'error': f'Failed to list SharePoint videos: {str(e)}'}), 500

@app.route('/sharepoint/download/<int:file_index>', methods=['POST'])
def sharepoint_download_video(file_index):
    """Download selected video file from SharePoint"""
    try:
        if not sharepoint_state.get('active') or not sharepoint_state.get('video_files'):
            return jsonify({'error': 'SharePoint video list not loaded. Please list videos first.'}), 400
        
        video_files = sharepoint_state['video_files']
        if file_index < 0 or file_index >= len(video_files):
            return jsonify({'error': 'Invalid file index'}), 400
        
        selected_file = video_files[file_index]
        downloader = sharepoint_state['downloader']
        
        if not downloader:
            return jsonify({'error': 'SharePoint downloader not initialized'}), 400
        
        # Set downloading state
        sharepoint_state['downloading'] = True
        sharepoint_state['selected_file'] = selected_file
        
        filename = selected_file['FileLeafRef']
        app.logger.info(f"Starting download of SharePoint file: {filename}")
        
        # Download the file
        success = downloader.download_file(selected_file)
        
        sharepoint_state['downloading'] = False
        
        if success:
            # Verify the file was downloaded
            expected_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(expected_path):
                file_size_mb = get_file_size_mb(expected_path)
                app.logger.info(f"SharePoint video downloaded: {filename} ({file_size_mb:.1f} MB)")
                
                return jsonify({
                    'success': True,
                    'filename': filename,
                    'file_path': expected_path,
                    'size_mb': round(file_size_mb, 1)
                })
            else:
                app.logger.error(f"Downloaded file not found at expected path: {expected_path}")
                return jsonify({'error': 'Download completed but file not found'}), 500
        else:
            app.logger.error(f"Failed to download SharePoint file: {filename}")
            return jsonify({'error': 'Download failed'}), 500
            
    except Exception as e:
        sharepoint_state['downloading'] = False
        app.logger.error(f"SharePoint download error: {str(e)}")
        return jsonify({'error': f'Download failed: {str(e)}'}), 500

@app.route('/sharepoint/status')
def sharepoint_status():
    """Get SharePoint downloader status"""
    return jsonify({
        'active': sharepoint_state.get('active', False),
        'downloading': sharepoint_state.get('downloading', False),
        'files_count': len(sharepoint_state.get('video_files', [])),
        'selected_file': sharepoint_state.get('selected_file', {}).get('FileLeafRef') if sharepoint_state.get('selected_file') else None
    })

# Slide Selector Helper Functions
def extract_vocabulary(ocr_text, model_id='bedrock/claude-4-sonnet'):
    """Extract domain-specific vocabulary terms from the OCR transcript."""
    extract_voc_prompt = f"""
Your task is to extract domain-specific vocabularies from the transcript below:
<transcript>
{ocr_text}
</transcript>

The terms and abbreviations include those that:
- Appear infrequently in general knowledge
- Are technical jargon or abbreviations with specific meanings
- Can be easily confused with more common words that sound similar
- Require precise spelling and recognition for downstream applications
- Significantly impact the meaning of the entire transcription if misrecognized

Now extract 20 to 30 vocabulary terms from the transcript:
1. Output them in a comma-separated list
2. If they are abbreviations, do not spell out the full names.
"""
    client = initialize_client(model_id)
    return get_llm_response(client, model_id, extract_voc_prompt)

def render_slide_page(title, header_title, content):
    """Render a full HTML page with a common base layout for slide selector."""
    base_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{{ title }}</title>
      <link rel="stylesheet" href="/static/css/hpe-design.css">
      <style>
         /* Page-specific overrides for slide selector */
         .vocabulary-section {
             margin-top: var(--hpe-space-6);
             padding: var(--hpe-space-5);
             background: var(--hpe-gray-100);
             border-radius: var(--hpe-radius-md);
         }
         
         .vocabulary-controls {
             display: flex;
             align-items: center;
             gap: var(--hpe-space-3);
             margin-bottom: var(--hpe-space-4);
         }
         
         .vocabulary-result {
             background: var(--hpe-white);
             border: 1px solid var(--hpe-gray-300);
             border-radius: var(--hpe-radius-md);
             padding: var(--hpe-space-4);
             margin-top: var(--hpe-space-4);
         }
         
         .vocabulary-content {
             background: var(--hpe-gray-100);
             padding: var(--hpe-space-4);
             border-radius: var(--hpe-radius-md);
             margin: var(--hpe-space-3) 0;
             white-space: pre-wrap;
             font-family: var(--hpe-font-mono);
             font-size: 0.9rem;
         }
         
         .vocabulary-status {
             margin-top: var(--hpe-space-3);
             font-weight: 500;
         }
      </style>
    </head>
    <body class="hpe-page-wrapper">
      <div class="hpe-container">
        <div class="hpe-header">
          <h1>{{ header_title }}</h1>
        </div>
        {{ content|safe }}
      </div>
    </body>
    </html>
    """
    return render_template_string(base_template, title=title, header_title=header_title, content=content)

def process_slides(selected_ids, slides, folder_path):
    """Process the slides based on selected IDs."""
    pruned = []
    
    # Backup original slides.json to ori_slides.json
    original_slides_path = os.path.join(folder_path, "slides.json")
    backup_slides_path = os.path.join(folder_path, "ori_slides.json")
    if os.path.exists(original_slides_path) and not os.path.exists(backup_slides_path):
        shutil.copy2(original_slides_path, backup_slides_path)
    
    for slide in slides:
        if slide["group_id"] in selected_ids:
            pruned.append(slide)
                
    return pruned

def initialize_slide_selector(folder_path):
    """Initialize the slide selector with the given folder"""
    if folder_path.endswith(os.sep):
        folder_path = folder_path[:-1]
    
    # Load slides.json from the folder (check for original file first)
    json_path = os.path.join(folder_path, "slides.json")
    original_json_path = os.path.join(folder_path, "slides_original.json")
    
    # Use original file if it exists, otherwise use slides.json
    if os.path.exists(original_json_path):
        json_path = original_json_path
    
    try:
        with open(json_path, 'r') as f:
            slides = json.load(f)
    except Exception as e:
        app.logger.error(f"Error loading slides.json: {e}")
        return False
        
    # Update each slide with a relative image path
    folder_basename = os.path.basename(folder_path)
    for slide in slides:
        # Extract filename from image_path (slides JSON uses 'image_path' not 'filename')
        filename = os.path.basename(slide['image_path'])
        slide["image_url"] = f"/slide-images/{folder_basename}/{filename}"
    
    # Set global state
    slide_selector_state['folder_path'] = folder_path
    slide_selector_state['slides'] = slides
    slide_selector_state['active'] = True
    
    log_message(f"Slide selector initialized with {len(slides)} slides")
    return True

# Slide Selector Routes
@app.route('/select-slides')
def select_slides_index():
    """Main slide selection page"""
    if not slide_selector_state['active']:
        return render_slide_page(
            "Slide Selector - Error", 
            "Slide Selector", 
            "<div class='hpe-alert hpe-alert-danger'>Slide selector not initialized</div>"
        )
    
    slides = slide_selector_state['slides']
    folder_path = slide_selector_state['folder_path']
    
    # Generate HTML for slides - one per row with larger images
    slides_html = ""
    for slide in slides:
        slides_html += f"""
        <div class="slide-item" data-slide-id="{slide['group_id']}">
            <div class="slide-checkbox">
                <input type="checkbox" id="slide_{slide['group_id']}" value="{slide['group_id']}" checked>
                <label for="slide_{slide['group_id']}">
                    <span class="checkbox-label">Select Slide {slide['group_id']}</span>
                </label>
            </div>
            <div class="slide-content">
                <img src="{slide['image_url']}" alt="Slide {slide['group_id']}" class="slide-image">
                <div class="slide-info">
                    <h4>Slide {slide['group_id']}</h4>
                    <p>Timestamp: {slide.get('timestamp', 'Unknown')}</p>
                </div>
            </div>
        </div>
        """
    
    content = f"""
    <div class="slides-container">
        <!-- Top controls -->
        <div class="slides-header">
            <div class="slides-controls">
                <button id="select-all" class="hpe-btn hpe-btn-secondary">Select All</button>
                <button id="deselect-all" class="hpe-btn hpe-btn-secondary">Deselect All</button>
                <button id="save-selection-top" class="hpe-btn hpe-btn-primary hpe-btn-lg">Save Selection and Continue the Workflow</button>
            </div>
            <div class="slide-count">
                <span id="selected-count">{len(slides)}</span> of {len(slides)} slides selected
            </div>
        </div>
        
        <div class="slides-list">
            {slides_html}
        </div>
        
        <!-- Bottom controls -->
        <div class="slides-footer">
            <div class="slides-controls">
                <button id="select-all-bottom" class="hpe-btn hpe-btn-secondary">Select All</button>
                <button id="deselect-all-bottom" class="hpe-btn hpe-btn-secondary">Deselect All</button>
                <button id="save-selection-bottom" class="hpe-btn hpe-btn-primary hpe-btn-lg">Save Selection and Continue the Workflow</button>
            </div>
            <div class="slide-count">
                <span id="selected-count-bottom">{len(slides)}</span> of {len(slides)} slides selected
            </div>
        </div>
        
        <div class="vocabulary-section">
            <h3>Extract Vocabulary (Optional)</h3>
            <div class="vocabulary-controls">
                <button id="extract-vocab" class="hpe-btn hpe-btn-secondary">Extract Domain Vocabulary</button>
                <select id="vocab-model" class="hpe-input">
                    <option value="openai/gpt-4o-2024-08-06">GPT-4o</option>
                    <option value="bedrock/claude-4-sonnet">Claude 4 Sonnet</option>
                </select>
            </div>
            <div id="vocab-result" class="vocabulary-result hpe-hidden">
                <h4>Extracted Vocabulary:</h4>
                <textarea id="vocab-content" class="vocabulary-content" rows="10" placeholder="Vocabulary will appear here after extraction..."></textarea>
                <div class="vocabulary-actions">
                    <button id="save-vocab" class="hpe-btn hpe-btn-success">Save Vocabularies</button>
                    <div id="vocab-status" class="vocabulary-status"></div>
                </div>
            </div>
        </div>
    </div>
    
    <style>
        .slides-container {{ max-width: 1000px; margin: 0 auto; }}
        .slides-header, .slides-footer {{ display: flex; justify-content: space-between; align-items: center; margin: 2rem 0; padding: 1.5rem; background: var(--hpe-gray-100); border-radius: var(--hpe-radius-md); }}
        .slides-controls {{ display: flex; gap: 1rem; align-items: center; }}
        .slides-list {{ display: flex; flex-direction: column; gap: 2rem; }}
        .slide-item {{ border: 2px solid #ddd; border-radius: 12px; padding: 2rem; background: white; transition: all 0.3s ease; }}
        .slide-item.selected {{ border-color: var(--hpe-blue); background-color: #f0f8ff; box-shadow: 0 4px 12px rgba(0, 123, 186, 0.1); }}
        .slide-checkbox {{ margin-bottom: 1rem; }}
        .slide-checkbox input[type="checkbox"] {{ transform: scale(1.2); margin-right: 0.5rem; }}
        .checkbox-label {{ font-weight: 600; color: var(--hpe-blue); }}
        .slide-content {{ display: flex; flex-direction: column; align-items: center; }}
        .slide-image {{ width: 100%; max-width: 800px; height: auto; min-height: 400px; object-fit: contain; border: 2px solid #eee; border-radius: 8px; background: #fafafa; }}
        .slide-info {{ text-align: center; margin-top: 1rem; }}
        .slide-info h4 {{ margin: 0.5rem 0; font-size: 1.2rem; color: var(--hpe-blue); }}
        .slide-info p {{ margin: 0.25rem 0; font-size: 1rem; color: #666; }}
        .vocabulary-actions {{ display: flex; align-items: center; gap: 1rem; margin-top: 1rem; }}
        .vocabulary-content {{ width: 100%; padding: 1rem; border: 1px solid #ddd; border-radius: var(--hpe-radius-md); font-family: monospace; resize: vertical; }}
    </style>
    
    <script>
        let selectedSlides = new Set({json.dumps([slide['group_id'] for slide in slides])});
        
        function updateSelectedCount() {{
            const count = selectedSlides.size;
            document.getElementById('selected-count').textContent = count;
            document.getElementById('selected-count-bottom').textContent = count;
        }}
        
        function updateSlideAppearance(slideId, isSelected) {{
            const slideItem = document.querySelector(`[data-slide-id="${{slideId}}"]`);
            if (isSelected) {{
                slideItem.classList.add('selected');
            }} else {{
                slideItem.classList.remove('selected');
            }}
        }}
        
        function selectAllSlides() {{
            document.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {{
                checkbox.checked = true;
                selectedSlides.add(parseInt(checkbox.value));
                updateSlideAppearance(parseInt(checkbox.value), true);
            }});
            updateSelectedCount();
        }}
        
        function deselectAllSlides() {{
            document.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {{
                checkbox.checked = false;
                selectedSlides.delete(parseInt(checkbox.value));
                updateSlideAppearance(parseInt(checkbox.value), false);
            }});
            updateSelectedCount();
        }}
        
        function saveSelection() {{
            const selectedIds = Array.from(selectedSlides);
            
            fetch('/save-slide-selection', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{
                    selected_ids: selectedIds
                }})
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    alert(`Selection saved! ${{selectedIds.length}} slides selected. The workflow will continue.`);
                    window.close();
                }} else {{
                    alert('Error saving selection: ' + data.error);
                }}
            }})
            .catch(error => {{
                alert('Error saving selection: ' + error.message);
            }});
        }}
        
        // Handle checkbox changes
        document.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {{
            checkbox.addEventListener('change', function() {{
                const slideId = parseInt(this.value);
                if (this.checked) {{
                    selectedSlides.add(slideId);
                }} else {{
                    selectedSlides.delete(slideId);
                }}
                updateSelectedCount();
                updateSlideAppearance(slideId, this.checked);
            }});
        }});
        
        // Top controls
        document.getElementById('select-all').addEventListener('click', selectAllSlides);
        document.getElementById('deselect-all').addEventListener('click', deselectAllSlides);
        document.getElementById('save-selection-top').addEventListener('click', saveSelection);
        
        // Bottom controls
        document.getElementById('select-all-bottom').addEventListener('click', selectAllSlides);
        document.getElementById('deselect-all-bottom').addEventListener('click', deselectAllSlides);
        document.getElementById('save-selection-bottom').addEventListener('click', saveSelection);
        
        // Extract vocabulary functionality
        document.getElementById('extract-vocab').addEventListener('click', function() {{
            const model = document.getElementById('vocab-model').value;
            const button = this;
            const resultDiv = document.getElementById('vocab-result');
            const contentTextarea = document.getElementById('vocab-content');
            const statusDiv = document.getElementById('vocab-status');
            
            button.disabled = true;
            button.textContent = 'Extracting...';
            statusDiv.textContent = 'Extracting vocabulary terms...';
            resultDiv.classList.remove('hpe-hidden');
            
            fetch('/extract-vocabulary-ajax', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{
                    model_id: model
                }})
            }})
            .then(response => response.json())
            .then(data => {{
                button.disabled = false;
                button.textContent = 'Extract Domain Vocabulary';
                
                if (data.success) {{
                    contentTextarea.value = data.vocabulary;
                    statusDiv.textContent = 'Vocabulary extraction completed. You can edit the text above and save it.';
                    statusDiv.style.color = 'green';
                }} else {{
                    contentTextarea.value = 'Error: ' + data.error;
                    statusDiv.textContent = 'Vocabulary extraction failed.';
                    statusDiv.style.color = 'red';
                }}
            }})
            .catch(error => {{
                button.disabled = false;
                button.textContent = 'Extract Domain Vocabulary';
                contentTextarea.value = 'Error: ' + error.message;
                statusDiv.textContent = 'Vocabulary extraction failed.';
                statusDiv.style.color = 'red';
            }});
        }});
        
        // Save vocabulary functionality
        document.getElementById('save-vocab').addEventListener('click', function() {{
            const vocabularyText = document.getElementById('vocab-content').value.trim();
            const button = this;
            const statusDiv = document.getElementById('vocab-status');
            
            if (!vocabularyText) {{
                alert('Please extract or enter vocabulary text first.');
                return;
            }}
            
            button.disabled = true;
            button.textContent = 'Saving...';
            statusDiv.textContent = 'Saving vocabulary...';
            
            fetch('/save-vocabulary', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{
                    vocabulary: vocabularyText
                }})
            }})
            .then(response => response.json())
            .then(data => {{
                button.disabled = false;
                button.textContent = 'Save Vocabularies';
                
                if (data.success) {{
                    statusDiv.textContent = 'Vocabulary saved successfully to vocabulary.txt';
                    statusDiv.style.color = 'green';
                }} else {{
                    statusDiv.textContent = 'Error saving vocabulary: ' + data.error;
                    statusDiv.style.color = 'red';
                }}
            }})
            .catch(error => {{
                button.disabled = false;
                button.textContent = 'Save Vocabularies';
                statusDiv.textContent = 'Error saving vocabulary: ' + error.message;
                statusDiv.style.color = 'red';
            }});
        }});
        
        // Initialize slide appearances
        selectedSlides.forEach(slideId => {{
            updateSlideAppearance(slideId, true);
        }});
    </script>
    """
    
    return render_slide_page("Slide Selector", "Select Slides", content)

@app.route('/slide-images/<path:filename>')
def slide_images(filename):
    """Serve slide images"""
    if not slide_selector_state['active']:
        return jsonify({'error': 'Slide selector not active'}), 400
    
    # Extract folder name and image filename
    parts = filename.split('/', 1)
    if len(parts) != 2:
        return jsonify({'error': 'Invalid image path'}), 400
    
    folder_name, image_filename = parts
    
    # Construct the full path
    base_folder_path = os.path.dirname(slide_selector_state['folder_path'])
    image_path = os.path.join(base_folder_path, folder_name, image_filename)
    
    # Security check
    if not os.path.exists(image_path) or not os.path.isfile(image_path):
        return jsonify({'error': 'Image not found'}), 404
    
    return send_file(image_path)

@app.route('/save-slide-selection', methods=['POST'])
def save_slide_selection():
    """Save the selected slides"""
    if not slide_selector_state['active']:
        return jsonify({'error': 'Slide selector not active'}), 400
    
    try:
        data = request.get_json()
        selected_ids = data.get('selected_ids', [])
        
        slides = slide_selector_state['slides']
        folder_path = slide_selector_state['folder_path']
        
        # Process the slides
        pruned_slides = process_slides(selected_ids, slides, folder_path)
        
        # Save the new slides.json
        slides_json_path = os.path.join(folder_path, 'slides.json')
        with open(slides_json_path, 'w') as f:
            json.dump(pruned_slides, f, indent=2)
        
        log_message(f"✅ Slide selection saved: {len(pruned_slides)} slides selected")
        
        return jsonify({
            'success': True,
            'selected_count': len(pruned_slides),
            'total_count': len(slides)
        })
        
    except Exception as e:
        app.logger.error(f"Error saving slide selection: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/extract-vocabulary-ajax', methods=['POST'])
def extract_vocabulary_ajax():
    """Extract vocabulary via AJAX"""
    if not slide_selector_state['active']:
        return jsonify({'error': 'Slide selector not active'}), 400
    
    try:
        data = request.get_json()
        model_id = data.get('model_id', 'bedrock/claude-4-sonnet')
        
        # Collect OCR text from all slides
        slides = slide_selector_state['slides']
        ocr_texts = []
        for slide in slides:
            if slide.get('ocr_text'):
                ocr_texts.append(slide['ocr_text'])
        
        combined_text = '\n'.join(ocr_texts)
        
        if not combined_text.strip():
            return jsonify({'error': 'No OCR text available'}), 400
        
        # Extract vocabulary
        vocabulary = extract_vocabulary(combined_text, model_id)
        
        return jsonify({
            'success': True,
            'vocabulary': vocabulary
        })
        
    except Exception as e:
        app.logger.error(f"Error extracting vocabulary: {e}")
        return jsonify({'error': str(e)}), 500

# Speaker Labeler Helper Functions
def parse_timestamp(ts_str):
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
        app.logger.error(f"Error parsing timestamp '{ts_str}': {e}")
        return 0

def load_transcript_for_labeling(transcript_path):
    """Load and parse transcript for speaker labeling."""
    global speaker_labeler_state
    
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            transcript_content = f.read()
    except Exception as e:
        app.logger.error(f"Error loading transcript: {e}")
        return False
    
    # Regex to match utterance headers like: **SPEAKER_09 [00:02.692]:**
    pattern = re.compile(r'\*\*(SPEAKER_\d{2}) \[([0-9:.]+)\]:\*\*')
    utterances = []
    for match in pattern.finditer(transcript_content):
        speaker_id = match.group(1)
        timestamp_str = match.group(2)
        start_ms = parse_timestamp(timestamp_str)
        
        utterances.append({
            "speaker_id": speaker_id,
            "timestamp_str": timestamp_str,
            "start_ms": start_ms,
            "match_start": match.start(),
            "match_end": match.end()
        })
    
    if not utterances:
        app.logger.error("No speaker utterances found in transcript")
        return False
    
    # Ensure utterances are in the order they appear in the transcript
    utterances.sort(key=lambda u: u["match_start"])
    
    # Set the end time for each utterance
    for i in range(len(utterances)):
        if i < len(utterances) - 1:
            utterances[i]["end_ms"] = utterances[i + 1]["start_ms"]
        else:
            utterances[i]["end_ms"] = utterances[i]["start_ms"] + 30000  # Default 30 seconds
    
    # Group utterances by speaker ID
    speaker_occurrences = {}
    for utt in utterances:
        speaker_id = utt["speaker_id"]
        if speaker_id not in speaker_occurrences:
            speaker_occurrences[speaker_id] = []
        speaker_occurrences[speaker_id].append(utt)
    
    # Create an ordered list of unique speaker IDs
    speaker_ids = sorted(speaker_occurrences.keys(), 
                        key=lambda spk: speaker_occurrences[spk][0]["start_ms"])
    
    # Choose segments for each speaker
    speaker_segments = {}
    for spk, occ_list in speaker_occurrences.items():
        speaker_segments[spk] = occ_list[:3]  # Use first 3 occurrences
    
    # Update global state
    speaker_labeler_state.update({
        'transcript_content': transcript_content,
        'utterances': utterances,
        'speaker_occurrences': speaker_occurrences,
        'speaker_segments': speaker_segments,
        'speaker_ids': speaker_ids,
        'speaker_mapping': {},
        'current_index': 0
    })
    
    return True

def update_transcript_with_labels():
    """Replace speaker headers with user-provided names."""
    updated_content = speaker_labeler_state['transcript_content']
    speaker_mapping = speaker_labeler_state['speaker_mapping']
    
    # Debug logging
    log_message(f"DEBUG: update_transcript_with_labels called with mapping: {speaker_mapping}")
    
    pattern = re.compile(r'\*\*(SPEAKER_\d{2})( \[[0-9:.]+\]:)\*\*')
    
    replacements_made = []
    
    def replace_func(match):
        speaker_id = match.group(1)
        timestamp_part = match.group(2)
        
        if speaker_id in speaker_mapping:
            new_name = speaker_mapping[speaker_id]
            replacement = f"**{new_name}{timestamp_part}**"
            replacements_made.append(f"{speaker_id} -> {new_name}")
            return replacement
        else:
            return match.group(0)  # No replacement
    
    updated_content = pattern.sub(replace_func, updated_content)
    
    # Debug logging
    log_message(f"DEBUG: Made {len(replacements_made)} replacements:")
    for replacement in replacements_made:
        log_message(f"DEBUG: {replacement}")
    
    return updated_content

def initialize_speaker_labeler(audio_path, transcript_path):
    """Initialize speaker labeler with audio and transcript."""
    try:
        if not os.path.exists(audio_path):
            app.logger.error(f"Audio file not found: {audio_path}")
            return False
            
        if not os.path.exists(transcript_path):
            app.logger.error(f"Transcript file not found: {transcript_path}")
            return False
        
        # Load audio file
        audio = AudioSegment.from_file(audio_path)
        speaker_labeler_state['audio_file'] = audio
        speaker_labeler_state['audio_duration_ms'] = len(audio)
        speaker_labeler_state['output_transcript_path'] = transcript_path.replace('.md', '_with_speakernames.md')
        
        # Load transcript
        if not load_transcript_for_labeling(transcript_path):
            return False
        
        speaker_labeler_state['active'] = True
        log_message(f"Speaker labeler initialized with {len(speaker_labeler_state['speaker_ids'])} speakers")
        return True
        
    except Exception as e:
        app.logger.error(f"Error initializing speaker labeler: {e}")
        return False

# Speaker Labeler Routes
@app.route('/label-speakers')
def label_speakers_index():
    """Main speaker labeling page"""
    if not speaker_labeler_state['active']:
        return render_slide_page(
            "Speaker Labeler - Error",
            "Speaker Labeler",
            "<div class='hpe-alert hpe-alert-danger'>Speaker labeler not initialized</div>"
        )
    
    speakers = speaker_labeler_state['speaker_ids']
    current_index = speaker_labeler_state['current_index']
    
    if current_index >= len(speakers):
        # All speakers labeled, show results
        return redirect(url_for('speaker_labeling_result'))
    
    current_speaker = speakers[current_index]
    segments = speaker_labeler_state['speaker_segments'][current_speaker]
    
    # Generate HTML for segments
    segments_html = ""
    for i, segment in enumerate(segments):
        segments_html += f"""
        <div class="speaker-segment">
            <h4>Sample {i+1}</h4>
            <p><strong>Timestamp:</strong> {segment['timestamp_str']}</p>
            <audio controls>
                <source src="/play-speaker-audio/{current_speaker}?segment={i}" type="audio/mpeg">
                Your browser does not support the audio element.
            </audio>
        </div>
        """
    
    content = f"""
    <div class="speaker-labeler-container">
        <div class="progress-info">
            <h3>Speaker {current_index + 1} of {len(speakers)}</h3>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {(current_index / len(speakers)) * 100}%"></div>
            </div>
        </div>
        
        <div class="speaker-info">
            <h2>Label Speaker: {current_speaker}</h2>
            <p>Listen to the audio samples below and enter a name for this speaker.</p>
        </div>
        
        <div class="audio-samples">
            {segments_html}
        </div>
        
        <form id="speaker-form" class="speaker-form">
            <div class="form-group">
                <label for="speaker-name">Speaker Name:</label>
                <input type="text" id="speaker-name" name="speaker_name" 
                       placeholder="Enter speaker name (e.g., John Smith)" required>
            </div>
            <div class="form-buttons">
                <button type="button" id="skip-speaker" class="hpe-btn hpe-btn-secondary">
                    Skip This Speaker
                </button>
                <button type="submit" class="hpe-btn hpe-btn-primary">
                    Save & Continue
                </button>
            </div>
        </form>
    </div>
    
    <style>
        .speaker-labeler-container {{ max-width: 800px; margin: 0 auto; }}
        .progress-info {{ margin-bottom: 2rem; }}
        .progress-bar {{ width: 100%; height: 10px; background: #eee; border-radius: 5px; }}
        .progress-fill {{ height: 100%; background: #007cba; border-radius: 5px; transition: width 0.3s; }}
        .speaker-info {{ margin-bottom: 2rem; }}
        .audio-samples {{ margin-bottom: 2rem; }}
        .speaker-segment {{ margin-bottom: 1rem; padding: 1rem; border: 1px solid #ddd; border-radius: 5px; }}
        .speaker-form {{ padding: 2rem; background: #f9f9f9; border-radius: 8px; }}
        .form-group {{ margin-bottom: 1rem; }}
        .form-group label {{ display: block; margin-bottom: 0.5rem; font-weight: bold; }}
        .form-group input {{ width: 100%; padding: 0.75rem; border: 1px solid #ddd; border-radius: 4px; }}
        .form-buttons {{ display: flex; gap: 1rem; justify-content: flex-end; }}
    </style>
    
    <script>
        document.getElementById('speaker-form').addEventListener('submit', function(e) {{
            e.preventDefault();
            
            const speakerName = document.getElementById('speaker-name').value.trim();
            if (!speakerName) {{
                alert('Please enter a speaker name');
                return;
            }}
            
            labelSpeaker(speakerName);
        }});
        
        document.getElementById('skip-speaker').addEventListener('click', function() {{
            labelSpeaker(''); // Empty name means skip
        }});
        
        function labelSpeaker(name) {{
            fetch('/label-speaker', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{
                    speaker_id: '{current_speaker}',
                    speaker_name: name
                }})
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    if (data.completed) {{
                        window.location.href = '/speaker-labeling-result';
                    }} else {{
                        window.location.reload(); // Reload to show next speaker
                    }}
                }} else {{
                    alert('Error: ' + data.error);
                }}
            }})
            .catch(error => {{
                alert('Error: ' + error.message);
            }});
        }}
    </script>
    """
    
    return render_slide_page("Speaker Labeler", "Label Speakers", content)

@app.route('/play-speaker-audio/<speaker_id>')
def play_speaker_audio(speaker_id):
    """Generate and serve audio segment for a speaker"""
    if not speaker_labeler_state['active']:
        return jsonify({'error': 'Speaker labeler not active'}), 400
    
    segment_index = int(request.args.get('segment', 0))
    
    try:
        segments = speaker_labeler_state['speaker_segments'][speaker_id]
        if segment_index >= len(segments):
            return jsonify({'error': 'Invalid segment index'}), 400
            
        segment = segments[segment_index]
        audio = speaker_labeler_state['audio_file']
        
        # Extract audio segment with some padding
        start_ms = max(0, segment['start_ms'] - 500)  # 0.5s before
        end_ms = min(len(audio), segment['end_ms'] + 500)  # 0.5s after
        
        audio_segment = audio[start_ms:end_ms]
        
        # Export to temporary file
        temp_path = f"/tmp/speaker_{speaker_id}_segment_{segment_index}.mp3"
        audio_segment.export(temp_path, format="mp3")
        
        return send_file(temp_path, mimetype="audio/mpeg")
        
    except Exception as e:
        app.logger.error(f"Error serving speaker audio: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/label-speaker', methods=['POST'])
def label_speaker():
    """Label a speaker and move to the next one"""
    if not speaker_labeler_state['active']:
        return jsonify({'error': 'Speaker labeler not active'}), 400
    
    try:
        data = request.get_json()
        speaker_id = data.get('speaker_id')
        speaker_name = data.get('speaker_name', '').strip();
        
        # Update speaker mapping
        if speaker_name:
            speaker_labeler_state['speaker_mapping'][speaker_id] = speaker_name
            log_message(f"Labeled {speaker_id} as '{speaker_name}'")
        else:
            log_message(f"Skipped labeling for {speaker_id}")
        
        # Move to next speaker
        speaker_labeler_state['current_index'] += 1
        speakers = speaker_labeler_state['speaker_ids']
        
        completed = speaker_labeler_state['current_index'] >= len(speakers)
        
        if completed:
            # Generate updated transcript
            updated_transcript = update_transcript_with_labels()
            output_path = speaker_labeler_state['output_transcript_path']
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(updated_transcript)
            
            log_message(f"✅ Speaker labeling completed. Updated transcript saved to: {output_path}")
            speaker_labeler_state['active'] = False
        
        return jsonify({
            'success': True,
            'completed': completed,
            'current_index': speaker_labeler_state['current_index'],
            'total_speakers': len(speakers)
        })
        
    except Exception as e:
        app.logger.error(f"Error labeling speaker: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/speaker-labeling-result')
def speaker_labeling_result():
    """Show speaker labeling results"""
    mapping = speaker_labeler_state['speaker_mapping']
    output_path = speaker_labeler_state['output_transcript_path']
    
    # Generate summary
    mapping_html = ""
    for speaker_id, name in mapping.items():
        mapping_html += f"<li><strong>{speaker_id}</strong> → {name}</li>"
    
    if not mapping_html:
        mapping_html = "<li>No speakers were labeled</li>"
    
    content = f"""
    <div class="results-container">
        <div class="hpe-alert hpe-alert-success">
            <h3>✅ Speaker Labeling Completed!</h3>
        </div>
        
        <div class="results-summary">
            <h4>Speaker Mappings:</h4>
            <ul>
                {mapping_html}
            </ul>
        </div>
        
        <div class="results-actions">
            <p><strong>Updated transcript saved to:</strong> {output_path}</p>
            <button onclick="window.close()" class="hpe-btn hpe-btn-primary">
                Close Window
            </button>
        </div>
    </div>
    
    <style>
        .results-container {{ max-width: 600px; margin: 0 auto; }}
        .results-summary {{ margin: 2rem 0; }}
        .results-summary ul {{ background: #f9f9f9; padding: 1rem; border-radius: 5px; }}
        .results-actions {{ text-align: center; }}
    </style>
    """
    
    return render_slide_page("Speaker Labeling Results", "Results", content)

@app.route('/debug/files')
def debug_files():
    """Debug endpoint to list files in various directories"""
    info = {}
    
    # Upload folder
    if os.path.exists(app.config['UPLOAD_FOLDER']):
        info['upload_folder'] = {
            'path': app.config['UPLOAD_FOLDER'],
            'files': os.listdir(app.config['UPLOAD_FOLDER'])
        }
    
    # Workflow output directory
    if workflow_state.get('output_dir') and os.path.exists(workflow_state['output_dir']):
        info['output_dir'] = {
            'path': workflow_state['output_dir'],
            'files': []
        }
        for root, dirs, files in os.walk(workflow_state['output_dir']):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), workflow_state['output_dir'])
                info['output_dir']['files'].append(rel_path)
    
    return jsonify(info)

# Static files route for CSS
@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

@app.route('/save-vocabulary', methods=['POST'])
def save_vocabulary():
    """Save vocabulary to vocabulary.txt file"""
    if not slide_selector_state['active']:
        return jsonify({'error': 'Slide selector not active'}), 400
    
    try:
        data = request.get_json()
        vocabulary_text = data.get('vocabulary', '').strip()
        
        if not vocabulary_text:
            return jsonify({'error': 'No vocabulary text provided'}), 400
        
        # Save to vocabulary.txt in the slides folder
        folder_path = slide_selector_state['folder_path']
        vocab_file_path = os.path.join(folder_path, 'vocabulary.txt')
        
        with open(vocab_file_path, 'w', encoding='utf-8') as f:
            f.write(vocabulary_text)
        
        log_message(f"✅ Vocabulary saved to: {vocab_file_path}")
        
        return jsonify({
            'success': True,
            'file_path': vocab_file_path
        })
        
    except Exception as e:
        app.logger.error(f"Error saving vocabulary: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Set up logging
    logging.basicConfig(level=logging.INFO)

    logging.info("🚀 Starting Video2Notes Web Application (Integrated Architecture)")
    logging.info(f"📝 Access the application at: http://0.0.0.0:{MAIN_APP_PORT}")
    logging.info("🔧 Slide selector and speaker labeler are now integrated into the main app")
    
    # Create static directory if it doesn't exist
    os.makedirs('static/css', exist_ok=True)

    app.run(host='0.0.0.0', port=MAIN_APP_PORT, debug=False, threaded=True)