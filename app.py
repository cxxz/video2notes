import os
import subprocess
import threading
import time
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file, Response
from werkzeug.utils import secure_filename
import logging
from dotenv import load_dotenv
load_dotenv()

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
SLIDE_SELECTOR_PORT = os.getenv('SLIDE_SELECTOR_PORT', 5002)
SPEAKER_LABELER_PORT = os.getenv('SPEAKER_LABELER_PORT', 5006)

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

def check_service_availability(host, port, timeout=5):
    """Check if a service is available on the given host and port"""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
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
        
        # Set environment variables for slide selector host/port
        env = os.environ.copy()
        env['SLIDE_SELECTOR_HOST'] = '0.0.0.0'  # Bind to all interfaces for remote access
        env['SLIDE_SELECTOR_PORT'] = str(SLIDE_SELECTOR_PORT)
        
        if not execute_command_with_env(
            ["python", "02-extract-slides.py", 
             "-i", video_path,
             "-j", rois_path,
             "-o", slides_dir,
             "--select"],
            "Extracting slides",
            env
        ):
            raise Exception("Slide extraction failed")
        
        # Wait for slide selection
        workflow_state['interactive_stage'] = 'slides'
        workflow_state['interactive_ready'] = True
        log_message("🖱️ Slide selection interface is ready")
        log_message("Please use the 'Open Slide Selector' button to select slides")
        
        # Check if slide selector is actually accessible
        slide_selector_host = 'localhost' if LOCAL_SERVER == 'true' else '0.0.0.0'
        max_wait_time = 30  # Wait up to 30 seconds for service to be ready
        wait_time = 0
        
        while wait_time < max_wait_time:
            if check_service_availability('localhost', int(SLIDE_SELECTOR_PORT)):
                log_message(f"✅ Slide selector is accessible on port {SLIDE_SELECTOR_PORT}")
                break
            else:
                log_message(f"⏳ Waiting for slide selector to be ready on port {SLIDE_SELECTOR_PORT}...")
                time.sleep(2)
                wait_time += 2
        else:
            log_message(f"⚠️ Slide selector may not be accessible on port {SLIDE_SELECTOR_PORT}")
            log_message(f"🔧 Try manually accessing http://localhost:{SLIDE_SELECTOR_PORT} or http://your-server-ip:{SLIDE_SELECTOR_PORT}")
        
        # Wait for slides to be selected (check for slides.json)
        slides_json = os.path.join(slides_dir, "slides.json")
        while not os.path.exists(slides_json):
            time.sleep(2)
            if workflow_state['status'] != 'running':
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
            
            workflow_state['interactive_stage'] = 'speakers'
            workflow_state['interactive_ready'] = True
            log_message("🎤 Speaker labeling interface is ready")
            log_message("Please use the 'Open Speaker Labeler' button to label speakers")
            
            # Set environment variables for speaker labeler host/port
            env = os.environ.copy()
            env['SPEAKER_LABELER_HOST'] = '0.0.0.0'  # Bind to all interfaces for remote access
            env['SPEAKER_LABELER_PORT'] = str(SPEAKER_LABELER_PORT)
            
            # Start speaker labeling in background
            speaker_thread = threading.Thread(
                target=lambda: execute_command_with_env(
                    ["python", "05-label-speakers.py",
                     "-a", audio_path,
                     "-t", notes_path],
                    "Speaker labeling (web interface)",
                    env
                )
            )
            speaker_thread.daemon = True
            speaker_thread.start()
            
            # Check if speaker labeler is actually accessible
            max_wait_time = 30  # Wait up to 30 seconds for service to be ready
            wait_time = 0
            
            while wait_time < max_wait_time:
                if check_service_availability('localhost', int(SPEAKER_LABELER_PORT)):
                    log_message(f"✅ Speaker labeler is accessible on port {SPEAKER_LABELER_PORT}")
                    break
                else:
                    log_message(f"⏳ Waiting for speaker labeler to be ready on port {SPEAKER_LABELER_PORT}...")
                    time.sleep(2)
                    wait_time += 2
            else:
                log_message(f"⚠️ Speaker labeler may not be accessible on port {SPEAKER_LABELER_PORT}")
                log_message(f"🔧 Try manually accessing http://localhost:{SPEAKER_LABELER_PORT} or http://your-server-ip:{SPEAKER_LABELER_PORT}")
            
            # Wait for speaker labeling to complete
            speaker_labeled_notes = notes_path.replace(".md", "_with_speakernames.md")
            while speaker_thread.is_alive():
                time.sleep(2)
                if workflow_state['status'] != 'running':
                    return
            
            if os.path.exists(speaker_labeled_notes):
                notes_for_refinement = speaker_labeled_notes
                log_message("✅ Speaker labeling completed")
            else:
                log_message("ℹ️ Speaker labeling skipped or failed, using original notes")
            
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
    
    return redirect(f'http://{get_server_host()}:{SLIDE_SELECTOR_PORT}')

@app.route('/open_speakers')
def open_speakers():
    """Redirect to speaker labeler"""
    if workflow_state['interactive_stage'] != 'speakers' or not workflow_state['interactive_ready']:
        return jsonify({'error': 'Speaker labeler not ready'}), 400
    
    return redirect(f'http://{get_server_host()}:{SPEAKER_LABELER_PORT}')

@app.route('/status')
def status():
    """Get current workflow status"""
    return jsonify({
        'status': workflow_state['status'],
        'current_step': workflow_state['current_step'],
        'progress': workflow_state['progress'],
        'interactive_stage': workflow_state['interactive_stage'],
        'interactive_ready': workflow_state['interactive_ready'],
        'output_dir': workflow_state['output_dir']
    })

@app.route('/download/<path:filename>')
def download_file(filename):
    """Download generated files"""
    if not workflow_state['output_dir']:
        return jsonify({'error': 'No workflow output available'}), 404
    
    file_path = os.path.join(workflow_state['output_dir'], filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
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
            'port': SLIDE_SELECTOR_PORT,
            'accessible': check_service_availability('localhost', int(SLIDE_SELECTOR_PORT))
        },
        'speaker_labeler': {
            'port': SPEAKER_LABELER_PORT,
            'accessible': check_service_availability('localhost', int(SPEAKER_LABELER_PORT))
        }
    }
    
    return jsonify({
        'services': services,
        'local_server_mode': LOCAL_SERVER,
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

if __name__ == '__main__':
    # Set up logging
    logging.basicConfig(level=logging.INFO)

    logging.info("🚀 Starting Video2Notes Web Application")
    logging.info(f"📝 Access the application at: http://0.0.0.0:{MAIN_APP_PORT}")
    logging.info(f"🔧 Make sure ports {SLIDE_SELECTOR_PORT} (slide selector) and {SPEAKER_LABELER_PORT} (speaker labeler) are available")
    

    app.run(host='0.0.0.0', port=MAIN_APP_PORT, debug=False, threaded=True)