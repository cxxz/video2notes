import os
import re
import io
import argparse
from flask import Flask, request, render_template_string, redirect, url_for, send_file, abort
from pydub import AudioSegment

app = Flask(__name__)

# Global variables
audio_file = None
audio_duration_ms = 0
transcript_content = ""
utterances = []             # List of all utterances from the transcript
speaker_occurrences = {}    # Dictionary: speaker_id -> list of utterance dicts
speaker_segments = {}       # Dictionary: speaker_id -> (start_ms, end_ms) for chosen segment
speaker_ids = []            # Ordered list of unique speaker_ids (for labeling)
speaker_mapping = {}        # Dictionary: speaker_id -> user-provided speaker name
current_index = 0           # Index to track the current speaker for labeling
output_transcript_path = "" # Path for the updated transcript file

def parse_timestamp(ts_str):
    """
    Convert a timestamp string (e.g., "00:02.692" or "01:42.575") to milliseconds.
    """
    try:
        parts = ts_str.split(':')
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return int((minutes * 60 + seconds) * 1000)
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return int((hours * 3600 + minutes * 60 + seconds) * 1000)
        else:
            raise ValueError("Invalid timestamp format: " + ts_str)
    except Exception as e:
        raise ValueError(f"Error parsing timestamp '{ts_str}': {e}")

def load_transcript(transcript_path):
    """
    Loads the transcript file, parses utterances with regex, computes segment boundaries,
    and groups utterances by speaker ID. For each speaker, applies the rule:
    if the first segment is shorter than 5 seconds and a second exists, use the longer of the two.
    """
    global transcript_content, utterances, speaker_occurrences, speaker_ids

    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            transcript_content = f.read()
    except Exception as e:
        print("Error reading transcript file:", e)
        exit(1)
    
    # Regex to match utterance headers like: **SPEAKER_09 [00:02.692]:**
    pattern = re.compile(r'\*\*(SPEAKER_\d{2}) \[([0-9:.]+)\]:\*\*')
    utterances = []
    for match in pattern.finditer(transcript_content):
        speaker = match.group(1)
        timestamp_str = match.group(2)
        try:
            start_ms = parse_timestamp(timestamp_str)
        except ValueError as e:
            print("Error parsing timestamp:", e)
            continue
        utterances.append({
            "speaker": speaker,
            "timestamp_str": timestamp_str,
            "start_ms": start_ms,
            "header_text": match.group(0),
            "match_start": match.start(),
            "match_end": match.end()
        })
    
    if not utterances:
        print("No utterances found in transcript.")
        exit(1)
    
    # Ensure utterances are in the order they appear in the transcript
    utterances.sort(key=lambda u: u["match_start"])
    
    # Set the end time for each utterance: for utterance i, end is the start of utterance i+1;
    # for the last utterance, use the audio file duration.
    for i in range(len(utterances)):
        if i < len(utterances) - 1:
            utterances[i]["end_ms"] = utterances[i+1]["start_ms"]
        else:
            utterances[i]["end_ms"] = audio_duration_ms
    
    # Group utterances by speaker ID
    speaker_occurrences = {}
    for utt in utterances:
        spk = utt["speaker"]
        if spk not in speaker_occurrences:
            speaker_occurrences[spk] = []
        speaker_occurrences[spk].append(utt)
    
    # Create an ordered list of unique speaker IDs based on first occurrence in the transcript
    speaker_ids = sorted(speaker_occurrences.keys(), key=lambda spk: speaker_occurrences[spk][0]["start_ms"])
    
    # For each speaker, choose a segment based on the rule:
    # If the first segment is shorter than 5 seconds and a second occurrence exists,
    # choose the longer of the two segments.
    for spk, occ_list in speaker_occurrences.items():
        first_utt = occ_list[0]
        duration_first = first_utt["end_ms"] - first_utt["start_ms"]
        chosen = first_utt
        if duration_first < 5000 and len(occ_list) > 1:
            second_utt = occ_list[1]
            duration_second = second_utt["end_ms"] - second_utt["start_ms"]
            chosen = first_utt if duration_first >= duration_second else second_utt
        speaker_segments[spk] = (chosen["start_ms"], chosen["end_ms"])

def update_transcript():
    """
    Replace each speaker header in the transcript with the user-provided speaker name.
    For example, **SPEAKER_09 [00:02.692]:** becomes **Alice [00:02.692]:**
    """
    global transcript_content, speaker_mapping
    updated_content = transcript_content
    # Pattern to match the header portion (speaker ID and timestamp)
    pattern = re.compile(r'\*\*(SPEAKER_\d{2})( \[[0-9:.]+\]:)\*\*')
    def replace_func(match):
        spk = match.group(1)
        rest = match.group(2)
        # Replace with the provided label if available, else leave unchanged.
        label = speaker_mapping.get(spk, spk)
        return f'**{label}{rest}**'
    updated_content = pattern.sub(replace_func, updated_content)
    return updated_content

