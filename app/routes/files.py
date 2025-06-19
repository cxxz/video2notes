"""
File management routes for Video2Notes application.
"""
from flask import Blueprint, request, jsonify, send_file
from flask import current_app

from ..models.workflow_state import workflow_state
from ..services.file_service import FileService
from ..services.sharepoint_service import SharePointService

files_bp = Blueprint('files', __name__)


@files_bp.route('/upload', methods=['POST'])
def upload_video():
    """Handle video file upload."""
    file_service = FileService()
    
    if 'video_file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400
    
    file = request.files['video_file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    result = file_service.handle_file_upload(file)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 500


@files_bp.route('/browse')
def browse_files():
    """Browse files and directories on the server."""
    file_service = FileService()
    path = request.args.get('path')
    
    result = file_service.browse_files(path)
    
    if result['success']:
        return jsonify({
            'current_path': result['current_path'],
            'items': result['items']
        })
    else:
        status_code = 403 if 'not allowed' in result['error'] else 404 if 'not exist' in result['error'] else 500
        return jsonify({'error': result['error']}), status_code


@files_bp.route('/get_initial_browse_path')
def get_initial_browse_path():
    """Get the initial path for file browsing."""
    file_service = FileService()
    initial_path = file_service.get_initial_browse_path()
    return jsonify({'path': initial_path})


@files_bp.route('/download/<path:filename>')
def download_file(filename):
    """Download generated files."""
    file_service = FileService()
    
    result = file_service.prepare_download_file(workflow_state.output_dir, filename)
    
    if not result['success']:
        status_code = 403 if 'Invalid file path' in result['error'] else 404
        return jsonify({'error': result['error']}), status_code
    
    file_path = result['file_path']
    
    # Handle ZIP files with proper content type
    if filename.lower().endswith('.zip'):
        return send_file(file_path, as_attachment=True, mimetype='application/zip')
    else:
        return send_file(file_path, as_attachment=True)


# SharePoint related routes
@files_bp.route('/sharepoint/list_videos', methods=['GET'])
def sharepoint_list_videos():
    """Get list of video files from SharePoint."""
    sharepoint_service = SharePointService()
    
    if not sharepoint_service.is_sharepoint_configured():
        return jsonify({'error': 'SHAREPOINT_URL environment variable not set'}), 500
    
    result = sharepoint_service.list_video_files()
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 500


@files_bp.route('/sharepoint/download/<int:file_index>', methods=['POST'])
def sharepoint_download_video(file_index):
    """Download selected video file from SharePoint."""
    sharepoint_service = SharePointService()
    
    result = sharepoint_service.download_video_file(file_index)
    
    if result['success']:
        return jsonify(result)
    else:
        status_code = 400 if 'not loaded' in result['error'] or 'Invalid file' in result['error'] else 500
        return jsonify(result), status_code


@files_bp.route('/sharepoint/status')
def sharepoint_status():
    """Get SharePoint downloader status."""
    sharepoint_service = SharePointService()
    return jsonify(sharepoint_service.get_sharepoint_status())