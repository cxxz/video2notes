"""
Slide service for handling slide selection functionality.
"""
import os
import json
import shutil
from typing import List, Dict, Any, Optional
from flask import current_app

from ..models.slide_selector import slide_selector_state, Slide
from ..models.workflow_state import workflow_state
from ..utils.file_utils import get_file_info


class SlideService:
    """Service for handling slide selection operations."""
    
    def __init__(self):
        self.state = slide_selector_state
    
    def initialize_slide_selector(self, folder_path: str) -> bool:
        """Initialize the slide selector with the given folder."""
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
                slides_data = json.load(f)
        except Exception as e:
            current_app.logger.error(f"Error loading slides.json: {e}")
            return False
        
        # Convert to Slide objects and update with relative image paths
        slides = []
        folder_basename = os.path.basename(folder_path)
        
        for slide_data in slides_data:
            slide = Slide.from_dict(slide_data)
            # Extract filename from image_path and create image_url
            filename = os.path.basename(slide.image_path)
            slide.image_url = f"/slides/slide-images/{folder_basename}/{filename}"
            slides.append(slide)
        
        # Update global state
        self.state.folder_path = folder_path
        self.state.slides = slides
        self.state.active = True
        
        workflow_state.add_log(f"Slide selector initialized with {len(slides)} slides")
        return True
    
    def get_slides_for_display(self) -> List[Dict[str, Any]]:
        """Get slides formatted for display in the UI."""
        if not self.state.active:
            return []
        
        return self.state.get_slides_as_dict()
    
    def save_slide_selection(self, selected_ids: List[int]) -> Dict[str, Any]:
        """Save the selected slides."""
        if not self.state.active:
            return {'success': False, 'error': 'Slide selector not active'}
        
        try:
            slides = self.state.slides
            folder_path = self.state.folder_path
            
            # Process the slides
            pruned_slides = self._process_slides(selected_ids, slides, folder_path)
            
            # Save the new slides.json
            slides_json_path = os.path.join(folder_path, 'slides.json')
            # Convert back to the original format expected by the workflow
            slides_data = []
            for slide in pruned_slides:
                slide_dict = {
                    'group_id': slide.group_id,
                    'image_path': slide.image_path,
                    'timestamp': slide.timestamp,
                    'ocr_text': slide.ocr_text
                }
                slides_data.append(slide_dict)
            
            with open(slides_json_path, 'w') as f:
                json.dump(slides_data, f, indent=2)
            
            workflow_state.add_log(f"✅ Slide selection saved: {len(pruned_slides)} slides selected to {slides_json_path}")
            
            return {
                'success': True,
                'selected_count': len(pruned_slides),
                'total_count': len(slides)
            }
            
        except Exception as e:
            current_app.logger.error(f"Error saving slide selection: {e}")
            return {'success': False, 'error': str(e)}
    
    def extract_vocabulary(self, model_id: str = 'azure/gpt-5.1') -> Dict[str, Any]:
        """Extract vocabulary via LLM."""
        if not self.state.active:
            return {'success': False, 'error': 'Slide selector not active'}
        
        try:
            # Collect OCR text from all slides
            combined_text = self.state.get_ocr_text_combined()
            
            if not combined_text.strip():
                return {'success': False, 'error': 'No OCR text available'}
            
            # Extract vocabulary using LLM
            from utils import initialize_client, get_llm_response
            vocabulary = self._extract_vocabulary_with_llm(combined_text, model_id)
            
            return {
                'success': True,
                'vocabulary': vocabulary
            }
            
        except Exception as e:
            current_app.logger.error(f"Error extracting vocabulary: {e}")
            return {'success': False, 'error': str(e)}
    
    def save_vocabulary(self, vocabulary_text: str) -> Dict[str, Any]:
        """Save vocabulary to vocabulary.txt file."""
        if not self.state.active:
            return {'success': False, 'error': 'Slide selector not active'}
        
        try:
            if not vocabulary_text.strip():
                return {'success': False, 'error': 'No vocabulary text provided'}
            
            # Save to vocabulary.txt in the slides folder
            folder_path = self.state.folder_path
            vocab_file_path = os.path.join(folder_path, 'vocabulary.txt')
            
            with open(vocab_file_path, 'w', encoding='utf-8') as f:
                f.write(vocabulary_text)
            
            workflow_state.add_log(f"✅ Vocabulary saved to: {vocab_file_path}")
            
            return {
                'success': True,
                'file_path': vocab_file_path
            }
            
        except Exception as e:
            current_app.logger.error(f"Error saving vocabulary: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_slide_image_path(self, folder_name: str, image_filename: str) -> Optional[str]:
        """Get the full path to a slide image file."""
        if not self.state.active:
            return None
        
        # Construct the full path
        base_folder_path = os.path.dirname(self.state.folder_path)
        image_path = os.path.join(base_folder_path, folder_name, image_filename)
        
        # Security check
        if not os.path.exists(image_path) or not os.path.isfile(image_path):
            return None
        
        return image_path
    
    def reset_selector(self) -> None:
        """Reset the slide selector state."""
        self.state.reset()
    
    def _process_slides(self, selected_ids: List[int], slides: List[Slide], folder_path: str) -> List[Slide]:
        """Process the slides based on selected IDs."""
        pruned = []
        
        # Backup original slides.json to ori_slides.json
        original_slides_path = os.path.join(folder_path, "slides.json")
        backup_slides_path = os.path.join(folder_path, "ori_slides.json")
        if os.path.exists(original_slides_path) and not os.path.exists(backup_slides_path):
            shutil.copy2(original_slides_path, backup_slides_path)
        
        for slide in slides:
            if slide.group_id in selected_ids:
                pruned.append(slide)
        
        return pruned
    
    def _extract_vocabulary_with_llm(self, ocr_text: str, model_id: str) -> str:
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
        from utils import initialize_client, get_llm_response
        client = initialize_client(model_id)
        return get_llm_response(client, model_id, extract_voc_prompt)
