from moviepy.editor import VideoFileClip
import sys
import os

def parse_timestamp(timestamp):
    parts = timestamp.strip().split(':')
    parts = [int(p) for p in parts]
    if len(parts) == 2:
        # MM:SS
        minutes, seconds = parts
        total_seconds = minutes * 60 + seconds
    elif len(parts) == 3:
        # HH:MM:SS
        hours, minutes, seconds = parts
        total_seconds = hours * 3600 + minutes * 60 + seconds
    else:
        raise ValueError(f"Invalid timestamp format: {timestamp}")
    return total_seconds

def main(video_file, timestamp_file):
    """Split video into segments based on timestamps.

    Uses proper resource cleanup to ensure VideoFileClip resources are released.
    """
    # Read timestamps from file
    with open(timestamp_file, 'r') as f:
        timestamps = f.readlines()

    # Parse and convert timestamps to seconds
    timestamps = [line.strip() for line in timestamps if line.strip()]
    times_in_seconds = [parse_timestamp(ts) for ts in timestamps]

    # Sort the times in case they're not in order
    times_in_seconds.sort()

    # Include start time and video duration
    times = [0] + times_in_seconds

    clip = None
    try:
        clip = VideoFileClip(video_file)
        video_duration = clip.duration
        times.append(video_duration)

        # Split video into segments
        for i in range(len(times) - 1):
            start_time = times[i]
            end_time = times[i + 1]
            subclip = None
            try:
                subclip = clip.subclip(start_time, end_time)
                video_path = os.path.splitext(video_file)[0]
                output_path = f'{video_path}_seg_{i + 1}'
                output_video = f'{output_path}.mp4'
                output_audio = f'{output_path}.mp3'
                subclip.write_videofile(
                    output_video,
                    codec='libx264',
                    temp_audiofile=output_audio,
                    remove_temp=False
                )
            finally:
                # Close subclip to release resources
                if subclip is not None:
                    try:
                        subclip.close()
                    except Exception:
                        pass
    finally:
        # Always close the main clip
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python split_video.py <video_file> <timestamp_file>")
    else:
        video_file = sys.argv[1]
        timestamp_file = sys.argv[2]
        main(video_file, timestamp_file)