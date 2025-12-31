"""
Main routes for Video2Notes application.
"""
import os
from functools import wraps
from flask import Blueprint, render_template, jsonify, send_file, request
from flask import current_app

from ..models.workflow_state import workflow_state
from ..models.slide_selector import slide_selector_state
from ..models.speaker_labeler import speaker_labeler_state
from ..services.workflow_service import WorkflowService
from ..services.file_service import FileService

main_bp = Blueprint('main', __name__)


def debug_only(f):
    """Decorator to restrict access to debug endpoints.

    Checks:
    1. DEBUG config must be True
    2. If DEBUG_TOKEN is set, requires matching token in header or query param
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_app.config.get('DEBUG', False):
            current_app.logger.warning(
                f"Debug endpoint access denied (DEBUG=False): {request.path} from {request.remote_addr}"
            )
            return jsonify({'error': 'Debug endpoints are disabled in production'}), 403

        # Optional: check for debug token if configured
        debug_token = os.getenv('DEBUG_TOKEN')
        if debug_token:
            provided_token = request.headers.get('X-Debug-Token') or request.args.get('debug_token')
            if provided_token != debug_token:
                current_app.logger.warning(
                    f"Debug endpoint access denied (invalid token): {request.path} from {request.remote_addr}"
                )
                return jsonify({'error': 'Invalid debug token'}), 403

        return f(*args, **kwargs)
    return decorated_function


@main_bp.route('/')
def index():
    """Main page with workflow configuration form."""
    return render_template('index.html')


@main_bp.route('/status')
def status():
    """Get current workflow status."""
    workflow_service = WorkflowService(workflow_state)
    return jsonify(workflow_service.get_workflow_status())


@main_bp.route('/debug')
@debug_only
def debug():
    """Debug endpoint to check workflow state."""
    return jsonify({
        'workflow_state': workflow_state.to_dict()
    })


@main_bp.route('/debug/services')
@debug_only
def debug_services():
    """Debug endpoint to check service availability."""
    services = {
        'slide_selector': {
            'integrated': True,
            'active': slide_selector_state.active,
            'slides_count': slide_selector_state.slide_count
        },
        'speaker_labeler': {
            'integrated': True,
            'active': speaker_labeler_state.active,
            'speakers_count': len(speaker_labeler_state.speaker_ids)
        }
    }
    
    return jsonify({
        'services': services,
        'architecture': 'integrated',
        'workflow_interactive_stage': workflow_state.interactive_stage.value if workflow_state.interactive_stage else None,
        'workflow_interactive_ready': workflow_state.interactive_ready
    })


@main_bp.route('/debug/files')
@debug_only
def debug_files():
    """Debug endpoint to list files in various directories."""
    info = {}
    
    # Upload folder
    upload_folder = current_app.config['UPLOAD_FOLDER']
    if os.path.exists(upload_folder):
        info['upload_folder'] = {
            'path': upload_folder,
            'files': os.listdir(upload_folder)
        }
    
    # Workflow output directory
    output_dir = workflow_state.output_dir
    if output_dir and os.path.exists(output_dir):
        info['output_dir'] = {
            'path': output_dir,
            'files': []
        }
        for root, dirs, files in os.walk(output_dir):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), output_dir)
                info['output_dir']['files'].append(rel_path)
    
    return jsonify(info)


@main_bp.route('/download/<path:filename>')
def download_file(filename):
    """Download generated files - compatibility route for original app."""
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