# Video2Notes

Transform presentation videos into structured notes with key screenshots and speaker identification.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp config/.env.sample .env
# Edit .env with your API keys

# Run application
./start_web_app.sh
# Or: python run_app.py

# Access at http://localhost:5100
```

## Features

- **Video Processing Pipeline**: Upload → Preprocess → Extract slides → Transcribe → Label speakers → Generate notes
- **Interactive Interfaces**: Visual slide selection and speaker labeling with audio playback
- **Multiple Input Sources**: Local upload, file browser, or SharePoint integration
- **AI Enhancement**: WhisperX transcription with speaker diarization and optional LLM refinement
- **Smart Features**: Domain vocabulary extraction from slides, real-time progress monitoring

## Project Structure

```
video2notes/
├── app/                    # Flask web application
│   ├── models/            # State management
│   ├── services/          # Business logic
│   ├── routes/            # API endpoints
│   ├── templates/         # HTML templates
│   ├── static/            # CSS/JS assets
│   └── utils/             # Utilities
├── scripts/               # Processing scripts
│   ├── preprocess-video.py
│   ├── extract-slides.py
│   ├── transcribe-audio.py
│   ├── generate-notes.py
│   └── ...
├── .env.sample                # Configuration  
├── docs/                  # Documentation
│   └── API.md            
├── start_web_app.sh      # Application launcher
├── run_app.py            # Flask entry point
└── utils.py              # Shared utilities
```

## Configuration

### Required Environment Variables

```bash
# Authentication
HF_TOKEN=your_huggingface_token        # Required for transcription

# Optional - LLM
V2N_API_KEY=your_openai_key         # For LLM refinement

# Optional - Local Whipser Model
LOCAL_WHISPER_MODEL=/path/to/model     # Local Whisper model
LOCAL_DIARIZE_MODEL=/path/to/model     # Local diarization model

# Optional - SharePoint
SHAREPOINT_URL=https://your.sharepoint.com/path

# Optional - Misc
FLASK_SECRET_KEY=your_secret_key
```

### SharePoint Setup

```bash
# Generate authentication session
playwright codegen --save-storage=sharepoint_session.json
# Log into SharePoint in the browser that opens
# Close browser when done
```

## Output Structure

```
video_output_YYYYMMDD_HHMMSS/
├── video.m4a                          # Extracted audio
├── slides_video_YYYYMMDD_HHMMSS/      # Slides directory
│   ├── slides.json                    # Selected slides metadata
│   ├── vocabulary.txt                 # Extracted vocabulary
│   └── slide_*.png                    # Slide images
├── transcript/
│   └── video.json                     # Transcription with timestamps
├── video_notes.md                     # Generated notes
├── video_notes_with_speakernames.md   # Notes with speaker labels
├── refined_video_notes.md             # AI-refined notes (optional)
└── video_output.zip                   # Complete package
```

## API Documentation

See [docs/API.md](docs/API.md) for detailed API endpoint documentation.

## Development

```bash
# Run tests (when available)
pytest

# Check logs
tail -f logs/app_*.log
```

## License

MIT License - see LICENSE file for details
