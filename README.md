# Convert Presentation Videos into Slide-Integrated Notes

## Overview

This project transforms videos of lectures or presentations into structured, text-based notes with integrated screenshots and speaker identification. The workflow includes video preprocessing, slide extraction with intelligent selection, audio transcription with vocabulary enhancement, speaker labeling, note generation, and optional refinement using Large Language Models.

## Workflow

### 0. **Split Video into Clips (Optional)**
   - **Script**: [`00-split-video.py`](00-split-video.py)
   - **Description**: Split your video into smaller segments based on timestamps.

### 1. **Preprocess Video**
   - **Script**: [`01-preprocess.py`](01-preprocess.py)
   - **Description**: Select Regions of Interest (ROIs) from video frames and extract audio.
   - **Usage**:
     ```sh
     python 01-preprocess.py -i <video_path> [-t <timestamp>] [-o <output_path>] [-s] [-a]
     ```
   - **Arguments**:
     - `-i, --video_path`: Path to the video file (required)
     - `-t, --timestamp`: Initial timestamp in seconds (default: 60)
     - `-o, --output`: Path to save the ROI data as JSON (default: current directory)
     - `-s, --silent`: Skip ROI selection and use entire frame as slide area
     - `-a, --audio`: Extract audio from the video

### 2. **Extract Slides**
   - **Script**: [`02-extract-slides.py`](02-extract-slides.py)
   - **Description**: Extract unique slides from video based on visual similarity analysis.
   - **Usage**:
     ```sh
     python 02-extract-slides.py -i <video_path> [-j <roi_json>] [-o <output_folder>] [--select]
     ```
   - **Arguments**:
     - `-i, --video_path`: Path to the video file (required)
     - `-j, --roi_json`: Path to the ROI JSON file
     - `-o, --output_folder`: Output folder to save slides
     - `-s, --start_seconds`: Start time in seconds (default: 1)
     - `-e, --end_seconds`: End time in seconds
     - `-f, --frame_rate`: Extract one frame every N seconds (default: 1)
     - `-t, --similarity_threshold`: Threshold for perceptual hash difference (default: 13)
     - `--select`: Launch slide selector web app after extraction

### 2.5. **Select and Curate Slides (Interactive)**
   - **Script**: [`slides_selector.py`](slides_selector.py)
   - **Description**: Web-based interface to select relevant slides and extract vocabulary.
   - **Usage**:
     ```sh
     python slides_selector.py <folder_path>
     ```
   - **Features**:
     - Visual slide selection interface
     - Automatic vocabulary extraction from slide text
     - Slide archiving options
     - Backup original slides.json as ori_slides.json
     - OCR text compilation for selected slides

### 3. **Transcribe Audio**
   - **Script**: [`03-transcribe.py`](03-transcribe.py)
   - **Description**: Transcribe audio using WhisperX with speaker diarization and vocabulary enhancement.
   - **Usage**:
     ```sh
     python 03-transcribe.py -a <audio_path> [-s <slides_dir>] [-o <output_path>] [-f <format>] [-m <model_id>]
     ```
   - **Arguments**:
     - `-a, --audio_path`: Path to the audio file (required)
     - `-s, --slides_dir`: Path to slides directory (for vocabulary.txt)
     - `-o, --output`: Output directory for transcriptions (default: current directory)
     - `-m, --model_id`: Whisper model ID or local path (default: large-v3)

### 4. **Generate Notes**
   - **Script**: [`04-generate-notes.py`](04-generate-notes.py)
   - **Description**: Generate Markdown notes by merging transcript and slide screenshots.
   - **Usage**:
     ```sh
     python 04-generate-notes.py -t <transcript_path> -s <screenshots_path> -o <output_path>
     ```
   - **Arguments**:
     - `-t, --transcript`: Path to the transcript JSON file (required)
     - `-s, --screenshots`: Path to the screenshots JSON file (required)
     - `-o, --output`: Path to save the output Markdown file (required)

