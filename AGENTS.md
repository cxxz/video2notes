# AGENTS.md

This file provides guidance to coding agent such as Opencode, Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Video2Notes is a Flask web application that transforms presentation videos into structured markdown notes with key screenshots and speaker identification. It processes videos through a multi-step pipeline: audio extraction, slide detection, transcription with speaker diarization (WhisperX), interactive editing, and optional LLM-based refinement.

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.sample .env
# Edit .env - HF_TOKEN (Hugging Face) required for transcription

# Run the app (port 5100)
./start_web_app.sh
# OR
python run_app.py
```

## Architecture

### Flask Blueprint Structure
- **`app/routes/`** - API endpoints organized by feature (main, workflow, files, slides, speakers)
- **`app/services/`** - Business logic layer; `workflow_service.py` orchestrates the entire pipeline
- **`app/models/`** - State management classes (WorkflowState singleton is the core state container)
- **`app/utils/`** - Shared utilities (command execution, file operations, security)

### Processing Pipeline
The workflow runs in a background thread with these steps:
1. Preprocess video (extract audio, detect slide ROI)
2. Extract unique slides (image hashing for deduplication)
3. **Interactive pause** - User selects relevant slides via web UI
4. Transcribe audio with WhisperX (speaker diarization)
5. **Interactive pause** - User labels speakers
6. Generate markdown notes
7. Optional LLM refinement

### State Management
- `WorkflowState` (`app/models/workflow_state.py`) is a thread-safe singleton managing workflow lifecycle
- Interactive pauses use file-based synchronization (e.g., `slides.json` written by UI triggers resume)
- Progress updates delivered via Server-Sent Events (SSE) at `/workflow/progress_stream`

### Scripts Directory
`scripts/` contains standalone processing scripts called via subprocess:
- `preprocess-video.py` - Audio extraction and ROI detection
- `extract-slides.py` - Slide deduplication using image hashing
- `transcribe-audio.py` - WhisperX transcription with diarization
- `generate-notes.py` - Markdown generation
- `refine-notes.py` - LLM-based refinement (supports Claude, GPT, Azure)

## Key Dependencies

- **WhisperX** - Speech-to-text with speaker diarization (requires HF_TOKEN)
- **OpenCV/MoviePy** - Video/audio processing
- **ImageHash/Tesseract** - Slide deduplication and OCR
- **Anthropic SDK** - Claude models (Bedrock supported)
- **Playwright** - SharePoint video downloads (optional feature)

## Configuration

- `app/config.py` - Environment-based configuration (dev/prod/test)
- `.env` - API keys, model settings, feature flags (see `.env.sample`)
- LLM model allowlist defined in `app/config.py`

## Common Patterns

- Long-running tasks execute in background threads, not blocking Flask requests
- File operations use `app/utils/security.py` for path validation
- Subprocess calls to scripts use `app/utils/command_executor.py`
- Debug endpoints available at `/debug/*` in development mode
