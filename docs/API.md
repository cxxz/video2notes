# Video2Notes API Documentation

## Overview

Video2Notes provides a RESTful API organized via Flask blueprints for managing video processing workflows, file operations, and interactive components.

## Base URL

```
http://localhost:5100
```

## API Endpoints

### Core Workflow Routes

#### GET /
Main application page with video upload and workflow configuration interface.

#### POST /workflow/start
Start a new video processing workflow.

**Request Body:**
```json
{
  "video_path": "/path/to/video.mp4",
  "extract_audio": true,
  "skip_roi": false,
  "roi_timestamp": 300,
  "do_label_speakers": true,
  "do_refine_notes": true,
  "refine_notes_llm": "openai/gpt-4o-2024-08-06",
  "do_split": false,
  "timestamp_file": null
}
```

**Response:**
```json
{
  "success": true
}
```

#### GET /workflow/progress
Workflow progress page with real-time updates via Server-Sent Events.

#### GET /workflow/status
Get current workflow status as JSON.

**Response:**
```json
{
  "status": "running",
  "progress": 45,
  "current_step": "Transcribing audio",
  "logs": ["🚀 Workflow started", "📹 Processing video..."],
  "interactive_stage": null,
  "available_files": []
}
```

#### POST /workflow/stop
Stop the current running workflow.

**Response:**
```json
{
  "success": true
}
```

### File Management Routes

#### POST /files/upload
Upload a video file for processing.

**Request:**
- Method: POST
- Content-Type: multipart/form-data
- Body: Video file

**Response:**
```json
{
  "success": true,
  "filename": "uploaded_video.mp4",
  "path": "/path/to/uploaded_video.mp4"
}
```

#### GET /files/browse
Browse available files on the server.

**Query Parameters:**
- `path` - Directory path to browse (optional)

**Response:**
```json
{
  "files": [
    {
      "name": "video1.mp4",
      "path": "/videos/video1.mp4",
      "size": 1048576,
      "type": "file"
    }
  ],
  "current_path": "/videos"
}
```

#### GET /download/<filename>
Download generated files.

**Parameters:**
- `filename` - Name of the file to download

**Response:**
- Binary file download

### SharePoint Integration Routes

#### POST /files/sharepoint/get-download-links
Get download links for a SharePoint video.

**Request Body:**
```json
{
  "sharepoint_video_url": "https://sharepoint.com/video.mp4"
}
```

#### POST /files/sharepoint/download
Download a video from SharePoint.

**Request Body:**
```json
{
  "direct_download_link": "https://sharepoint.com/direct/video.mp4",
  "output_filename": "video.mp4"
}
```

#### GET /files/sharepoint/download-progress
Get SharePoint download progress via SSE.

### Interactive Component Routes

#### Slide Selection Routes (/slides/)

##### GET /slides/selector
Open the interactive slide selection interface.

##### POST /slides/save
Save selected slides.

**Request Body:**
```json
{
  "selected_slides": [0, 2, 5, 8]
}
```

##### POST /slides/update-vocabulary
Enable/disable vocabulary extraction from slides.

**Request Body:**
```json
{
  "extract_vocabulary": true
}
```

##### GET /slides/download-vocabulary
Download extracted vocabulary file.

#### Speaker Labeling Routes (/speakers/)

##### GET /speakers/labeler
Open the interactive speaker labeling interface.

##### POST /speakers/get-speakers
Get list of speakers from the transcript.

##### POST /speakers/get-audio-segment
Get audio segment for a specific utterance.

**Request Body:**
```json
{
  "start": 10.5,
  "end": 15.3
}
```

##### POST /speakers/label-speaker
Label a speaker with a name.

**Request Body:**
```json
{
  "speaker_id": "SPEAKER_00",
  "speaker_name": "John Doe"
}
```

##### POST /speakers/save-labeled-notes
Save the notes with labeled speaker names.

## Server-Sent Events (SSE)

### GET /workflow/stream
Real-time workflow progress updates.

**Event Format:**
```
data: {"progress": 50, "message": "Extracting slides...", "status": "running"}
```

### GET /files/sharepoint/download-progress
Real-time SharePoint download progress.

**Event Format:**
```
data: {"progress": 75, "message": "Downloading: 75%"}
```

## Response Codes

- `200` - Success
- `400` - Bad Request (invalid parameters)
- `404` - Not Found
- `500` - Internal Server Error

## Error Response Format

```json
{
  "success": false,
  "error": "Error message description"
}
```