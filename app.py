import os
import subprocess
import threading
import time
import json
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

MAIN_APP_PORT = os.getenv('MAIN_APP_PORT', 5001)

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
                ["python", "00-split-video.py", video_path, params['timestamp_file']],
                "Splitting video"
            ):
                raise Exception("Video splitting failed")
        
        # Step 1: Preprocess
        workflow_state['current_step'] = 'Preprocessing video'
        workflow_state['progress'] = 15
        
        preprocess_cmd = [
            "python", "01-preprocess.py",
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
            ["python", "02-extract-slides.py", 
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
        
        audio_path = os.path.join(output_dir, f"{video_name}.m4a")
        workflow_state['audio_path'] = audio_path
        transcript_dir = os.path.join(output_dir, "transcript")
        os.makedirs(transcript_dir, exist_ok=True)
        
        if not execute_command(
            ["python", "03-transcribe.py",
             "-a", audio_path,
             "-s", slides_dir,
             "-o", transcript_dir,
             "-f", "json"],
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
            ["python", "04-generate-notes.py",
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
            
            if not execute_command(
                ["python", "06-refine-notes.py",
                 "-i", notes_for_refinement,
                 "-o", output_dir],
                "Refining notes"
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
    path = request.args.get('path', os.path.expanduser('~'))
    
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
    # Try user home directory first, then fall back to upload folder
    home_dir = os.path.expanduser('~')
    if is_safe_path(home_dir) and os.path.exists(home_dir):
        return jsonify({'path': home_dir})
    else:
        return jsonify({'path': app.config['UPLOAD_FOLDER']})

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
    
    params = {
        'video_path': video_path,
        'do_split': request.form.get('do_split') == 'on',
        'timestamp_file': request.form.get('timestamp_file', '').strip(),
        'extract_audio': request.form.get('extract_audio', 'on') == 'on',
        'skip_roi': request.form.get('skip_roi', 'on') == 'on',
        'roi_timestamp': request.form.get('roi_timestamp', '').strip(),
        'do_label_speakers': request.form.get('do_label_speakers', 'on') == 'on',
        'do_refine_notes': request.form.get('do_refine_notes') == 'on'
    }
    
    # Debug logging
    app.logger.info(f"Input method: '{input_method}'")
    app.logger.info(f"Final video_path: '{params['video_path']}'")
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
        
        # Notes file
        if workflow_state.get('notes_path'):
            notes_filename = os.path.basename(workflow_state['notes_path'])
            if os.path.exists(workflow_state['notes_path']):
                available_files.append({
                    'name': 'Notes',
                    'filename': notes_filename,
                    'icon': '📄',
                    'description': 'Generated notes from video'
                })
        
        # Speaker-labeled notes (if exists)
        if workflow_state.get('notes_path'):
            speaker_notes_path = workflow_state['notes_path'].replace('.md', '_with_speakernames.md')
            speaker_notes_filename = os.path.basename(speaker_notes_path)
            if os.path.exists(speaker_notes_path):
                available_files.append({
                    'name': 'Notes with Speaker Names',
                    'filename': speaker_notes_filename,
                    'icon': '🎤',
                    'description': 'Notes with labeled speakers'
                })
        
        # Transcript JSON
        if workflow_state.get('video_name'):
            transcript_path = os.path.join(workflow_state['output_dir'], 'transcript', f"{workflow_state['video_name']}.json")
            if os.path.exists(transcript_path):
                # For download, we need relative path from output_dir
                available_files.append({
                    'name': 'Transcript JSON',
                    'filename': f"transcript/{workflow_state['video_name']}.json",
                    'icon': '📝',
                    'description': 'Detailed transcript with timestamps'
                })
        
        # Audio file
        if workflow_state.get('audio_path') and os.path.exists(workflow_state['audio_path']):
            audio_filename = os.path.basename(workflow_state['audio_path'])
            available_files.append({
                'name': 'Extracted Audio',
                'filename': audio_filename,
                'icon': '🔊',
                'description': 'Audio extracted from video'
            })
        
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
        
        status_data['available_files'] = available_files
    
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
            pruned.append({
                "group_id": slide.get("group_id"),
                "timestamp": slide.get("timestamp"),
                "image_path": slide.get("image_path"),
                "ocr_text": slide.get("ocr_text")
            })
                
    return pruned

# Slide Selector Routes
@app.route('/select-slides')
def select_slides_index():
    """Slide selector main page"""
    if not slide_selector_state['active'] or not slide_selector_state['slides']:
        return render_slide_page("Error", "Slide Selector", 
                                '<div class="hpe-alert hpe-alert-danger"><p>Slide selector is not active or no slides available.</p></div>')
    
    slides = slide_selector_state['slides']
    folder_path = slide_selector_state['folder_path']
    
    # Build HTML for each slide item
    slides_html = []
    for slide in slides:
        image_url = url_for('slide_images', filename=slide["relative_path"])
        slide_html = f"""
        <div class="hpe-slide">
            <img src="{image_url}" alt="Slide {slide['group_id']}" style="max-width: 600px;">
            <div class="hpe-slide-checkbox">
                <input type="checkbox" id="slide_{slide['group_id']}" name="slides" value="{slide['group_id']}" checked>
                <label for="slide_{slide['group_id']}">Slide {slide['group_id']}</label>
            </div>
        </div>
        """
        slides_html.append(slide_html)
    
    # Form content
    form_content = f"""
    <div class="hpe-card">
        <div class="hpe-card-header">
            <h3 class="hpe-card-title">🖼️ Select Slides</h3>
        </div>
        <form action="{url_for('save_slide_selection')}" method="post">
            {''.join(slides_html)}
            <div class="hpe-mt-5">
                <button type="submit" class="hpe-btn hpe-btn-primary hpe-btn-lg">💾 Save Selection</button>
            </div>
        </form>
    </div>
    
    <div class="vocabulary-section">
        <h3 class="hpe-card-title">🔤 Extract Vocabulary</h3>
        <p class="hpe-mb-4">Extract domain-specific vocabulary from selected slides to improve transcription accuracy.</p>
        
        <div class="vocabulary-controls">
            <label for="model" class="hpe-label">Model:</label>
            <select id="model" class="hpe-select" style="max-width: 300px;">
                <option value="bedrock/claude-4-sonnet">Claude 4 Sonnet</option>
                <option value="openai/gpt-4o">GPT-4o</option>
            </select>
            <button type="button" class="hpe-btn hpe-btn-secondary" onclick="extractVocabulary()">🔤 Extract Vocabulary</button>
        </div>
        
        <div id="vocabulary-result" class="vocabulary-result hpe-hidden">
            <h4 class="hpe-mb-3">📝 Extracted Vocabulary:</h4>
            <div id="vocabulary-content" class="vocabulary-content"></div>
            <div id="vocabulary-status" class="vocabulary-status"></div>
        </div>
    </div>
    
    <script>
    function getSelectedSlides() {{
        const checkboxes = document.querySelectorAll('input[name="slides"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    }}
    
    function extractVocabulary() {{
        const selectedSlides = getSelectedSlides();
        const model = document.getElementById('model').value;
        
        if (selectedSlides.length === 0) {{
            alert('Please select at least one slide before extracting vocabulary.');
            return;
        }}
        
        // Show loading state
        const resultDiv = document.getElementById('vocabulary-result');
        const contentDiv = document.getElementById('vocabulary-content');
        const statusDiv = document.getElementById('vocabulary-status');
        
        resultDiv.classList.remove('hpe-hidden');
        contentDiv.innerHTML = '<div class="hpe-spinner"></div> Extracting vocabulary...';
        statusDiv.innerHTML = '';
        
        // Make AJAX request
        fetch('{url_for('extract_vocabulary_ajax')}', {{
            method: 'POST',
            headers: {{
                'Content-Type': 'application/json',
            }},
            body: JSON.stringify({{
                model: model,
                selected_slides: selectedSlides
            }})
        }})
        .then(response => response.json())
        .then(data => {{
            if (data.success) {{
                contentDiv.textContent = data.vocabulary;
                statusDiv.innerHTML = '<span style="color: var(--hpe-success);">✅ ' + data.message + '</span>';
            }} else {{
                contentDiv.textContent = 'Error: ' + data.error;
                statusDiv.innerHTML = '<span style="color: var(--hpe-danger);">❌ Failed to extract vocabulary</span>';
            }}
        }})
        .catch(error => {{
            contentDiv.textContent = 'Error: ' + error;
            statusDiv.innerHTML = '<span style="color: var(--hpe-danger);">❌ Network error</span>';
        }});
    }}
    </script>
    """
    
    return render_slide_page("Slide Selector", "Video2Notes - Slide Selector", form_content)

@app.route('/slide-images/<path:filename>')
def slide_images(filename):
    """Serve slide images"""
    if not slide_selector_state['active']:
        return "Slide selector not active", 404
    return send_from_directory(slide_selector_state['folder_path'], filename)

@app.route('/save-slide-selection', methods=['POST'])
def save_slide_selection():
    """Save selected slides"""
    selected_ids = request.form.getlist('slides')
    selected_ids = [int(id) for id in selected_ids]
    
    slides = slide_selector_state['slides']
    folder_path = slide_selector_state['folder_path']
    
    pruned = process_slides(selected_ids, slides, folder_path)
    
    # Save pruned slides as the new slides.json
    json_path = os.path.join(folder_path, "slides.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(pruned, f, indent=4)
    
    # Deactivate slide selector
    slide_selector_state['active'] = False
    
    success_content = f"""
    <div class="hpe-alert hpe-alert-success hpe-text-center">
        <h3>🎉 Selection Saved Successfully!</h3>
        <p><strong>{len(pruned)} slides</strong> have been selected and saved.</p>
        <p>You can now close this tab and return to the main workflow.</p>
        <a href="/" class="hpe-btn hpe-btn-primary hpe-mt-4">🔄 Process Another Video</a>
    </div>
    """
    
    return render_slide_page("Selection Saved", "Video2Notes - Slide Selector", success_content)

@app.route('/extract-vocabulary-ajax', methods=['POST'])
def extract_vocabulary_ajax():
    """Extract vocabulary from selected slides via AJAX"""
    try:
        data = request.get_json()
        model = data.get('model', 'bedrock/claude-4-sonnet')
        selected_slide_ids = data.get('selected_slides', [])
        
        if not selected_slide_ids:
            return jsonify({'success': False, 'error': 'No slides selected'})
        
        slides = slide_selector_state['slides']
        folder_path = slide_selector_state['folder_path']
        
        # Filter slides to only selected ones
        selected_slides = [slide for slide in slides if str(slide['group_id']) in selected_slide_ids]
        
        if not selected_slides:
            return jsonify({'success': False, 'error': 'Selected slides not found'})
        
        # Extract text from selected slides only
        concatenated_texts = [slide.get("ocr_text", "") for slide in selected_slides]
        all_text = "\n".join(concatenated_texts)
        
        if not all_text.strip():
            return jsonify({'success': False, 'error': 'No text found in selected slides'})
        
        # Extract vocabulary
        vocabulary = extract_vocabulary(all_text, model)
        
        # Write vocabulary to file
        vocabulary_file = os.path.join(folder_path, "vocabulary.txt")
        with open(vocabulary_file, 'w', encoding='utf-8') as f:
            f.write(f"Vocabulary extracted from {len(selected_slides)} selected slides using {model}\n")
            f.write("=" * 60 + "\n\n")
            f.write(vocabulary)
        
        success_message = f"Vocabulary saved to vocabulary.txt ({len(selected_slides)} slides, {model})"
        
        return jsonify({
            'success': True,
            'vocabulary': vocabulary,
            'message': success_message,
            'file_path': vocabulary_file
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

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
        with open(json_path, "r", encoding="utf-8") as f:
            slides = json.load(f)
    except Exception as e:
        log_message(f"Error loading slides.json: {e}")
        return False
        
    # Update each slide with a relative image path
    folder_basename = os.path.basename(folder_path)
    for slide in slides:
        prefix = folder_basename + os.sep
        if slide["image_path"].startswith(prefix):
            slide["relative_path"] = slide["image_path"][len(prefix):]
        else:
            slide["relative_path"] = slide["image_path"]
    
    # Set global state
    slide_selector_state['folder_path'] = folder_path
    slide_selector_state['slides'] = slides
    slide_selector_state['active'] = True
    
    log_message(f"Slide selector initialized with {len(slides)} slides")
    return True

# Speaker Labeler Helper Functions
def parse_timestamp(ts_str):
    """Convert a timestamp string to milliseconds."""
    try:
        parts = ts_str.split(':')
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return int((minutes * 60 + seconds) * 1000)
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return int((hours * 3600 + minutes * 60 + seconds) * 1000)
        else:
            raise ValueError("Invalid timestamp format: " + ts_str)
    except Exception as e:
        raise ValueError(f"Error parsing timestamp '{ts_str}': {e}")

def load_transcript_for_labeling(transcript_path):
    """Load and parse transcript for speaker labeling."""
    global speaker_labeler_state
    
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            transcript_content = f.read()
    except Exception as e:
        log_message(f"Error reading transcript file: {e}")
        return False
    
    # Regex to match utterance headers like: **SPEAKER_09 [00:02.692]:**
    pattern = re.compile(r'\*\*(SPEAKER_\d{2}) \[([0-9:.]+)\]:\*\*')
    utterances = []
    for match in pattern.finditer(transcript_content):
        speaker = match.group(1)
        timestamp_str = match.group(2)
        try:
            start_ms = parse_timestamp(timestamp_str)
        except ValueError as e:
            log_message(f"Error parsing timestamp: {e}")
            continue
        utterances.append({
            "speaker": speaker,
            "timestamp_str": timestamp_str,
            "start_ms": start_ms,
            "header_text": match.group(0),
            "match_start": match.start(),
            "match_end": match.end()
        })
    
    if not utterances:
        log_message("No utterances found in transcript.")
        return False
    
    # Ensure utterances are in the order they appear in the transcript
    utterances.sort(key=lambda u: u["match_start"])
    
    # Set the end time for each utterance
    for i in range(len(utterances)):
        if i < len(utterances) - 1:
            utterances[i]["end_ms"] = utterances[i+1]["start_ms"]
        else:
            utterances[i]["end_ms"] = speaker_labeler_state['audio_duration_ms']
    
    # Group utterances by speaker ID
    speaker_occurrences = {}
    for utt in utterances:
        spk = utt["speaker"]
        if spk not in speaker_occurrences:
            speaker_occurrences[spk] = []
        speaker_occurrences[spk].append(utt)
    
    # Create an ordered list of unique speaker IDs
    speaker_ids = sorted(speaker_occurrences.keys(), 
                        key=lambda spk: speaker_occurrences[spk][0]["start_ms"])
    
    # Choose segments for each speaker
    speaker_segments = {}
    for spk, occ_list in speaker_occurrences.items():
        first_utt = occ_list[0]
        duration_first = first_utt["end_ms"] - first_utt["start_ms"]
        chosen = first_utt
        if duration_first < 5000 and len(occ_list) > 1:
            second_utt = occ_list[1]
            duration_second = second_utt["end_ms"] - second_utt["start_ms"]
            chosen = first_utt if duration_first >= duration_second else second_utt
        speaker_segments[spk] = (chosen["start_ms"], chosen["end_ms"])
    
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
        spk = match.group(1)
        rest = match.group(2)
        label = speaker_mapping.get(spk, spk)
        
        if label != spk:
            formatted_label = f"SPEAKER - {label}"
            replacements_made.append(f"{spk} -> SPEAKER - {label}")
        else:
            formatted_label = label
            replacements_made.append(f"{spk} -> {label} (unchanged)")
            
        return f'**{formatted_label}{rest}**'
    
    updated_content = pattern.sub(replace_func, updated_content)
    
    # Debug logging
    log_message(f"DEBUG: Made {len(replacements_made)} replacements:")
    for replacement in replacements_made:
        log_message(f"DEBUG:   {replacement}")
    
    return updated_content

def initialize_speaker_labeler(audio_path, transcript_path):
    """Initialize speaker labeler with audio and transcript."""
    try:
        # Load audio file
        audio = AudioSegment.from_file(audio_path)
        audio_duration_ms = len(audio)
        
        # Update global state
        speaker_labeler_state.update({
            'audio_file': audio,
            'audio_duration_ms': audio_duration_ms,
            'output_transcript_path': transcript_path.replace(".md", "_with_speakernames.md"),
            'active': True
        })
        
        # Load and parse transcript
        if load_transcript_for_labeling(transcript_path):
            log_message(f"Speaker labeler initialized with {len(speaker_labeler_state['speaker_ids'])} speakers")
            return True
        else:
            return False
            
    except Exception as e:
        log_message(f"Error initializing speaker labeler: {e}")
        return False

# Speaker Labeler Routes
@app.route('/label-speakers')
def label_speakers_index():
    """Speaker labeling main page"""
    if not speaker_labeler_state['active'] or not speaker_labeler_state['speaker_ids']:
        error_content = """
        <div class="hpe-alert hpe-alert-danger hpe-text-center">
            <h3>❌ Speaker Labeling Not Available</h3>
            <p>Speaker labeler is not active or no speakers found.</p>
            <a href="/" class="hpe-btn hpe-btn-primary hpe-mt-4">🏠 Return to Main Page</a>
        </div>
        """
        return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Speaker Labeling</title>
            <link rel="stylesheet" href="/static/css/hpe-design.css">
        </head>
        <body class="hpe-page-wrapper">
            <div class="hpe-container">
                <div class="hpe-header">
                    <h1>🎤 Speaker Labeling</h1>
                </div>
                """ + error_content + """
            </div>
        </body>
        </html>
        """)
    
    current_index = speaker_labeler_state['current_index']
    speaker_ids = speaker_labeler_state['speaker_ids']
    
    if current_index >= len(speaker_ids):
        return redirect(url_for('speaker_labeling_result'))
    
    current_speaker = speaker_ids[current_index]
    
    html = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Speaker Labeling</title>
        <link rel="stylesheet" href="/static/css/hpe-design.css">
        <style>
            .speaker-audio {{
                width: 100%;
                margin: var(--hpe-space-5) 0;
            }}
            
            .speaker-form {{
                margin-top: var(--hpe-space-5);
            }}
            
            .progress-info {{
                background: var(--hpe-gray-100);
                padding: var(--hpe-space-4);
                border-radius: var(--hpe-radius-md);
                margin-bottom: var(--hpe-space-5);
                text-align: center;
            }}
        </style>
    </head>
    <body class="hpe-page-wrapper">
        <div class="hpe-container">
            <div class="hpe-header">
                <h1>🎤 Speaker Labeling</h1>
                <p>Assign names to speakers in your transcript</p>
            </div>
            
            <div class="progress-info">
                <h3 class="hpe-mb-2">Speaker {current_index + 1} of {len(speaker_ids)}</h3>
                <div class="hpe-progress">
                    <div class="hpe-progress-bar" style="width: {((current_index) / len(speaker_ids)) * 100}%"></div>
                </div>
                <p class="hpe-mt-2">{current_index} of {len(speaker_ids)} speakers labeled</p>
            </div>
            
            <div class="hpe-card">
                <div class="hpe-card-header">
                    <h3 class="hpe-card-title">Current Speaker: {current_speaker}</h3>
                </div>
                
                <div class="hpe-alert hpe-alert-info">
                    <p><strong>Instructions:</strong> Listen to the audio clip and enter a name for this speaker. Leave blank to keep the original speaker ID.</p>
                </div>
                
                <audio controls autoplay class="speaker-audio">
                    <source src="{url_for('play_speaker_audio', speaker_id=current_speaker)}" type="audio/wav">
                    Your browser does not support the audio element.
                </audio>
                
                <form action="{url_for('label_speaker')}" method="post" class="speaker-form">
                    <input type="hidden" name="speaker_id" value="{current_speaker}">
                    
                    <div class="hpe-form-group">
                        <label for="label" class="hpe-label">Enter Speaker Name (optional):</label>
                        <input type="text" id="label" name="label" 
                               placeholder="e.g., John, Alice, or leave blank for {current_speaker}"
                               class="hpe-input">
                        <div class="help-text">Enter a human-readable name for this speaker, or leave blank to keep the original ID.</div>
                    </div>
                    
                    <button type="submit" class="hpe-btn hpe-btn-primary hpe-btn-lg">
                        ➡️ {('Complete Labeling' if current_index >= len(speaker_ids) - 1 else 'Next Speaker')}
                    </button>
                </form>
            </div>
        </div>
    </body>
    </html>
    '''
    return html

@app.route('/play-speaker-audio/<speaker_id>')
def play_speaker_audio(speaker_id):
    """Serve audio segment for a specific speaker"""
    if not speaker_labeler_state['active'] or speaker_id not in speaker_labeler_state['speaker_segments']:
        return "Speaker not found", 404
    
    audio = speaker_labeler_state['audio_file']
    start_ms, end_ms = speaker_labeler_state['speaker_segments'][speaker_id]
    
    # Extract audio segment
    segment = audio[start_ms:end_ms]
    
    # Convert to WAV and serve
    buffer = io.BytesIO()
    segment.export(buffer, format="wav")
    buffer.seek(0)
    
    return send_file(buffer, mimetype="audio/wav", as_attachment=False)

@app.route('/label-speaker', methods=['POST'])
def label_speaker():
    """Process speaker label submission"""
    speaker_id = request.form.get('speaker_id')
    label = request.form.get('label', '').strip()
    
    # Debug logging
    log_message(f"DEBUG: Received speaker_id: '{speaker_id}'")
    log_message(f"DEBUG: Received label: '{label}'")
    log_message(f"DEBUG: Current speaker_mapping before update: {speaker_labeler_state['speaker_mapping']}")
    
    if label:
        speaker_labeler_state['speaker_mapping'][speaker_id] = label
        log_message(f"Speaker {speaker_id} labeled as: {label}")
    else:
        log_message(f"Speaker {speaker_id} kept original name")
    
    # Debug logging after update
    log_message(f"DEBUG: Current speaker_mapping after update: {speaker_labeler_state['speaker_mapping']}")
    
    # Move to next speaker
    speaker_labeler_state['current_index'] += 1
    
    return redirect(url_for('label_speakers_index'))

@app.route('/speaker-labeling-result')
def speaker_labeling_result():
    """Show speaker labeling completion page"""
    speaker_mapping = speaker_labeler_state['speaker_mapping']
    
    # Debug logging
    log_message(f"DEBUG: Final speaker_mapping: {speaker_mapping}")
    log_message(f"DEBUG: Available speaker_ids: {speaker_labeler_state['speaker_ids']}")
    
    # Generate updated transcript
    updated_transcript = update_transcript_with_labels()
    
    # Save updated transcript
    output_path = speaker_labeler_state['output_transcript_path']
    log_message(f"DEBUG: Saving updated transcript to: {output_path}")
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(updated_transcript)
        save_message = f"Updated transcript saved to: {output_path}"
        save_status = "success"
        log_message(f"DEBUG: Successfully saved transcript with {len(updated_transcript)} characters")
    except Exception as e:
        save_message = f"Error saving transcript: {e}"
        save_status = "danger"
        log_message(f"DEBUG: Error saving transcript: {e}")
    
    # Deactivate speaker labeler
    speaker_labeler_state['active'] = False
    
    # Build mapping display
    mapping_items = ""
    for speaker_id in speaker_labeler_state['speaker_ids']:
        label = speaker_mapping.get(speaker_id, speaker_id)
        mapping_items += f'<li><strong>{speaker_id}</strong> → <em>{label}</em></li>'
    
    html = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Speaker Labeling Complete</title>
        <link rel="stylesheet" href="/static/css/hpe-design.css">
    </head>
    <body class="hpe-page-wrapper">
        <div class="hpe-container">
            <div class="hpe-header">
                <h1>🎉 Speaker Labeling Complete!</h1>
                <p>All speakers have been successfully labeled</p>
            </div>
            
            <div class="hpe-alert hpe-alert-{save_status}">
                <p>{save_message}</p>
            </div>
            
            <div class="hpe-card">
                <div class="hpe-card-header">
                    <h3 class="hpe-card-title">📋 Speaker Mappings</h3>
                </div>
                <ul class="hpe-mb-0">
                    {mapping_items}
                </ul>
            </div>
            
            <div class="hpe-text-center hpe-mt-6">
                <p class="hpe-mb-4">You can now close this tab and return to the main workflow.</p>
                <a href="/" class="hpe-btn hpe-btn-primary hpe-btn-lg">🏠 Return to Main Page</a>
            </div>
        </div>
    </body>
    </html>
    '''
    
    return html

@app.route('/debug/files')
def debug_files():
    """Debug endpoint to list available files for download"""
    if not workflow_state['output_dir'] or not os.path.exists(workflow_state['output_dir']):
        return jsonify({'error': 'No output directory available'})
    
    try:
        files_info = []
        for root, dirs, files in os.walk(workflow_state['output_dir']):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, workflow_state['output_dir'])
                file_size = os.path.getsize(full_path)
                files_info.append({
                    'relative_path': rel_path,
                    'full_path': full_path,
                    'size_bytes': file_size,
                    'size_mb': round(file_size / (1024 * 1024), 2),
                    'exists': os.path.exists(full_path)
                })
        
        return jsonify({
            'output_dir': workflow_state['output_dir'],
            'video_name': workflow_state.get('video_name', 'Unknown'),
            'notes_path': workflow_state.get('notes_path', 'Not set'),
            'audio_path': workflow_state.get('audio_path', 'Not set'),
            'slides_dir': workflow_state.get('slides_dir', 'Not set'),
            'total_files': len(files_info),
            'files': files_info
        })
    except Exception as e:
        return jsonify({'error': f'Error listing files: {str(e)}'})

# Static files route for CSS
@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve static files (CSS, JS, etc.)"""
    return send_from_directory('static', filename)

if __name__ == '__main__':
    # Set up logging
    logging.basicConfig(level=logging.INFO)

    logging.info("🚀 Starting Video2Notes Web Application (Integrated Architecture)")
    logging.info(f"📝 Access the application at: http://0.0.0.0:{MAIN_APP_PORT}")
    logging.info("🔧 Slide selector and speaker labeler are now integrated into the main app")
    

    app.run(host='0.0.0.0', port=MAIN_APP_PORT, debug=False, threaded=True)