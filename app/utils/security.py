"""
Security utility functions for Video2Notes application.
"""
import os
import socket
from typing import List
from flask import current_app, request


def is_safe_path(path: str) -> bool:
    """Check if a path is safe to browse (within allowed directories).

    Validates that the resolved path is within one of the configured safe directories.
    Uses proper path separator checking to prevent prefix matching attacks
    (e.g., /safe/dir123 incorrectly matching /safe/dir1).
    """
    if not path:
        return False

    try:
        real_path = os.path.realpath(path)
        safe_dirs: List[str] = current_app.config['SAFE_BROWSE_DIRS']

        for safe_dir in safe_dirs:
            safe_real_path = os.path.realpath(safe_dir)
            # Check exact match OR path starts with safe_dir + separator
            # This prevents /safe/dir123 from matching /safe/dir1
            if real_path == safe_real_path or real_path.startswith(safe_real_path + os.sep):
                return True
        return False
    except Exception:
        return False


def validate_file_path_security(file_path: str, base_dir: str) -> bool:
    """Validate that a file path is secure and within the base directory.

    Uses proper path separator checking to prevent prefix matching attacks
    (e.g., /safe/dir123 incorrectly matching /safe/dir1).
    """
    try:
        real_base_dir = os.path.realpath(base_dir)
        real_file_path = os.path.realpath(file_path)
        # Check exact match OR path starts with base_dir + separator
        # This prevents /safe/dir123 from matching /safe/dir1
        return real_file_path == real_base_dir or real_file_path.startswith(real_base_dir + os.sep)
    except Exception:
        return False


def get_server_host() -> str:
    """Get the server host/IP address from the request.

    Priority order:
    1. LOCAL_SERVER config -> 'localhost'
    2. SERVER_HOST environment variable (for explicit configuration)
    3. X-Forwarded-Host header (when behind proxy)
    4. Request Host header
    5. socket.gethostname() fallback
    """
    if current_app.config.get('LOCAL_SERVER', False):
        return 'localhost'

    # Allow explicit configuration via environment variable
    configured_host = os.getenv('SERVER_HOST')
    if configured_host:
        return configured_host

    # Try to get the host from the request
    host = request.host.split(':')[0]  # Remove port if present

    # If it's localhost or 127.0.0.1, try to get actual IP
    if host in ['localhost', '127.0.0.1', '0.0.0.0']:
        # Try to get from X-Forwarded-Host header (if behind proxy)
        forwarded_host = request.headers.get('X-Forwarded-Host')
        if forwarded_host:
            return forwarded_host.split(':')[0]

        # Try to get from Host header
        host_header = request.headers.get('Host')
        if host_header and host_header.split(':')[0] not in ['localhost', '127.0.0.1', '0.0.0.0']:
            return host_header.split(':')[0]

        # Fallback: use hostname resolution (doesn't require external connectivity)
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            if local_ip and local_ip != '127.0.0.1':
                return local_ip
        except socket.error:
            pass

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