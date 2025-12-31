"""
Configuration management for Video2Notes application.
"""
import os
from typing import List, Set


def _parse_safe_browse_dirs() -> List[str]:
    """Parse safe browse directories from environment or use defaults.

    Environment variable SAFE_BROWSE_DIRS should be colon-separated paths.
    Example: SAFE_BROWSE_DIRS="~:/data:/projects"
    """
    env_dirs = os.getenv('SAFE_BROWSE_DIRS', '')
    if env_dirs:
        # Parse colon-separated paths from environment
        dirs = [d.strip() for d in env_dirs.split(':') if d.strip()]
        # Expand user home directory references
        return [os.path.expanduser(d) for d in dirs]
    # Default: user home directory only (more restrictive)
    return [os.path.expanduser('~')]


class Config:
    """Base configuration class."""
    
    # Flask configuration
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', '/tmp/video2notes_uploads')
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_UPLOAD_SIZE', 2 * 1024 * 1024 * 1024))  # 2GB default
    
    # Server configuration
    MAIN_APP_PORT = int(os.getenv('MAIN_APP_PORT', 5100))
    LOCAL_SERVER = os.getenv('LOCAL_SERVER', 'false').lower() == 'true'
    
    # File handling configuration
    ALLOWED_EXTENSIONS: Set[str] = {
        'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpg', 'mpeg'
    }
    
    # Safe directories for file browsing
    # Configurable via SAFE_BROWSE_DIRS env var (colon-separated paths)
    SAFE_BROWSE_DIRS: List[str] = _parse_safe_browse_dirs()
    
    # SharePoint configuration
    SHAREPOINT_URL = os.getenv('SHAREPOINT_URL')
    
    # AI/ML Model configuration
    LOCAL_WHISPER_MODEL = os.getenv('LOCAL_WHISPER_MODEL')
    LOCAL_DIARIZE_MODEL = os.getenv('LOCAL_DIARIZE_MODEL')
    REFINE_NOTES_LLM = os.getenv('REFINE_NOTES_LLM', 'openai/gpt-oss-120b')
    
    # Allowed LLM models for note refinement
    ALLOWED_LLM_MODELS: List[str] = [
        'openai/gpt-oss-120b',
        'azure/gpt-5.1',
    ]
    
    # File cleanup configuration
    FILE_CLEANUP_AGE_HOURS = 24
    ZIP_CACHE_DURATION_SECONDS = 60
    
    @classmethod
    def init_directories(cls) -> None:
        """Initialize required directories."""
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
        # Add upload folder to safe browse directories
        if cls.UPLOAD_FOLDER not in cls.SAFE_BROWSE_DIRS:
            cls.SAFE_BROWSE_DIRS.append(cls.UPLOAD_FOLDER)


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    UPLOAD_FOLDER = '/tmp/test_video2notes_uploads'


# Configuration mapping
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
