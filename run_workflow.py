import os
import subprocess
import argparse
from datetime import datetime
import time

try:
    import readline
except ImportError:
    import pyreadline3 as readline

def complete_filepath(text, state):
    """Tab completion function for filepath"""
    if '~' in text:
        text = os.path.expanduser(text)
    
    dirname = os.path.dirname(text)
    basename = os.path.basename(text)
    
    if dirname == '':
        dirname = '.'
    
    try:
        ls = os.listdir(dirname)
    except OSError:
        return None
    
    if not basename:
        completions = ls
    else:
        completions = [f for f in ls if f.startswith(basename)]
    
    if dirname != '.':
        completions = [os.path.join(dirname, f) for f in completions]
    
    try:
        return completions[state]
    except IndexError:
        return None

def ask_yes_no(prompt, default=None):
    """Get yes/no input from user with an optional default value."""
    if default is not None:
        prompt = f"{prompt} (y/n) [default: {default}]: "
    else:
        prompt = f"{prompt} (y/n): "
    
    while True:
        response = input(prompt).lower().strip()
        if response == '' and default is not None:
            return default.lower() == 'y'
        if response in ['y', 'n']:
            return response == 'y'

def ask_timestamp(prompt):
    """Get timestamp input from user with validation."""
    while True:
        try:
            value = float(input(prompt))
            if value >= 0:
                return value
            print("Please enter a non-negative number.")
        except ValueError:
            print("Please enter a valid number.")

def execute_command(command, description):
    """Run a command and handle its output."""
    print(f"\n=== {description} ===")
    print(f"Running command: {' '.join(command)}")
    start_time = time.time()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        print(line, end="")
    retcode = process.wait()
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"{description} took {elapsed_time:.2f} seconds.")
    return retcode == 0

def main():
    """
    Main entry point for running the video2notes workflow.
    Handles user input, path completion, and orchestrates all steps.
    """
    # Enable tab completion for file paths
    readline.set_completer_delims(' \t\n;')
    readline.parse_and_bind('tab: complete')
    readline.set_completer(complete_filepath)
    
    # Create timestamp for output folders
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Get input video path with tab completion enabled
    video_path = input("Enter the path to your input video: ").strip()
    video_path = os.path.expanduser(video_path)  # Expand ~ to home directory
    if not os.path.exists(video_path):
        print(f"Error: Video file {video_path} does not exist.")
        return

    # Create output directory
    base_dir = os.path.dirname(video_path)
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    output_dir = os.path.join(base_dir, f"{video_name}_output_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    print(f"\nOutput directory: {output_dir}")

    # Step 0: Split video (optional)
    do_split = ask_yes_no("Do you want to split the video into segments?", default='n')
    if do_split:
        timestamp_file = input("Enter the path to timestamp file: ").strip()
        if not os.path.exists(timestamp_file):
            print(f"Error: Timestamp file {timestamp_file} does not exist.")
            return
        
        if not execute_command(
            ["python", "00-split-video.py", video_path, timestamp_file],
            "Splitting video"
        ):
            return

    # Step 1: Preprocess
    # Ask about audio extraction
    extract_audio = ask_yes_no("Do you want to extract audio from the video?", default='y')
    
    # Ask about ROI selection
    skip_roi = ask_yes_no("Do you want to skip ROI selection? (This will use the entire frame as slide)", default='y')
    
    roi_timestamp = None
    if not skip_roi:
        if ask_yes_no("Do you want to specify an initial timestamp for ROI selection?"):
            roi_timestamp = ask_timestamp("Enter timestamp in seconds: ")

    preprocess_cmd = [
        "python", "01-preprocess.py",
        "-i", video_path,
        "-o", output_dir
    ]
    
    if extract_audio:
        preprocess_cmd.append("-a")
    if skip_roi:
        preprocess_cmd.append("-s")
    if roi_timestamp is not None:
        preprocess_cmd.extend(["-t", str(roi_timestamp)])

    if not execute_command(preprocess_cmd, "Preprocessing video"):
        return

    # Step 2: Extract slides
    rois_path = os.path.join(output_dir, f"{video_name}_rois.json")
    slides_dir = os.path.join(output_dir, f"slides_{video_name}_{timestamp}")
    os.makedirs(slides_dir, exist_ok=True)

    if not execute_command(
        ["python", "02-extract-slides.py", 
         "-i", video_path,
         "-j", rois_path,
         "-o", slides_dir],
        "Extracting slides"
    ):
        return

    # Step 3: Transcribe
    audio_path = os.path.join(output_dir, f"{video_name}.m4a")
    transcript_dir = os.path.join(output_dir, "transcript")
    os.makedirs(transcript_dir, exist_ok=True)

    if not execute_command(
        ["python", "03-transcribe.py",
         "-i", audio_path,
         "-o", transcript_dir,
         "-f", "json"],
        "Transcribing audio"
    ):
        return

    # Step 4: Generate notes
    transcript_json = os.path.join(transcript_dir, f"{video_name}.json")
    slides_json = os.path.join(slides_dir, "slides.json")
    notes_path = os.path.join(output_dir, f"{video_name}_notes.md")

    if not execute_command(
        ["python", "04-generate-notes.py",
         "-t", transcript_json,
         "-s", slides_json,
         "-o", notes_path],
        "Generating notes"
    ):
        return

    # Step 5: Refine notes
    if not execute_command(
        ["python", "05-refine-notes.py",
         "-i", notes_path,
         "-o", output_dir],
        "Refining notes"
    ):
        return

    print("\n=== Workflow completed successfully! ===")
    print(f"Final output directory: {output_dir}")

if __name__ == "__main__":
    main()
