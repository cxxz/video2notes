import cv2
import argparse
import json
import os
from moviepy.editor import VideoFileClip

def select_roi_at_timestamp(video_path, timestamp=60, silent=False):
    def get_frame_at_timestamp(cap, timestamp):
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_number = int(fps * timestamp)

        if frame_number >= total_frames:
            print(f"Timestamp {timestamp}s exceeds video duration. Setting to last frame.")
            frame_number = total_frames - 1

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if not ret:
            print("Error: Could not read video at the specified timestamp.")
            return None, frame_number
        return frame, frame_number

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video file {video_path}")
        return None

    if silent:
        # Directly get the frame without displaying it
        frame, frame_number = get_frame_at_timestamp(cap, timestamp)
        if frame is None:
            cap.release()
            return None

        # Set the entire frame as the "slide" ROI
        height, width = frame.shape[:2]
        roi = {'slide': [0, 0, width, height]}
        print("Silent mode enabled: 'slide' ROI set to entire frame.")
    else:
        while True:
            frame, frame_number = get_frame_at_timestamp(cap, timestamp)
            if frame is None:
                cap.release()
                return None

            cv2.imshow("Frame at Timestamp", frame)
            print(f"Displaying frame at {timestamp} seconds (Frame {frame_number}).")
            key = cv2.waitKey(1) & 0xFF

            # Ask user if they want to change the timestamp
            user_input = input("Is this the correct frame? (y/n): ").strip().lower()
            if user_input == 'y':
                break
            elif user_input == 'n':
                try:
                    new_timestamp = float(input("Enter new timestamp in seconds: ").strip())
                    timestamp = new_timestamp
                except ValueError:
                    print("Invalid input. Please enter a numeric value.")
            else:
                print("Please enter 'y' or 'n'.")

        roi = {}
        # Select Slide ROI
        # print("Select the ROI of the slide and press ENTER or SPACE when done, or 'c' to cancel.")
        print("\n\n========================\n")
        slide_roi = cv2.selectROI("Select Slide Area", frame, fromCenter=False, showCrosshair=True)
        if slide_roi == (0, 0, 0, 0):
            print("Slide ROI selection canceled.")
            cap.release()
            cv2.destroyAllWindows()
            return None
        roi['slide'] = slide_roi

        # Select Speaker ROI
        # print("Select the ROI of the speaker and press ENTER or SPACE when done, or 'c' to cancel.")
        print("\n\n========================\n")
        speaker_roi = cv2.selectROI("Select Speaker Area", frame, fromCenter=False, showCrosshair=True)
        print(f"\n\n\nSpeaker ROI: {speaker_roi}")
        if speaker_roi[2:] == (0, 0):
            print("No ROI selection for Speaker.")
        else:
            roi['speaker'] = speaker_roi

        # Select Subtitle ROI
        # print("Select the ROI of the subtitle and press ENTER or SPACE when done, or 'c' to cancel.")
        print("\n\n========================\n")
        subtitle_roi = cv2.selectROI("Select Subtitle Area", frame, fromCenter=False, showCrosshair=True)
        if subtitle_roi[2:] == (0, 0):
            print("No ROI selection for Subtitle.")
        else:
            roi['subtitle'] = subtitle_roi

        cv2.destroyAllWindows()

    cap.release()

    return {
        "timestamp": timestamp,
        "frame_number": frame_number,
        "rois": roi
    }

def save_rois_to_json(rois_data, output_path):
    try:
        with open(output_path, 'w') as f:
            json.dump(rois_data, f, indent=4)
        print(f"ROIs saved to {output_path}")
    except IOError as e:
        print(f"Error saving ROIs to file: {e}")

def extract_audio_from_video(video_path, output_audio_path):
    # Load the video file
    video_clip = VideoFileClip(video_path)

    # Extract audio from the video
    audio_clip = video_clip.audio

    # Write the audio to the desired output format
    audio_clip.write_audiofile(output_audio_path, codec="aac", ffmpeg_params=['-threads', '4'])
    print(f"Audio extracted and saved to {output_audio_path}")

    # Close the clips
    video_clip.close()
    audio_clip.close()

def parse_arguments():
    parser = argparse.ArgumentParser(description="Select ROIs from a video at a specific timestamp.")
    parser.add_argument('-i', '--video_path', type=str, help='Path to the video file.')
    parser.add_argument('-t', '--timestamp', type=float, default=60, help='Initial timestamp in seconds (default: 60).')
    parser.add_argument('-o', '--output', type=str, default=".", help='Path to save the ROI data as JSON.')
    parser.add_argument('-s', '--silent', action='store_true', help='Skip ROI selection and set slide ROI to entire frame.')
    parser.add_argument('-a', '--audio', action='store_true', help='Extract audio from the video.')
    return parser.parse_args()

def main():
    args = parse_arguments()

    if not os.path.isfile(args.video_path):
        print(f"Error: The file {args.video_path} does not exist.")
        return

    rois = select_roi_at_timestamp(args.video_path, timestamp=args.timestamp, silent=args.silent)
    if rois is None:
        print("ROI selection was unsuccessful.")
        return

    # Determine output file path
    if args.output:
        output_folder = args.output
    else:
        output_folder = os.path.dirname(args.video_path)
    base_name = os.path.splitext(os.path.basename(args.video_path))[0]

    json_output = f"{output_folder}/{base_name}_rois.json"
    audio_output = f"{output_folder}/{base_name}.m4a"

    save_rois_to_json(rois, json_output)

    # Optionally, print the ROIs
    for k, v in rois['rois'].items():
        print(f"{k}: {v}")

    # Extract audio from the video
    if args.audio:
        extract_audio_from_video(args.video_path, audio_output)

if __name__ == "__main__":
    main()
