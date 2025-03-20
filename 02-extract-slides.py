import cv2
import os
import imagehash
from PIL import Image
from datetime import datetime
import numpy as np
import argparse
import json
import pytesseract
import sys

# Import slide selection functionality
from utils import analyze_text_for_names
from slides_selector import run_slide_selector

def crop_slide(frame, roi):
    if roi is None:
        return frame
    """Crop the slide area from the frame using the defined ROI."""
    x, y, w, h = roi
    return frame[y:y+h, x:x+w]

def mask_frame(frame, roi):
    """Mask out the specified ROI area in the frame."""
    x, y, w, h = roi
    # Get the background color by computing the median color
    bg_color = np.median(frame, axis=(0, 1)).astype(np.uint8)
    frame[y:y+h, x:x+w] = bg_color
    return frame

def seconds_to_hms(seconds):
    """Convert seconds to hours, minutes, and seconds."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return h, m, s

def extract_unique_slides(video_path, save_folder, slide_roi, masks_roi=None, start_seconds=0, end_seconds=None, frame_rate=1, similarity_threshold=10):
    """Extract unique slides from the video and save them to the specified folder."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video file {video_path}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = fps * frame_rate
    frame_number = start_seconds * fps
    end_frame = end_seconds * fps if end_seconds else cap.get(cv2.CAP_PROP_FRAME_COUNT)

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

    unique_slides = []
    last_slide_hash = None
    group_started = False
    first_timestamp_of_group = None
    slides_buffer = []
    speaker_names = []
    names_text = ""
    group_id = 0

    slides_folder = os.path.basename(os.path.normpath(save_folder))

    while frame_number < end_frame:
        ret, frame = cap.read()
        if not ret:
            break

        unmasked_frame = frame.copy()

        # Apply masks if any
        if masks_roi:
            masked_frame = frame.copy()
            for roi in masks_roi:
                masked_frame = mask_frame(masked_frame, roi)
            slide_frame = crop_slide(masked_frame, slide_roi)
        else:
            slide_frame = crop_slide(frame, slide_roi)

        # Convert cropped slide to grayscale for comparison
        gray_slide = cv2.cvtColor(slide_frame, cv2.COLOR_BGR2GRAY)
        pil_image = Image.fromarray(gray_slide)

        # Calculate perceptual hash
        current_hash = imagehash.phash(pil_image)
        # print(f"CONG TES current_hash: {current_hash}")

        # Compare with the last slide hash
        if last_slide_hash is None or abs(current_hash - last_slide_hash) > similarity_threshold:
            # ocr_text = pytesseract.image_to_string(unmasked_frame)
            # len_ocr_text = len(ocr_text)
            # if len_ocr_text < 10:
            #     # Categorize as non-slide if OCR text is too short
            #     frame_number += frame_interval
            #     cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            #     continue

            # End of a group; save the middle slide
            if group_started and slides_buffer:     
                add_new_slide = True

                slide_index = int(len(slides_buffer) / 2)       
                selected_slide = slides_buffer[slide_index]

                ocr_text = pytesseract.image_to_string(selected_slide)
                len_ocr_text = len(ocr_text)
                if len_ocr_text < 10:
                    add_new_slide = False
                elif len(unique_slides) > 0:
                    for slide in unique_slides:
                        prev_group = slide['group_id']
                        prev_imagehash = slide['imagehash']
                        if abs(current_hash - prev_imagehash) <= similarity_threshold:
                            print(f"Duplicate slide found: {prev_group} with current group {group_id}")
                            add_new_slide = False
                            break
                    
                    if add_new_slide and len_ocr_text <= 300:
                        # Check if the slide contains mostly names
                        is_mostly_names, _, names = analyze_text_for_names(ocr_text)
                        if is_mostly_names:
                            print(f"Slide {group_id} contains mostly names: {names} in ocr_text: {ocr_text}")
                            if len(names) > len(speaker_names):
                                speaker_names = names
                                names_text = ocr_text
                            add_new_slide = False
                            
                if add_new_slide:
                    timestamps = first_timestamp_of_group
                    slide_filepath = os.path.join(save_folder, f'slide_{group_id}.png')
                    image_path = os.path.join(slides_folder, f'slide_{group_id}.png')
                    cv2.imwrite(slide_filepath, selected_slide)
                    h, m, s = seconds_to_hms(first_timestamp_of_group)
                    print(f'slide_{group_id}.png starts at: {h:02d}:{m:02d}:{s:02d} with {len_ocr_text} characters')

                    unique_slides.append({
                        'group_id': group_id,
                        'timestamp': first_timestamp_of_group,
                        'image_path': image_path,
                        'ocr_text': ocr_text,
                        'imagehash': current_hash
                    })

                slides_buffer = []
                group_id += 1
                group_started = False

                # Skip frames to avoid transition slides
                frame_number += fps * 3  # Skip next 3 seconds
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                continue

            # Start a new group
            first_timestamp_of_group = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000  # in seconds
            slides_buffer = [unmasked_frame]
            group_started = True
        else:
            # We are in a group of similar slides
            if group_started:
                slides_buffer.append(unmasked_frame)

        last_slide_hash = current_hash
        frame_number += frame_interval
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

    # Handle the last group if any
    if group_started and slides_buffer:
        timestamps = first_timestamp_of_group
        slide_index = int(len(slides_buffer) / 2)
        selected_slide = slides_buffer[slide_index]

        # Perform OCR on the selected slide
        ocr_text = pytesseract.image_to_string(selected_slide)
        len_ocr_text = len(ocr_text)
        if len_ocr_text >= 10:
            slide_filepath = os.path.join(save_folder, f'slide_{group_id}.png')
            image_path = os.path.join(slides_folder, f'slide_{group_id}.png')
            cv2.imwrite(slide_filepath, selected_slide)
            h, m, s = seconds_to_hms(first_timestamp_of_group)
            print(f'slide_{group_id}.png starts at: {h:02d}:{m:02d}:{s:02d} with {len_ocr_text} characters')

            unique_slides.append({
                'group_id': group_id,
                'timestamp': first_timestamp_of_group,
                'image_path': image_path,
                'ocr_text': ocr_text,
                'imagehash': current_hash
            })

    cap.release()
    # Convert all imagehash objects in unique_slides to strings
    for slide in unique_slides:
        slide['imagehash'] = str(slide['imagehash'])

    if len(speaker_names) > 0:
        print(f"Speaker names detected: {speaker_names}")
        # save speaker names to a txt named speaker_names.txt
        speaker_names_file = os.path.join(save_folder, 'speaker_names.txt')
        with open(speaker_names_file, 'w') as f:
            f.write(names_text)

    return unique_slides

