"""
Centralized constants for Video2Notes application.

All magic numbers and configurable values should be defined here.
Values can be overridden via environment variables where appropriate.
"""
import os

# =============================================================================
# TIMEOUTS (in seconds)
# =============================================================================

# Default timeout for subprocess execution
DEFAULT_SUBPROCESS_TIMEOUT = int(os.getenv('SUBPROCESS_TIMEOUT', 3600))

# Slide selection wait timeout
SLIDE_SELECTION_TIMEOUT = int(os.getenv('SLIDE_SELECTION_TIMEOUT', 3600))

# Speaker labeling wait timeout
SPEAKER_LABELING_TIMEOUT = int(os.getenv('SPEAKER_LABELING_TIMEOUT', 3600))

# AI refinement thread timeout
REFINEMENT_TIMEOUT = int(os.getenv('REFINEMENT_TIMEOUT', 1800))

# =============================================================================
# AUDIO PROCESSING
# =============================================================================

# Maximum audio segment duration for playback (ms)
MAX_AUDIO_SEGMENT_DURATION_MS = 60000

# Padding around audio segments (ms)
DEFAULT_AUDIO_PADDING_MS = 500

# Supported audio file extensions (in priority order)
AUDIO_EXTENSIONS = ['.mp3', '.m4a', '.wav', '.aac', '.flac', '.ogg']

# =============================================================================
# SLIDE EXTRACTION
# =============================================================================

# Image hash similarity threshold for duplicate detection
DEFAULT_SIMILARITY_THRESHOLD = int(os.getenv('SIMILARITY_THRESHOLD', 10))

# Minimum OCR text length to consider a frame as a slide
MIN_OCR_TEXT_LENGTH = 10

# Maximum OCR text length for "mostly names" check
MAX_OCR_TEXT_FOR_NAME_CHECK = 300

# Default frame extraction rate (frames per second)
DEFAULT_FRAME_RATE = 1

# =============================================================================
# LOGGING
# =============================================================================

# Interval between progress log messages (seconds)
LOG_INTERVAL_SECONDS = 60

# =============================================================================
# FILE HANDLING
# =============================================================================

# Maximum filename length
MAX_FILENAME_LENGTH = 255

# Allowed video file extensions
ALLOWED_VIDEO_EXTENSIONS = {
    'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpg', 'mpeg'
}

# =============================================================================
# WHISPERX / TRANSCRIPTION
# =============================================================================

# Batch size for WhisperX (GPU)
WHISPERX_BATCH_SIZE_GPU = int(os.getenv('WHISPERX_BATCH_SIZE_GPU', 32))

# Batch size for WhisperX (CPU)
WHISPERX_BATCH_SIZE_CPU = int(os.getenv('WHISPERX_BATCH_SIZE_CPU', 8))

# Data type for WhisperX
WHISPERX_DTYPE = os.getenv('WHISPERX_DTYPE', 'float16')

# =============================================================================
# LLM / AI
# =============================================================================

# Default LLM for note refinement
DEFAULT_REFINE_NOTES_LLM = os.getenv('REFINE_NOTES_LLM', 'openai/gpt-4')

# Default LLM for vocabulary extraction
DEFAULT_VOCABULARY_LLM = os.getenv('VOCABULARY_LLM', 'azure/gpt-4')

# Chunk sizes for LLM processing
LLM_MIN_CHUNK_CHARS = int(os.getenv('LLM_MIN_CHUNK_CHARS', 2000))
LLM_MAX_CHUNK_CHARS = int(os.getenv('LLM_MAX_CHUNK_CHARS', 3000))
