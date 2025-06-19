"""
SharePoint service for handling SharePoint video download functionality.
"""
import os
from typing import List, Dict, Any, Optional
from flask import current_app

from ..models.sharepoint_state import sharepoint_state
from ..utils.file_utils import get_file_size_mb


class SharePointService:
    """Service for handling SharePoint operations."""
    
    def __init__(self):
        self.state = sharepoint_state
        self.upload_folder = current_app.config['UPLOAD_FOLDER']
    
    def list_video_files(self) -> Dict[str, Any]:
        """Get list of video files from SharePoint."""
        try:
            # Initialize SharePoint downloader
            sharepoint_url = current_app.config.get('SHAREPOINT_URL')
            if not sharepoint_url:
                return {'success': False, 'error': 'SHAREPOINT_URL not configured'}
            
            # Import SharePoint downloader
            from ..utils.sharepoint_downloader import SharePointDownloader
            
            downloader = SharePointDownloader(
                sharepoint_url=sharepoint_url,
                output_dir=self.upload_folder
            )
            
            # Get video files from SharePoint
            video_files = downloader.get_video_files()
            
            # Store in state
            self.state.downloader = downloader
            self.state.video_files = video_files
            self.state.active = True
            
            # Prepare simplified file list for frontend (limit to 10 files)
            file_list = []
            for i, video_file in enumerate(video_files[:10]):
                file_info = {
                    'index': i,
                    'filename': video_file['FileLeafRef'],
                    'modified': video_file.get('Modified.', 'Unknown'),
                    'size': video_file.get('FileSizeDisplay', 'Unknown')
                }
                file_list.append(file_info)
            
            current_app.logger.info(f"Found {len(video_files)} SharePoint video files")
            
            return {
                'success': True,
                'files': file_list,
                'total_count': len(video_files)
            }
            
        except Exception as e:
            current_app.logger.error(f"SharePoint list error: {str(e)}")
            return {'success': False, 'error': f'Failed to list SharePoint videos: {str(e)}'}
    
    def download_video_file(self, file_index: int) -> Dict[str, Any]:
        """Download selected video file from SharePoint."""
        try:
            if not self.state.active or not self.state.video_files:
                return {'success': False, 'error': 'SharePoint video list not loaded. Please list videos first.'}
            
            video_files = self.state.video_files
            if file_index < 0 or file_index >= len(video_files):
                return {'success': False, 'error': 'Invalid file index'}
            
            selected_file = self.state.get_file_by_index(file_index)
            downloader = self.state.downloader
            
            if not downloader:
                return {'success': False, 'error': 'SharePoint downloader not initialized'}
            
            # Set downloading state
            self.state.downloading = True
            self.state.selected_file = selected_file
            
            filename = selected_file['FileLeafRef']
            current_app.logger.info(f"Starting download of SharePoint file: {filename}")
            
            try:
                # Download the file
                success = downloader.download_file(selected_file)
                
                if success:
                    # Verify the file was downloaded
                    expected_path = os.path.join(self.upload_folder, filename)
                    if os.path.exists(expected_path):
                        file_size_mb = get_file_size_mb(expected_path)
                        current_app.logger.info(f"SharePoint video downloaded: {filename} ({file_size_mb:.1f} MB)")
                        
                        return {
                            'success': True,
                            'filename': filename,
                            'file_path': expected_path,
                            'size_mb': round(file_size_mb, 1)
                        }
                    else:
                        current_app.logger.error(f"Downloaded file not found at expected path: {expected_path}")
                        return {'success': False, 'error': 'Download completed but file not found'}
                else:
                    current_app.logger.error(f"Failed to download SharePoint file: {filename}")
                    return {'success': False, 'error': 'Download failed'}
            finally:
                self.state.downloading = False
                
        except Exception as e:
            self.state.downloading = False
            current_app.logger.error(f"SharePoint download error: {str(e)}")
            return {'success': False, 'error': f'Download failed: {str(e)}'}
    
    def get_sharepoint_status(self) -> Dict[str, Any]:
        """Get SharePoint downloader status."""
        return self.state.to_dict()
    
    def get_selected_file_path(self) -> Optional[str]:
        """Get path to the selected/downloaded SharePoint file."""
        if not self.state.selected_file:
            return None
        
        filename = self.state.selected_filename
        if not filename:
            return None
        
        file_path = os.path.join(self.upload_folder, filename)
        if os.path.exists(file_path):
            return file_path
        
        return None
    
    def reset_sharepoint_state(self) -> None:
        """Reset SharePoint state."""
        self.state.reset()
    
    def is_sharepoint_configured(self) -> bool:
        """Check if SharePoint is properly configured."""
        return bool(current_app.config.get('SHAREPOINT_URL'))
    
    def validate_sharepoint_file_selection(self) -> tuple[bool, Optional[str]]:
        """Validate that a SharePoint file has been selected and downloaded."""
        if not self.state.selected_file:
            return False, 'No SharePoint file selected. Please select and download a video first.'
        
        file_path = self.get_selected_file_path()
        if not file_path:
            return False, 'Downloaded SharePoint file not found. Please download a video first.'
        
        return True, None