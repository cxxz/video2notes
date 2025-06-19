"""
SharePoint downloader state management.
"""
import threading
from typing import List, Dict, Any, Optional


class SharePointState:
    """Manages the state of the SharePoint downloader."""
    
    def __init__(self):
        self._downloader = None  # SharePointDownloader instance
        self._video_files: List[Dict[str, Any]] = []
        self._selected_file: Optional[Dict[str, Any]] = None
        self._downloading = False
        self._download_progress = 0
        self._active = False
        self._lock = threading.Lock()
    
    @property
    def downloader(self):
        """Get SharePoint downloader instance."""
        with self._lock:
            return self._downloader
    
    @downloader.setter
    def downloader(self, value) -> None:
        """Set SharePoint downloader instance."""
        with self._lock:
            self._downloader = value
    
    @property
    def video_files(self) -> List[Dict[str, Any]]:
        """Get video files list."""
        with self._lock:
            return self._video_files.copy()
    
    @video_files.setter
    def video_files(self, value: List[Dict[str, Any]]) -> None:
        """Set video files list."""
        with self._lock:
            self._video_files = value.copy() if value else []
    
    @property
    def selected_file(self) -> Optional[Dict[str, Any]]:
        """Get selected file."""
        with self._lock:
            return self._selected_file.copy() if self._selected_file else None
    
    @selected_file.setter
    def selected_file(self, value: Optional[Dict[str, Any]]) -> None:
        """Set selected file."""
        with self._lock:
            self._selected_file = value.copy() if value else None
    
    @property
    def downloading(self) -> bool:
        """Get downloading status."""
        with self._lock:
            return self._downloading
    
    @downloading.setter
    def downloading(self, value: bool) -> None:
        """Set downloading status."""
        with self._lock:
            self._downloading = value
    
    @property
    def download_progress(self) -> int:
        """Get download progress."""
        with self._lock:
            return self._download_progress
    
    @download_progress.setter
    def download_progress(self, value: int) -> None:
        """Set download progress."""
        with self._lock:
            self._download_progress = max(0, min(100, value))
    
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
    def files_count(self) -> int:
        """Get number of video files."""
        with self._lock:
            return len(self._video_files)
    
    @property
    def selected_filename(self) -> Optional[str]:
        """Get selected file name."""
        with self._lock:
            if self._selected_file:
                return self._selected_file.get('FileLeafRef')
            return None
    
    def get_file_by_index(self, index: int) -> Optional[Dict[str, Any]]:
        """Get file by index."""
        with self._lock:
            if 0 <= index < len(self._video_files):
                return self._video_files[index].copy()
            return None
    
    def reset(self) -> None:
        """Reset state to initial values.""" 
        with self._lock:
            self._downloader = None
            self._video_files.clear()
            self._selected_file = None
            self._downloading = False
            self._download_progress = 0
            self._active = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for API responses."""
        with self._lock:
            return {
                'active': self._active,
                'downloading': self._downloading,
                'download_progress': self._download_progress,
                'files_count': len(self._video_files),
                'selected_file': self._selected_file.get('FileLeafRef') if self._selected_file else None
            }


# Global SharePoint state instance
sharepoint_state = SharePointState()