### 5. **Label Speakers (Interactive)**
   - **Script**: [`05-label-speakers.py`](05-label-speakers.py)
   - **Description**: Web-based interface to label speakers in the transcript with audio playback.
   - **Usage**:
     ```sh
     python 05-label-speakers.py -a <audio_file> -t <transcript_path>
     ```
   - **Arguments**:
     - `-a, --audio_file`: Path to the audio file (required)
     - `-t, --transcript_path`: Path to the transcript markdown file (required)
   - **Features**:
     - Automatic browser opening
     - Audio segment playback for each speaker
     - Custom speaker name assignment (formats as "Speaker - Name")
     - Default to original speaker IDs if no name provided
     - Web-based close button functionality

### 6. **Refine Notes (Optional)**
   - **Script**: [`06-refine-notes.py`](06-refine-notes.py)
   - **Description**: Refine generated notes using Large Language Models for better structure and clarity.
   - **Usage**:
     ```sh
     python 06-refine-notes.py -i <input_markdown> [-o <output_folder>] [-m <model>] [--max_chars <max_chars>]
     ```
   - **Arguments**:
     - `-i, --input`: Path to the input Markdown file (required)
     - `-o, --output`: Folder to save refined Markdown file (default: current directory)
     - `-m, --model`: LLM model for refinement (default: bedrock/claude-4-sonnet)
     - `--max_chars`: Maximum characters to process in one request

## Run the Entire Workflow

### **Automated Workflow Runner**
- **Script**: [`run_workflow.py`](run_workflow.py)
- **Description**: Orchestrates all steps with interactive prompts and intelligent file routing.
- **Usage**:
  ```sh
  python run_workflow.py
  ```
- **Features**:
  - Interactive prompts for all options
  - Tab completion for file paths
  - Optional video splitting
  - Optional ROI selection
  - Speaker labeling (enabled by default)
  - Optional note refinement
  - Automatic file path management
  - Error handling and continuation

## Key Features

### **Smart Workflow Integration**
- Speaker labeling runs before note refinement for better final output
- Vocabulary from slides automatically enhances transcription accuracy
- Intelligent file routing between steps
- Backup and archive functionality

### **Interactive Web Interfaces**
- **Slide Selector**: Visual selection of relevant slides with vocabulary extraction
- **Speaker Labeler**: Audio-enhanced speaker identification and naming

### **Enhanced Transcription**
- Speaker diarization with customizable names
- Domain-specific vocabulary integration

## Environment Variables

- **`V2N_BASE_URL`**: Base URL for custom OpenAI-compatible custom endpoint
- **`HF_TOKEN`**: Hugging Face token for Whisper and diarization models
- **Additional API keys**: Configure in `.env` file for various LLM providers

## Installation

1. Clone the repository:
   ```sh
   git clone <repository_url>
   cd <repository_directory>
   ```

2. Install dependencies:
   ```sh
   pip install -r requirements.txt
   ```

3. Set up environment variables:
   ```sh
   cp .env.example .env
   # Edit .env with your API keys
   ```

4. Run the workflow:
   ```sh
   python run_workflow.py
   ```

## Output Structure

```
video_output_YYYYMMDD_HHMMSS/
├── video_name.m4a                    # Extracted audio
├── video_name_rois.json              # ROI coordinates
├── slides_video_name_YYYYMMDD_HHMMSS/ # Slide images and metadata
│   ├── slides.json                   # Selected slides metadata
│   ├── ori_slides.json              # Original slides backup
│   ├── vocabulary.txt               # Extracted vocabulary
│   └── slide_*.png                  # Individual slide images
├── transcript/                       # Transcription files
│   └── video_name.json              # Detailed transcript with speakers
├── video_name_notes.md              # Initial generated notes
├── video_name_notes_with_speakernames.md  # Notes with labeled speakers
└── video_name_notes_refined.md     # Final refined notes (optional)
```

