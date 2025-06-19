# Video2Notes: Converting Presentation Videos into Slide-Integrated Notes

## Overview

**Video2Notes** is an integrated web application that transforms lecture or presentation videos into structured, text-based notes with slide screenshots and speaker identification. The app provides a seamless, interactive workflow for:

- Video upload (local or SharePoint)
- Video preprocessing and audio extraction
- Slide extraction and visual selection
- OCR and domain vocabulary extraction
- Audio transcription with speaker diarization
- Speaker labeling with audio playback
- Markdown note generation and optional LLM-based refinement

All steps are orchestrated via a modern Flask web interface (`app.py`), with real-time progress, interactive slide/speaker selection, and download of results.

## Quick Start

1. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```
2. **Set up environment variables:**
   - Copy `.env.example` to `.env` and fill in your API keys (OpenAI, HuggingFace, etc.)
3. **Run the web app:**
   ```sh
   python app.py
   ```
   - The app will be available at `http://localhost:5100` (or the port set in your `.env`)

## Web App Features (`app.py`)

### Unified Workflow
- **Single web interface** for the entire pipeline: upload, configure, run, monitor, and download.
- **Interactive forms** for workflow configuration (video source, options, LLM model, etc.)
- **Real-time progress** and logs via server-sent events.
- **Download center** for all generated outputs (audio, slides, transcript, notes, ZIP, etc.).

### Video Input
- **Upload**: Drag-and-drop or browse for local video files (large file support, 2GB+).
- **SharePoint**: Browse and download videos directly from SharePoint (with authentication).

### Slide Extraction & Selection
- **Automatic slide extraction** from video using visual similarity.
- **Integrated slide selector**: visually select/curate slides in-browser.
- **OCR and vocabulary extraction**: extract domain-specific terms from slides for improved transcription.

### Audio Transcription & Speaker Diarization
- **Audio extraction** from video (supports .mp4, .mkv, etc.).
- **Transcription** using WhisperX (local or cloud), with optional vocabulary enhancement.
- **Speaker diarization** and labeling.

### Speaker Labeling (Interactive)
- **Web-based speaker labeler**: listen to audio segments, assign real names to speakers, and update transcript.

### Note Generation & Refinement
- **Markdown note generation**: integrates transcript and slide images.
- **Optional LLM-based refinement**: further improve notes using your choice of LLM (e.g., Claude, GPT-4).

### Download & Output
- **Download all results**: audio, slides, transcript, notes, refined notes, and ZIP archive.
- **Output structure** mirrors the classic CLI workflow (see below).


## Classic CLI Workflow (for reference)

The web app orchestrates the following scripts (also usable standalone):

1. `preprocess-video.py` – Preprocess video, extract audio, select ROI
2. `extract-slides.py` – Extract unique slides from video
3. `slides_selector.py` – (Now integrated) Visual slide selection and vocabulary extraction
4. `transcribe-audio.py` – Transcribe audio with WhisperX, speaker diarization, vocabulary
5. `generate-notes.py` – Generate Markdown notes from transcript and slides
6. `label-speakers.py` – (Now integrated) Assign real names to speakers in transcript
7. `refine-notes.py` – (Optional) Refine notes with LLM


## Output Structure

```
video_name_output_YYYYMMDD_HHMMSS/
├── video_name.m4a / .mp3                # Extracted audio
├── video_name_rois.json                 # ROI coordinates
├── slides_video_name_YYYYMMDD_HHMMSS/   # Slide images and metadata
│   ├── slides.json                      # Selected slides metadata
│   ├── slides_original.json / ori_slides.json # Original slides backup
│   ├── vocabulary.txt                   # Extracted vocabulary
│   └── slide_*.png                      # Individual slide images
├── transcript/
│   └── video_name.json                  # Detailed transcript with speakers
├── video_name_notes.md                  # Initial generated notes
├── video_name_notes_with_speakernames.md # Notes with labeled speakers
├── video_name_notes_refined.md          # Final refined notes (optional)
└── video_name_output_YYYYMMDD_HHMMSS.zip # ZIP archive of all outputs
```

## Environment Variables

Set these in your `.env` file:

- `FLASK_SECRET_KEY` – Flask session secret
- `UPLOAD_FOLDER` – Where uploads are stored (default: `/tmp/video2notes_uploads`)
- `MAX_UPLOAD_SIZE` – Max upload size in bytes (default: 2GB)
- `MAIN_APP_PORT` – Port for the web app (default: 5100)
- `LOCAL_WHISPER_MODEL` – Path or ID for local Whisper model (optional)
- `LOCAL_DIARIZE_MODEL` – Path or ID for local diarization model (optional)
- `V2N_BASE_URL`, `HF_TOKEN`, etc. – API keys for LLMs and transcription

## License

This project is licensed under the MIT License. 

