"""
Slide selector state management.
"""
import threading
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class Slide:
    """Represents a slide with metadata."""
    group_id: int
    image_path: str
    image_url: str = ''
    timestamp: str = 'Unknown'
    ocr_text: str = ''
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Slide':
        """Create Slide from dictionary."""
        return cls(
            group_id=data['group_id'],
            image_path=data['image_path'],
            image_url=data.get('image_url', ''),
            timestamp=data.get('timestamp', 'Unknown'),
            ocr_text=data.get('ocr_text', '')
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert slide to dictionary."""
        return {
            'group_id': self.group_id,
            'image_path': self.image_path,
            'image_url': self.image_url,
            'timestamp': self.timestamp,
            'ocr_text': self.ocr_text
        }


class SlideSelectorState:
    """Manages the state of the slide selector."""
    
    def __init__(self):
        self._folder_path = ''
        self._slides: List[Slide] = []
        self._active = False
        self._lock = threading.Lock()
    
    @property
    def folder_path(self) -> str:
        """Get folder path."""
        with self._lock:
            return self._folder_path
    
    @folder_path.setter
    def folder_path(self, value: str) -> None:
        """Set folder path."""
        with self._lock:
            self._folder_path = value
    
    @property
    def slides(self) -> List[Slide]:
        """Get slides list."""
        with self._lock:
            return self._slides.copy()
    
    @slides.setter
    def slides(self, value: List[Slide]) -> None:
        """Set slides list."""
        with self._lock:
            self._slides = value.copy() if value else []
    
    def add_slide(self, slide: Slide) -> None:
        """Add a slide to the collection."""
        with self._lock:
            self._slides.append(slide)
    
    def clear_slides(self) -> None:
        """Clear all slides."""
        with self._lock:
            self._slides.clear()
    
    def get_slide_by_id(self, group_id: int) -> Optional[Slide]:
        """Get slide by group ID."""
        with self._lock:
            for slide in self._slides:
                if slide.group_id == group_id:
                    return slide
            return None
    
    @property
    def active(self) -> bool:
        """Get active status."""
        with self._lock:
            return self._active
    
    @active.setter
    def active(self, value: bool) -> None:
        """Set active status."""
        with self._lock:
            self._active = value
    
    @property
    def slide_count(self) -> int:
        """Get number of slides."""
        with self._lock:
            return len(self._slides)
    
    def reset(self) -> None:
        """Reset state to initial values."""
        with self._lock:
            self._folder_path = ''
            self._slides.clear()
            self._active = False
    
    def load_from_json_data(self, slides_data: List[Dict[str, Any]]) -> None:
        """Load slides from JSON data."""
        slides = [Slide.from_dict(slide_data) for slide_data in slides_data]
        self.slides = slides
    
    def get_slides_as_dict(self) -> List[Dict[str, Any]]:
        """Get slides as list of dictionaries."""
        with self._lock:
            return [slide.to_dict() for slide in self._slides]
    
    def get_ocr_text_combined(self) -> str:
        """Get combined OCR text from all slides."""
        with self._lock:
            ocr_texts = [slide.ocr_text for slide in self._slides if slide.ocr_text]
            return '\n'.join(ocr_texts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for API responses."""
        with self._lock:
            return {
                'folder_path': self._folder_path,
                'active': self._active,
                'slide_count': len(self._slides),
                'slides': [slide.to_dict() for slide in self._slides]
            }


# Global slide selector state instance
slide_selector_state = SlideSelectorState()