"""
Slide selection routes for Video2Notes application.
"""
import os
from flask import Blueprint, render_template, request, jsonify, send_file
from flask import current_app

from ..models.slide_selector import slide_selector_state
from ..services.slide_service import SlideService

slides_bp = Blueprint('slides', __name__)


@slides_bp.route('/select-slides')
def select_slides_index():
    """Main slide selection page."""
    slide_service = SlideService()
    
    if not slide_selector_state.active:
        return render_template('slides/select_slides.html', 
                             slides=[], 
                             slide_ids=[],
                             error="Slide selector not initialized")
    
    slides = slide_service.get_slides_for_display()
    slide_ids = [slide['group_id'] for slide in slides]
    
    return render_template('slides/select_slides.html', 
                         slides=slides,
                         slide_ids=slide_ids)


@slides_bp.route('/slide-images/<path:filename>')
def slide_images(filename):
    """Serve slide images."""
    slide_service = SlideService()
    
    if not slide_selector_state.active:
        return jsonify({'error': 'Slide selector not active'}), 400
    
    # Extract folder name and image filename
    parts = filename.split('/', 1)
    if len(parts) != 2:
        return jsonify({'error': 'Invalid image path'}), 400
    
    folder_name, image_filename = parts
    
    # Debug logging
    current_app.logger.info(f"Requesting slide image: folder={folder_name}, file={image_filename}")
    current_app.logger.info(f"Current folder_path: {slide_selector_state.folder_path}")
    
    image_path = slide_service.get_slide_image_path(folder_name, image_filename)
    if not image_path:
        current_app.logger.error(f"Image not found: {folder_name}/{image_filename}")
        return jsonify({'error': 'Image not found'}), 404
    
    current_app.logger.info(f"Serving image from: {image_path}")
    return send_file(image_path)


@slides_bp.route('/save-slide-selection', methods=['POST'])
def save_slide_selection():
    """Save the selected slides."""
    slide_service = SlideService()
    
    if not slide_selector_state.active:
        return jsonify({'error': 'Slide selector not active'}), 400
    
    try:
        data = request.get_json()
        selected_ids = data.get('selected_ids', [])
        
        result = slide_service.save_slide_selection(selected_ids)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
        
    except Exception as e:
        current_app.logger.error(f"Error in save_slide_selection: {e}")
        return jsonify({'error': str(e)}), 500


@slides_bp.route('/extract-vocabulary-ajax', methods=['POST'])
def extract_vocabulary_ajax():
    """Extract vocabulary via AJAX."""
    slide_service = SlideService()
    
    if not slide_selector_state.active:
        return jsonify({'error': 'Slide selector not active'}), 400
    
    try:
        data = request.get_json()
        model_id = data.get('model_id', 'bedrock/claude-4-sonnet')
        
        result = slide_service.extract_vocabulary(model_id)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
        
    except Exception as e:
        current_app.logger.error(f"Error in extract_vocabulary_ajax: {e}")
        return jsonify({'error': str(e)}), 500


@slides_bp.route('/debug-slides')
def debug_slides():
    """Debug endpoint to check slide state."""
    from flask import current_app
    
    state_info = slide_selector_state.to_dict()
    
    # Add more debug info
    if slide_selector_state.slides:
        first_slide = slide_selector_state.slides[0]
        state_info['first_slide_details'] = {
            'group_id': first_slide.group_id,
            'image_path': first_slide.image_path,
            'image_url': first_slide.image_url,
            'image_exists': os.path.exists(first_slide.image_path) if first_slide.image_path else False
        }
    
    state_info['folder_exists'] = os.path.exists(slide_selector_state.folder_path) if slide_selector_state.folder_path else False
    
    return jsonify(state_info)


@slides_bp.route('/save-vocabulary', methods=['POST'])
def save_vocabulary():
    """Save vocabulary to vocabulary.txt file."""
    slide_service = SlideService()
    
    if not slide_selector_state.active:
        return jsonify({'error': 'Slide selector not active'}), 400
    
    try:
        data = request.get_json()
        vocabulary_text = data.get('vocabulary', '').strip()
        
        result = slide_service.save_vocabulary(vocabulary_text)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
        
    except Exception as e:
        current_app.logger.error(f"Error in save_vocabulary: {e}")
        return jsonify({'error': str(e)}), 500


# Import render_template_string for the temporary template
from flask import render_template_string