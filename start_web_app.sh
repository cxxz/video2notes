#!/bin/bash

echo "🚀 Starting Video2Notes Web Application"
echo "=================================================="

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed"
    exit 1
fi

# Check if refactored app structure exists
if [ ! -d "app" ]; then
    echo "❌ App directory not found - please ensure you're using the refactored version"
    echo "   If you want to use the original app.py, use: python app.py"
    exit 1
fi

# Check if templates exist in the new location
if [ ! -f "app/templates/index.html" ] || [ ! -f "app/templates/workflow.html" ]; then
    echo "❌ Template files not found in app/templates/ directory"
    echo "Please ensure the refactored templates are in place"
    exit 1
fi

# Check if main scripts exist (these are still used by the workflow service)
REQUIRED_SCRIPTS=("preprocess-video.py" "extract-slides.py" "transcribe-audio.py" "generate-notes.py" "refine-notes.py")

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

# Create logs directory if it doesn't exist
mkdir -p logs

# Start the application
echo "🎬 Starting Video2Notes Web Application..."

# Run the refactored Flask app
python run_app.py 2>&1 | tee logs/app_$(date +%Y%m%d_%H%M%S).log 
