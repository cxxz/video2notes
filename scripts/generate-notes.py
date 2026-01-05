import json
import os
import argparse
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def load_json(file_path):
    """
    Load JSON data from a file.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def sort_transcript(transcript):
    """
    Sort transcript entries by their start time.
    """
    return sorted(transcript, key=lambda x: x.get('start', 0))

def sort_screenshots(screenshots):
    """
    Sort screenshots by their timestamp.
    """
    return sorted(screenshots, key=lambda x: x.get('timestamp', 0))

def group_screenshots(screenshots):
    """
    Group screenshots by their group_id.
    Returns a list of groups, each group is a list of screenshots.
    """
    groups = {}
    for screenshot in screenshots:
        group_id = screenshot.get('group_id', 0)
        if group_id not in groups:
            groups[group_id] = []
        groups[group_id].append(screenshot)
    # Sort groups by timestamp
    sorted_groups = sorted(groups.values(), key=lambda group: group[0].get('timestamp', 0))
    return sorted_groups

def generate_markdown(transcript, screenshot_groups, output_path):
    """
    Generate a Markdown file with merged transcript and screenshots.
    """
    md_lines = []
    screenshot_index = 0
    total_groups = len(screenshot_groups)
    
    current_speaker = None
    current_paragraph = []
    
    for entry in transcript:
        entry_start = entry.get('start', 0)
        # Insert all screenshot groups that should appear before this transcript entry
        while (screenshot_index < total_groups and
               screenshot_groups[screenshot_index][0].get('timestamp', 0) - 1.0 <= entry_start):
            group = screenshot_groups[screenshot_index]
            for screenshot in group:
                # If there's an ongoing paragraph, flush it before inserting the screenshot
                if current_paragraph:
                    if current_speaker:
                        md_lines.append(f"**{current_speaker} [{format_time(current_paragraph[0].get('start', 0))}]:**")
                    paragraph_text = ' '.join([e.get('text', '') for e in current_paragraph])
                    md_lines.append(f"{paragraph_text}\n")
                    current_paragraph = []
                # Insert the screenshot
                image_path = screenshot.get('image_path', '')
                if image_path:
                    md_lines.append(f"![Screenshot]({image_path})\n")
            screenshot_index += 1
        
        # Check if the speaker has changed
        if 'speaker' not in entry:
            logging.warning(f"No speaker found for entry at {entry}")
            entry['speaker'] = "Unknown"
        
        if entry['speaker'] != current_speaker:
            # Flush the current paragraph if exists
            if current_paragraph:
                if current_speaker:
                    md_lines.append(f"**{current_speaker} [{format_time(current_paragraph[0].get('start', 0))}]:**")
                paragraph_text = ' '.join([e.get('text', '') for e in current_paragraph])
                md_lines.append(f"{paragraph_text}\n")
                current_paragraph = []
            # Update the current speaker
            current_speaker = entry['speaker']
        
        # Add the current entry to the paragraph
        current_paragraph.append(entry)
    
    # After processing all entries, flush any remaining paragraph
    if current_paragraph:
        if current_speaker:
            md_lines.append(f"**{current_speaker} [{format_time(current_paragraph[0].get('start', 0))}]:**")
        paragraph_text = ' '.join([e.get('text', '') for e in current_paragraph])
        md_lines.append(f"{paragraph_text}\n")

    # Insert any remaining screenshots after the last transcript entry
    while screenshot_index < total_groups:
        group = screenshot_groups[screenshot_index]
        for screenshot in group:
            image_path = screenshot.get('image_path', '')
            if image_path:
                md_lines.append(f"![Screenshot]({image_path})\n")
        screenshot_index += 1

    # Write to Markdown file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_lines))

def format_time(seconds):
    """
    Convert seconds to HH:MM:SS.mmm format.
    """
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hrs > 0:
        return f"{hrs:02}:{mins:02}:{secs:06.3f}"
    else:
        return f"{mins:02}:{secs:06.3f}"

def parse_arguments():
    """
    Parse command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Generate a Markdown file by merging a transcript and screenshots.")
    parser.add_argument("-t", "--transcript", required=True, help="Path to the transcript JSON file")
    parser.add_argument("-s", "--screenshots", required=True, help="Path to the screenshots JSON file")
    parser.add_argument("-o", "--output", required=True, help="Path to the output Markdown file")
    
    return parser.parse_args()

def main():
    # Parse arguments from the command line
    args = parse_arguments()

    # Load JSON data
    transcript_data = load_json(args.transcript)['segments']
    screenshots_data = load_json(args.screenshots)

    # Sort data
    sorted_transcript = sort_transcript(transcript_data)
    sorted_screenshots = sort_screenshots(screenshots_data)
    grouped_screenshots = group_screenshots(sorted_screenshots)

    # Generate Markdown
    generate_markdown(sorted_transcript, grouped_screenshots, args.output)

    logging.info(f"Markdown file '{args.output}' has been generated successfully.")

if __name__ == "__main__":
    main()
