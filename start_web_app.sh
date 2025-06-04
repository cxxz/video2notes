#!/bin/bash

# Video2Notes Web Application Startup Script

echo "🚀 Starting Video2Notes Web Application"
echo "================================="

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed"
    exit 1
fi

# Check if Flask is installed
if ! python3 -c "import flask" &> /dev/null; then
    echo "📦 Installing Flask requirements..."
    pip3 install -r requirements_web.txt
fi

## if templates folder does not exist, create it
if [ ! -d "templates" ]; then
    echo "❌ Template folder not found"
    exit 1
fi

# Check if templates exist
if [ ! -f "templates/index.html" ] || [ ! -f "templates/workflow.html" ]; then
    echo "❌ Template files not found in templates/ directory"
    echo "Please ensure index.html and workflow.html are in the templates/ folder"
    exit 1
fi

# Check if main scripts exist
REQUIRED_SCRIPTS=("01-preprocess.py" "02-extract-slides.py" "03-transcribe.py" "04-generate-notes.py" "05-label-speakers.py" "06-refine-notes.py" "slides_selector.py")

for script in "${REQUIRED_SCRIPTS[@]}"; do
    if [ ! -f "$script" ]; then
        echo "❌ Required script $script not found"
        exit 1
    fi
done

echo "✅ All required files found"

# Set environment variables if .env exists
if [ -f ".env" ]; then
    echo "📝 Loading environment variables from .env"
    export $(grep -v '^#' .env | xargs)
fi

# Check required environment variables
if [ -z "$HF_TOKEN" ]; then
    echo "⚠️  Warning: HF_TOKEN environment variable not set"
    echo "   This is required for Whisper transcription and speaker diarization"
fi

# Display network information
echo ""
echo "🌐 Network Information:"
echo "   Main Application:    http://localhost:5001"
echo "   Slide Selector:      http://localhost:5002 (auto-launched)"
echo "   Speaker Labeler:     http://localhost:5006 (auto-launched)"
echo ""
echo "📁 Upload Information:"
echo "   Users can now upload video files directly through the web interface"
echo "   Supported formats: MP4, AVI, MOV, MKV, WMV, FLV, WebM, M4V, MPG, MPEG"
echo "   Maximum file size: 2GB"
echo ""

# Create logs directory
mkdir -p logs

# Start the application
echo "🎬 Starting Video2Notes Web Application..."
echo "   Access the application at: http://localhost:5000"
echo "   Press Ctrl+C to stop the application"
echo ""

# Run the Flask app
python3 app.py 2>&1 | tee logs/app_$(date +%Y%m%d_%H%M%S).log 