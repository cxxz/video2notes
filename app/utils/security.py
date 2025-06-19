"""
Security utility functions for Video2Notes application.
"""
import os
import socket
from typing import List
from flask import current_app, request


def is_safe_path(path: str) -> bool:
    """Check if a path is safe to browse (within allowed directories)."""
    if not path:
        return False
    
    try:
        real_path = os.path.realpath(path)
        safe_dirs: List[str] = current_app.config['SAFE_BROWSE_DIRS']
        
        for safe_dir in safe_dirs:
            safe_real_path = os.path.realpath(safe_dir)
            if real_path.startswith(safe_real_path):
                return True
        return False
    except Exception:
        return False


def validate_file_path_security(file_path: str, base_dir: str) -> bool:
    """Validate that a file path is secure and within the base directory."""
    try:
        real_base_dir = os.path.realpath(base_dir)
        real_file_path = os.path.realpath(file_path)
        return real_file_path.startswith(real_base_dir)
    except Exception:
        return False


def get_server_host() -> str:
    """Get the server host/IP address from the request."""
    current_app.logger.info(f"Whether to use local server: {current_app.config.get('LOCAL_SERVER', False)}")
    
    if current_app.config.get('LOCAL_SERVER', False):
        return 'localhost'

    # Try to get the host from the request
    host = request.host.split(':')[0]  # Remove port if present
    
    # If it's localhost or 127.0.0.1, try to get actual IP
    if host in ['localhost', '127.0.0.1', '0.0.0.0']:
        # Try to get from X-Forwarded-Host header (if behind proxy)
        forwarded_host = request.headers.get('X-Forwarded-Host')
        if forwarded_host:
            return forwarded_host.split(':')[0]
        
        # Try to get from Host header
        if request.headers.get('Host'):
            return request.headers.get('Host').split(':')[0]
        
        # If still localhost, try to get actual server IP
        try:
            # Connect to a remote address to get local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                return local_ip
        except Exception:
            # Fall back to localhost if all else fails
            return 'localhost'
    
    return host


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename to make it safe for filesystem use."""
    if not filename:
        return "unnamed"
    
    # Remove or replace dangerous characters
    dangerous_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    sanitized = filename
    
    for char in dangerous_chars:
        sanitized = sanitized.replace(char, '_')
    
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip('. ')
    
    # Ensure it's not empty after sanitization
    if not sanitized:
        return "unnamed"
    
    # Limit length to reasonable size
    if len(sanitized) > 255:
        name, ext = os.path.splitext(sanitized)
        max_name_length = 255 - len(ext)
        sanitized = name[:max_name_length] + ext
    
    return sanitized


def is_allowed_file_type(filename: str) -> bool:
    """Check if file type is allowed based on extension."""
    if not filename or '.' not in filename:
        return False
    
    extension = filename.rsplit('.', 1)[1].lower()
    allowed_extensions = current_app.config.get('ALLOWED_EXTENSIONS', set())
    return extension in allowed_extensions


def validate_upload_size(file_size: int) -> bool:
    """Check if file size is within allowed limits."""
    max_size = current_app.config.get('MAX_CONTENT_LENGTH', 0)
    return file_size <= max_size if max_size > 0 else True