def main():
    parser = argparse.ArgumentParser(description="Extract unique slides from a video.")
    parser.add_argument('-i', '--video_path', required=True, help='Path to the video file')
    parser.add_argument('-j', '--roi_json', required=False, help='Path to the ROI JSON file')
    parser.add_argument('-o', '--output_folder', default=None, help='Output folder to save slides')
    parser.add_argument('-s', '--start_seconds', type=int, default=1, help='Start time in seconds')
    parser.add_argument('-e', '--end_seconds', type=int, default=None, help='End time in seconds')
    parser.add_argument('-f', '--frame_rate', type=int, default=1, help='Extract one frame every N seconds')
    parser.add_argument('-t', '--similarity_threshold', type=int, default=15, help='Threshold for perceptual hash difference')
    parser.add_argument('--select', action='store_true', help='Launch slide selector web app after extraction')
    args = parser.parse_args()

    # Read ROIs from the JSON file
    slide_roi = None
    masks_roi = None

    if args.roi_json:
        with open(args.roi_json, 'r') as f:
            roi_data = json.load(f)

        # Extract the ROIs
        rois = roi_data.get('rois', {})
        slide_roi = rois.get('slide', None)

        # Collect masks ROI if they exist
        masks_roi = []
        for key in ['speaker', 'subtitle']:
            roi = rois.get(key, None)
            if roi:
                masks_roi.append(roi)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    video_basename = os.path.splitext(os.path.basename(args.video_path))[0]

    # Set up the output folder
    if args.output_folder:
        save_folder = os.path.join(args.output_folder)
    else:
        save_folder = os.path.join(os.path.dirname(args.video_path), f'slides_{video_basename}_{timestamp}')

    os.makedirs(save_folder, exist_ok=True)
    print(f'Saving slides to {save_folder}')

    # Extract unique slides
    unique_slides = extract_unique_slides(
        video_path=args.video_path,
        save_folder=save_folder,
        slide_roi=slide_roi,
        masks_roi=masks_roi if masks_roi else None,
        start_seconds=args.start_seconds,
        end_seconds=args.end_seconds,
        frame_rate=args.frame_rate,
        similarity_threshold=args.similarity_threshold
    )

    # Save unique_slides to a JSON file
    json_file = os.path.join(save_folder, 'slides.json')
    with open(json_file, 'w') as f:
        json.dump(unique_slides, f, indent=4)
    print(f'Saved slides to {json_file}')
    
    # Launch the slide selector web app if requested
    if args.select:
        print("\nLaunching slide selector web app...")
        run_slide_selector(save_folder)

if __name__ == '__main__':
    main()
