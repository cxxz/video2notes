"""
Speaker labeling routes for Video2Notes application.
"""
from flask import (
    Blueprint, render_template, render_template_string, request,
    jsonify, send_file, redirect, url_for, current_app
)

from ..models.speaker_labeler import speaker_labeler_state
from ..services.speaker_service import SpeakerService

speakers_bp = Blueprint('speakers', __name__)


@speakers_bp.route('/label-speakers')
def label_speakers_index():
    """Main speaker labeling page."""
    speaker_service = SpeakerService()
    
    if not speaker_labeler_state.active:
        # For now, return a simple error page until we extract templates
        return render_template_string("""
            <div style="padding: 20px; font-family: Arial, sans-serif;">
                <h1>Speaker Labeler - Error</h1>
                <div style="padding: 10px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px; color: #721c24;">
                    Speaker labeler not initialized
                </div>
            </div>
        """)
    
    speaker_info = speaker_service.get_current_speaker_info()
    
    if not speaker_info:
        # All speakers labeled, show results
        return redirect(url_for('speakers.speaker_labeling_result'))
    
    # Use the proper template with all interactive elements
    return render_template('speakers/label_speakers.html',
        current_speaker=speaker_info['speaker_id'],
        current_index=speaker_info['current_index'],
        total_speakers=speaker_info['total_speakers'],
        segments=speaker_info['segments']
    )


@speakers_bp.route('/play-speaker-audio/<speaker_id>')
def play_speaker_audio(speaker_id):
    """Generate and serve audio segment for a speaker."""
    speaker_service = SpeakerService()
    
    if not speaker_labeler_state.active:
        return jsonify({'error': 'Speaker labeler not active'}), 400
    
    segment_index = int(request.args.get('segment', 0))
    
    audio_path = speaker_service.get_speaker_audio_segment(speaker_id, segment_index)
    if not audio_path:
        return jsonify({'error': 'Audio segment not available'}), 400
    
    return send_file(audio_path, mimetype="audio/mpeg")


@speakers_bp.route('/label-speaker', methods=['POST'])
def label_speaker():
    """Label a speaker and move to the next one."""
    speaker_service = SpeakerService()
    
    if not speaker_labeler_state.active:
        return jsonify({'error': 'Speaker labeler not active'}), 400
    
    try:
        data = request.get_json()
        speaker_id = data.get('speaker_id')
        speaker_name = data.get('speaker_name', '').strip()
        
        result = speaker_service.label_speaker(speaker_id, speaker_name)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
        
    except Exception as e:
        current_app.logger.error(f"Error in label_speaker: {e}")
        return jsonify({'error': str(e)}), 500


@speakers_bp.route('/speaker-labeling-result')
def speaker_labeling_result():
    """Show speaker labeling results."""
    speaker_service = SpeakerService()
    results = speaker_service.get_labeling_results()
    
    # Calculate statistics
    total_speakers = results.get('total_speakers', 0)
    speaker_mapping = results.get('speaker_mapping', {})
    labeled_count = len(speaker_mapping)
    skipped_count = total_speakers - labeled_count
    
    # Use the proper template
    return render_template('speakers/results.html',
        speaker_mapping=speaker_mapping,
        output_path=results.get('output_transcript_path', ''),
        total_speakers=total_speakers,
        labeled_count=labeled_count,
        skipped_count=skipped_count
    )


