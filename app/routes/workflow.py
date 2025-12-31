"""
Workflow management routes for Video2Notes application.
"""
import os
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, Response
from flask import current_app
import json
import time

from ..models.workflow_state import workflow_state, WorkflowParameters
from ..models.sharepoint_state import sharepoint_state
from ..services.workflow_service import WorkflowService
from ..services.file_service import FileService
from ..services.sharepoint_service import SharePointService

workflow_bp = Blueprint('workflow', __name__)


@workflow_bp.route('/start', methods=['POST'])
def start_workflow():
    """Start the workflow with user parameters."""
    workflow_service = WorkflowService(workflow_state)
    file_service = FileService()
    sharepoint_service = SharePointService()
    
    if workflow_state.status.value == 'running':
        return jsonify({'error': 'Workflow is already running'}), 400
    
    # Get parameters from form
    input_method = request.form.get('input_method', '').strip()
    video_path = request.form.get('video_path', '').strip()
    
    # Handle upload method - find the most recent uploaded file
    if input_method == 'upload' and not video_path:
        video_path = file_service.find_most_recent_upload()
        if not video_path:
            return jsonify({'error': 'No uploaded video file found. Please upload a video first.'}), 400
        current_app.logger.info(f"Using uploaded file: {video_path}")
    
    # Handle SharePoint method - use the downloaded file
    elif input_method == 'sharepoint' and not video_path:
        is_valid, error_msg = sharepoint_service.validate_sharepoint_file_selection()
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        video_path = sharepoint_service.get_selected_file_path()
        current_app.logger.info(f"Using SharePoint downloaded file: {video_path}")
    
    # Create workflow parameters
    params = WorkflowParameters(
        video_path=video_path,
        do_split=request.form.get('do_split') == 'on',
        timestamp_file=request.form.get('timestamp_file', '').strip(),
        extract_audio=request.form.get('extract_audio', 'on') == 'on',
        skip_roi=request.form.get('skip_roi', 'on') == 'on',
        roi_timestamp=_parse_float(request.form.get('roi_timestamp', '').strip()),
        do_label_speakers=request.form.get('do_label_speakers', 'on') == 'on',
        do_refine_notes=request.form.get('do_refine_notes') == 'on',
        refine_notes_llm=request.form.get('refine_notes_llm', '').strip(),
        skip_slide_selection=request.form.get('skip_slide_selection', 'on') == 'on'
    )
    
    # Debug logging
    current_app.logger.info(f"Input method: '{input_method}'")
    current_app.logger.info(f"Final video_path: '{params.video_path}'")
    current_app.logger.info(f"Refine notes LLM: '{params.refine_notes_llm}'")
    current_app.logger.info(f"All form fields: {dict(request.form)}")
    
    # Validation
    is_valid, error_msg = file_service.validate_video_file(params.video_path)
    if not is_valid:
        return jsonify({'error': error_msg}), 400
    
    if params.do_split and (not params.timestamp_file or not os.path.exists(params.timestamp_file)):
        return jsonify({'error': 'Timestamp file required for video splitting'}), 400
    
    # Validate refine notes LLM model if specified
    if params.do_refine_notes and params.refine_notes_llm:
        allowed_models = current_app.config.get('ALLOWED_LLM_MODELS', [])
        if params.refine_notes_llm not in allowed_models:
            return jsonify({'error': f'Invalid LLM model selection: {params.refine_notes_llm}'}), 400
    
    # Start workflow
    result = workflow_service.start_workflow(params)
    if not result['success']:
        return jsonify(result), 400
    
    return redirect(url_for('workflow.progress'))


@workflow_bp.route('/progress')
def progress():
    """Workflow progress page."""
    # Log current workflow state for debugging
    current_app.logger.info(f"Progress page accessed - Workflow status: {workflow_state.status.value}")
    current_app.logger.info(f"Current step: {workflow_state.current_step}")
    current_app.logger.info(f"Progress: {workflow_state.progress}")
    current_app.logger.info(f"Logs count: {len(workflow_state.logs)}")
    
    return render_template('workflow.html')


@workflow_bp.route('/progress_stream')
def progress_stream():
    """Server-sent events for real-time progress updates."""
    import logging
    logger = logging.getLogger(__name__)
    
    def generate():
        last_log_count = 0
        logger.info("SSE connection established")
        
        # Send initial status immediately
        initial_data = {
            'status': workflow_state.status.value,
            'current_step': workflow_state.current_step or 'Initializing...',
            'progress': workflow_state.progress,
            'interactive_stage': workflow_state.interactive_stage.value if workflow_state.interactive_stage else None,
            'interactive_ready': workflow_state.interactive_ready,
            'new_logs': workflow_state.logs
        }
        logger.info(f"Sending initial SSE data: status={initial_data['status']}, step={initial_data['current_step']}, progress={initial_data['progress']}")
        yield f"data: {json.dumps(initial_data)}\n\n"
        last_log_count = len(workflow_state.logs)
        
        while True:
            # Send current status
            data = {
                'status': workflow_state.status.value,
                'current_step': workflow_state.current_step,
                'progress': workflow_state.progress,
                'interactive_stage': workflow_state.interactive_stage.value if workflow_state.interactive_stage else None,
                'interactive_ready': workflow_state.interactive_ready,
                'new_logs': workflow_state.logs[last_log_count:]
            }
            
            # Only send if there are updates
            if data['new_logs'] or last_log_count == 0:
                yield f"data: {json.dumps(data)}\n\n"
                last_log_count = len(workflow_state.logs)
            
            if workflow_state.status.value in ['completed', 'error', 'stopped']:
                # Send one final update after a short delay to ensure frontend receives it
                time.sleep(0.5)
                yield f"data: {json.dumps(data)}\n\n"
                logger.info("SSE connection closing - workflow finished")
                break
                
            time.sleep(1)
    
    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Cache-Control'
    response.headers['X-Accel-Buffering'] = 'no'  # Disable buffering for nginx
    return response


@workflow_bp.route('/stop', methods=['POST'])
def stop_workflow():
    """Stop the current workflow."""
    workflow_service = WorkflowService(workflow_state)
    return jsonify(workflow_service.stop_workflow())


@workflow_bp.route('/status')
def workflow_status():
    """Get workflow status."""
    workflow_service = WorkflowService(workflow_state)
    return jsonify(workflow_service.get_workflow_status())


@workflow_bp.route('/open_slides')
def open_slides():
    """Redirect to slide selector."""
    if (workflow_state.interactive_stage and workflow_state.interactive_stage.value != 'slides') or not workflow_state.interactive_ready:
        return jsonify({'error': 'Slide selector not ready'}), 400
    
    return redirect(url_for('slides.select_slides_index'))


@workflow_bp.route('/open_speakers')
def open_speakers():
    """Redirect to speaker labeler."""
    if (workflow_state.interactive_stage and workflow_state.interactive_stage.value != 'speakers') or not workflow_state.interactive_ready:
        return jsonify({'error': 'Speaker labeler not ready'}), 400
    
    return redirect(url_for('speakers.label_speakers_index'))


@workflow_bp.route('/debug_form', methods=['POST'])
def debug_form():
    """Debug endpoint to check form submission data."""
    form_data = dict(request.form)
    files_data = {key: file.filename for key, file in request.files.items()}
    
    return jsonify({
        'form_data': form_data,
        'files_data': files_data,
        'video_path': request.form.get('video_path', ''),
        'video_path_exists': os.path.exists(request.form.get('video_path', '')) if request.form.get('video_path') else False
    })


def _parse_float(value: str) -> float:
    """Parse float value from string, return None if invalid."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None