# Flask Routes

@app.route("/")
def index():
    """
    Displays the current speaker to label with a play button for the associated audio segment.
    """
    global current_index
    if current_index >= len(speaker_ids):
        return redirect(url_for('result'))
    current_speaker = speaker_ids[current_index]
    # HTML page with an audio element and a form for entering the speaker's name.
    html = '''
    <!doctype html>
    <html>
    <head>
        <title>Speaker Labeling</title>
    </head>
    <body>
        <h2>Label Speaker</h2>
        <p><strong>Speaker ID:</strong> {{ speaker_id }}</p>
        <p>
            <audio controls>
                <source src="{{ url_for('play_audio', speaker_id=speaker_id) }}" type="audio/wav">
                Your browser does not support the audio element.
            </audio>
        </p>
        <form action="{{ url_for('label') }}" method="post">
            <input type="hidden" name="speaker_id" value="{{ speaker_id }}">
            <label for="label">Enter Speaker Name:</label>
            <input type="text" id="label" name="label" required>
            <input type="submit" value="Submit">
        </form>
    </body>
    </html>
    '''
    return render_template_string(html, speaker_id=current_speaker)

@app.route("/play/<speaker_id>")
def play_audio(speaker_id):
    """
    Extracts and serves the audio segment corresponding to the given speaker ID.
    """
    segment = speaker_segments.get(speaker_id)
    if segment is None:
        abort(404, description="Audio segment not found for speaker " + speaker_id)
    start_ms, end_ms = segment
    try:
        segment_audio = audio_file[start_ms:end_ms]
    except Exception as e:
        abort(500, description="Error extracting audio segment: " + str(e))
    buffer = io.BytesIO()
    try:
        segment_audio.export(buffer, format="wav")
    except Exception as e:
        abort(500, description="Error exporting audio segment: " + str(e))
    buffer.seek(0)
    return send_file(buffer, mimetype="audio/wav", as_attachment=False, download_name="segment.wav")

@app.route("/label", methods=["POST"])
def label():
    """
    Receives the speaker name from the form, updates the mapping, and moves on to the next speaker.
    """
    global current_index
    speaker_id = request.form.get("speaker_id")
    label_text = request.form.get("label")
    if not speaker_id or not label_text:
        abort(400, description="Missing speaker_id or label")
    speaker_mapping[speaker_id] = label_text
    current_index += 1
    return redirect(url_for('index'))

@app.route("/result")
def result():
    """
    Once all speakers have been labeled, updates the transcript and provides a link to download it.
    """
    updated = update_transcript()
    try:
        with open(output_transcript_path, "w", encoding="utf-8") as f:
            f.write(updated)
    except Exception as e:
        abort(500, description="Error saving updated transcript: " + str(e))
    html = '''
    <!doctype html>
    <html>
    <head>
        <title>Labeling Complete</title>
    </head>
    <body>
        <h2>All speakers have been labeled!</h2>
        <p>The updated transcript has been saved as <strong>{{ output_filename }}</strong>.</p>
        <p><a href="{{ url_for('download_transcript') }}">Download Updated Transcript</a></p>
    </body>
    </html>
    '''
    return render_template_string(html, output_filename=os.path.basename(output_transcript_path))

@app.route("/download")
def download_transcript():
    """
    Serves the updated transcript file for download.
    """
    try:
        return send_file(output_transcript_path, as_attachment=True,
                         download_name=os.path.basename(output_transcript_path), mimetype="text/markdown")
    except Exception as e:
        abort(500, description="Error sending updated transcript file: " + str(e))

def initialize(audio_path, transcript_path):
    """
    Checks that the files exist, loads the audio file, sets the duration,
    and loads & parses the transcript.
    """
    global audio_file, audio_duration_ms, output_transcript_path
    if not os.path.exists(audio_path):
        print("Audio file not found:", audio_path)
        exit(1)
    if not os.path.exists(transcript_path):
        print("Transcript file not found:", transcript_path)
        exit(1)
    try:
        audio_file = AudioSegment.from_file(audio_path)
        audio_duration_ms = len(audio_file)
    except Exception as e:
        print("Error loading audio file:", e)
        exit(1)
    load_transcript(transcript_path)
    
    # Set the output transcript path based on the input transcript path
    output_transcript_path = transcript_path.replace(".md", "_with_speakernames.md")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Speaker Labeling Application")
    parser.add_argument("-a", "--audio_file", type=str, help="Path to the audio file", required=True)
    parser.add_argument("-t", "--transcript_path", type=str, help="Path to the transcript markdown file", required=True)
    args = parser.parse_args()
    initialize(args.audio_file, args.transcript_path)
    # Start the Flask app. In production, consider using a production server.
    app.run(host='0.0.0.0', port=5001, debug=True)
