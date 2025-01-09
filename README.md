# Convert Presentation Videos into Slide-Integrated Notes

## Overview

The goal of this project is to transform videos of lectures or presentations into structured, text-based notes with integrated screenshots. Each step is handled by one of the listed Python scripts, allowing you to split the video (optionally), preprocess it, extract slides, transcribe audio, and generate/refine the final Markdown notes.

## Workflow

0. **Split Video into Clips (Optional)**
   - Uses `00-split-video.py` to slice your video into smaller parts.

1. **Preprocess Video ([`01-preprocess.py`](01-preprocess.py))**
    - **Description**: Select Regions of Interest (ROIs) from a video at a specific timestamp and extract audio.
    - **Usage**:
      ```sh
      python 01-preprocess.py -i <video_path> -t <timestamp> -o <output_path> [-s]
      ```
    - **Arguments**:
      - `-i, --video_path`: Path to the video file.
      - `-t, --timestamp`: Initial timestamp in seconds (default: 60).
      - `-o, --output`: Path to save the ROI data as JSON.
      - `-s, --silent`: Skip ROI selection and set slide ROI to the entire frame.

2. **Extract Slides ([`02-extract-slides.py`](02-extract-slides.py))**
    - **Description**: Extract slides from the video based on the selected ROIs.
    - **Usage**:
      ```sh
      python 02-extract-slides.py -i <video_path> -r <rois_path> -o <output_path>
      ```
    - **Arguments**:
      - `-i, --video_path`: Path to the video file.
      - `-r, --rois_path`: Path to the ROI JSON file.
      - `-o, --output`: Path to save the extracted slides.

3. **Transcribe Audio ([`03-transcribe.py`](03-transcribe.py))**
    - **Description**: Transcribe the audio extracted from the video using Whisper.
    - **Usage**:
      ```sh
      python 03-transcribe.py -a <audio_path> -o <output_path> -f <format> -m <model_id>
      ```
    - **Arguments**:
      - `-a, --audio_path`: Path to the audio file.
      - `-o, --output`: Path to save the transcription.
      - `-f, --format`: Output format (srt, vtt, json).
      - `-m, --model_id`: Whisper model ID.

4. **Generate Notes ([`04-generate-notes.py`](04-generate-notes.py))**
    - **Description**: Generate a Markdown file by merging the transcript and screenshots.
    - **Usage**:
      ```sh
      python 04-generate-notes.py -t <transcript_path> -s <screenshots_path> -o <output_path>
      ```
    - **Arguments**:
      - `-t, --transcript`: Path to the transcript JSON file.
      - `-s, --screenshots`: Path to the screenshots JSON file.
      - `-o, --output`: Path to save the output Markdown file.

5. **Refine Notes ([`05-refine-notes.py`](05-refine-notes.py))**
    - **Description**: Refine the generated Markdown notes using a Large Language Model (LLM).
    - **Usage**:
      ```sh
      python 05-refine-notes.py -i <input_markdown> -o <output_folder> -m <model> [--max_chars <max_chars>]
      ```
    - **Arguments**:
      - `-i, --input`: Path to the input Markdown file.
      - `-o, --output`: Folder to save the output Markdown file.
      - `-m, --model`: LLM model to use for refinement.


## Run the Entire Workflow 
**Using ([`run_workflow.py`](run_workflow.py))**
  - **Description**: Orchestrates all steps (optional video splitting, preprocessing, slide extraction, transcription, note generation, and refinement) in one script.
  - **Usage**:
    ```sh
    python run_workflow.py
    ```
  - **Arguments**: Prompt-based interaction for file paths and optional steps.

## Environment Variables

- `OPENAI_BASE_URL`: Base URL for your OpenAI API (when using Azure or custom endpoints).
- `HF_TOKEN`: Your Hugging Face token necessary for Whisper and diarization models.

## Installation

1. Clone the repository:
   ```sh
   git clone <repository_url>
   cd <repository_directory>
   ```

