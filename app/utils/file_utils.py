"""
File utility functions for Video2Notes application.
"""
import os
import time
import zipfile
from datetime import datetime
from typing import Dict, Any, Optional
from flask import current_app


def allowed_file(filename: str) -> bool:
    """Check if file has an allowed extension."""
    if not filename or '.' not in filename:
        return False
    
    extension = filename.rsplit('.', 1)[1].lower()
    return extension in current_app.config['ALLOWED_EXTENSIONS']


def get_file_size_mb(file_path: str) -> float:
    """Get file size in MB."""
    try:
        return os.path.getsize(file_path) / (1024 * 1024)
    except (OSError, IOError):
        return 0.0


def get_file_info(file_path: str) -> Dict[str, Any]:
    """Get file information for display."""
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
    except (OSError, IOError):
        return {
            'size': 0,
            'size_str': 'Unknown',
            'modified': 'Unknown'
        }


def cleanup_old_uploads() -> None:
    """Clean up old uploaded files (older than configured hours)."""
    upload_folder = current_app.config['UPLOAD_FOLDER']
    max_age_hours = current_app.config.get('FILE_CLEANUP_AGE_HOURS', 24)
    
    if not os.path.exists(upload_folder):
        return
    
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    
    try:
        for filename in os.listdir(upload_folder):
            file_path = os.path.join(upload_folder, filename)
            
            if not os.path.isfile(file_path):
                continue
                
            file_age = current_time - os.path.getmtime(file_path)
            if file_age > max_age_seconds:
                try:
                    os.remove(file_path)
                    current_app.logger.info(f"Cleaned up old upload: {filename}")
                except OSError as e:
                    current_app.logger.error(f"Error cleaning up {filename}: {e}")
    except OSError as e:
        current_app.logger.error(f"Error accessing upload folder during cleanup: {e}")


def create_output_zip(output_dir: str) -> Optional[str]:
    """Create a ZIP file of the entire output directory."""
    if not output_dir or not os.path.exists(output_dir):
        return None
    
    try:
        # Create ZIP filename based on output directory name
        output_basename = os.path.basename(output_dir)
        zip_filename = f"{output_basename}.zip"
        zip_path = os.path.join(output_dir, zip_filename)
        
        # Don't recreate if already exists and is recent
        cache_duration = current_app.config.get('ZIP_CACHE_DURATION_SECONDS', 60)
        if os.path.exists(zip_path):
            zip_age = time.time() - os.path.getmtime(zip_path)
            if zip_age < cache_duration:
                return zip_filename
        
        # Create the ZIP file
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    # Skip the ZIP file itself
                    if file == zip_filename:
                        continue
                    
                    file_path = os.path.join(root, file)
                    # Create relative path for inside the ZIP
                    arcname = os.path.relpath(file_path, output_dir)
                    zipf.write(file_path, arcname)
        
        current_app.logger.info(f"Created ZIP file: {zip_path}")
        return zip_filename
        
    except Exception as e:
        current_app.logger.error(f"Error creating ZIP file: {e}")
        return None


def ensure_directory_exists(directory: str) -> bool:
    """Ensure a directory exists, create if it doesn't."""
    try:
        os.makedirs(directory, exist_ok=True)
        return True
    except OSError as e:
        current_app.logger.error(f"Error creating directory {directory}: {e}")
        return False


def list_directory_contents(path: str) -> Dict[str, Any]:
    """List directory contents with metadata."""
    if not os.path.exists(path) or not os.path.isdir(path):
        raise ValueError(f"Path does not exist or is not a directory: {path}")
    
    items = []
    
    # Add parent directory option (except for root)
    parent_path = os.path.dirname(path)
    if parent_path != path:
        from .security import is_safe_path
        if is_safe_path(parent_path):
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
    
    return {
        'current_path': path,
        'items': items
    }