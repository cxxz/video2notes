# Video2Notes: Converting Presentation Videos into Slide-Integrated Notes

## Overview

**Video2Notes** is a modular web application that transforms lecture or presentation videos into structured, text-based notes with slide screenshots and speaker identification. The application provides a seamless, interactive workflow from video upload to refined notes generation.

## Quick Start

1. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

2. **Set up environment variables:**
   - Copy `.env.example` to `.env` and configure your API keys

3. **Run the application:**
   ```sh
   ./start_web_app.sh
   # OR directly:
   python run_app.py
   ```
   - Access at `http://localhost:5100`

### Legacy Version
For the original monolithic version: `python app.py`

## Architecture

Modern Flask blueprint architecture with proper separation of concerns:

```
app/
├── __init__.py              # Flask app factory
├── config.py               # Configuration management
├── models/                 # State management classes
├── services/               # Business logic services
├── routes/                 # Flask Blueprints (main, workflow, files, slides, speakers)
├── utils/                  # Utility functions
├── templates/              # Jinja2 templates
└── static/                 # Static assets

Core Scripts:
├── run_app.py              # Main application entry point
├── preprocess-video.py     # Video preprocessing
├── extract-slides.py       # Slide extraction
├── transcribe-audio.py     # Audio transcription
├── generate-notes.py       # Note generation
├── refine-notes.py         # Note refinement
└── sharepoint_downloader.py # SharePoint integration
```

## Features

### Complete Workflow Pipeline
1. **Video Input** - Upload, browse files, or download from SharePoint
2. **Video Preprocessing** - Audio extraction and ROI selection
3. **Slide Extraction & Selection** - Visual slide curation with large preview images
4. **Audio Transcription** - WhisperX with speaker diarization and vocabulary enhancement
5. **Interactive Speaker Labeling** - Audio playback and speaker naming
6. **Note Generation** - Markdown notes with integrated slides and speaker names
7. **Optional LLM Refinement** - AI-powered note improvement

### Key Capabilities
- **Real-time progress monitoring** with server-sent events
- **Interactive web interfaces** for slide selection and speaker labeling
- **Multiple video input methods** (upload, file browser, SharePoint)
- **Domain vocabulary extraction** from slide OCR for better transcription
- **Automatic file management** with ZIP packaging and version selection
- **Security features** with path traversal protection

## API Endpoints

Organized via Flask blueprints:

### Core Routes
- `GET /` - Main application page
- `POST /workflow/start` - Start processing workflow
- `GET /workflow/progress` - Workflow progress page with real-time updates
- `POST /workflow/stop` - Stop current workflow

### File Management
- `POST /files/upload` - Upload video files
- `GET /files/browse` - Browse server directories
- `GET /download/<filename>` - Download generated files
- SharePoint integration endpoints under `/files/sharepoint/`

### Interactive Components
- `/slides/` - Slide selection interface and vocabulary extraction
- `/speakers/` - Speaker labeling interface with audio playback

## Output Structure

```
video_name_output_YYYYMMDD_HHMMSS/
├── video_name.m4a                        # Extracted audio
├── video_name_rois.json                  # ROI coordinates
├── slides_video_name_YYYYMMDD_HHMMSS/    # Slide images and metadata
│   ├── slides.json                       # Selected slides
│   ├── vocabulary.txt                    # Domain vocabulary (optional)
│   └── slide_*.png                       # Slide images
├── transcript/
│   └── video_name.json                   # Detailed transcript
├── video_name_notes.md                   # Generated notes
├── video_name_notes_with_speakernames.md # Notes with speaker names
├── refined_video_name_notes.md           # LLM-refined notes (optional)
└── video_name_output.zip                 # Complete archive
```

## Configuration

Set these in your `.env` file:

**Flask & Server:**
- `FLASK_SECRET_KEY` - Flask session secret
- `MAIN_APP_PORT` - Web app port (default: 5100)
- `UPLOAD_FOLDER` - Upload directory (default: `/tmp/video2notes_uploads`)
- `MAX_UPLOAD_SIZE` - Max upload size (default: 2GB)

**AI Models & APIs:**
- `HF_TOKEN` - HuggingFace token for model access
- `LOCAL_WHISPER_MODEL` - Local Whisper model path (optional)
- `LOCAL_DIARIZE_MODEL` - Local diarization model path (optional)
- `OPENAI_API_KEY` - OpenAI API key (if using OpenAI models)
- `SHAREPOINT_URL` - SharePoint site URL for video downloads

## Technical Benefits

- **Modular Architecture**: Easy maintenance and feature additions
- **Thread Safety**: Proper concurrent workflow handling
- **Security**: Path traversal protection and safe file operations
- **Error Handling**: Comprehensive error reporting and recovery
- **Testability**: Services can be unit tested independently

## License

MIT License