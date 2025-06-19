#!/usr/bin/env python
"""
SharePoint video downloader script.
This script provides a command-line interface for downloading videos from SharePoint.
"""
import sys
import os
import argparse
from dotenv import load_dotenv

# Add parent directory to path to import from app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.sharepoint_downloader import SharePointDownloader

load_dotenv()

# Default configuration
DEFAULT_SHAREPOINT_URL = os.getenv("SHAREPOINT_URL", None)
DEFAULT_OUTPUT_DIR = "downloaded_videos"


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Download video files from SharePoint",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--sharepoint-url",
        type=str,
        default=DEFAULT_SHAREPOINT_URL,
        help="SharePoint URL to download from (default: configured VFMOS meeting recordings folder)"
    )
    
    parser.add_argument(
        "--select",
        action="store_true",
        help="Show the latest 5 video files and let user select which one to download"
    )
    
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save downloaded files (default: downloads/meeting_recordings)"
    )
    
    return parser.parse_args()


def display_video_selection(video_files, max_count=5):
    """Display video files for user selection and return the selected file."""
    files_to_show = video_files[:max_count]
    
    print(f"\nFound {len(video_files)} video file(s). Showing latest {len(files_to_show)}:")
    print("-" * 60)
    
    for i, video_file in enumerate(files_to_show, 1):
        filename = video_file["FileLeafRef"]
        modified = video_file.get("Modified.", "Unknown")
        print(f"{i}. {filename}")
        print(f"   Modified: {modified}")
        print()
    
    while True:
        try:
            choice = input(f"Select a file to download (1-{len(files_to_show)}): ").strip()
            choice_num = int(choice)
            
            if 1 <= choice_num <= len(files_to_show):
                selected_file = files_to_show[choice_num - 1]
                print(f"Selected: {selected_file['FileLeafRef']}")
                return selected_file
            else:
                print(f"Please enter a number between 1 and {len(files_to_show)}")
        except ValueError:
            print("Please enter a valid number")
        except KeyboardInterrupt:
            print("\nOperation cancelled by user")
            return None


def main():
    """Main function for standalone script usage."""
    # Parse command line arguments
    args = parse_arguments()
    
    if not args.sharepoint_url:
        print("Error: SharePoint URL must be provided via --sharepoint-url or SHAREPOINT_URL environment variable")
        sys.exit(1)
    
    # Create downloader instance with command line arguments
    downloader = SharePointDownloader(
        sharepoint_url=args.sharepoint_url,
        output_dir=args.output_dir
    )
    
    # Download based on selection mode
    try:
        if args.select:
            # Get video files and let user select
            print(f"Using SharePoint URL: {args.sharepoint_url}")
            print(f"Output directory: {args.output_dir}")
            print("Selection mode enabled - will show latest video files for selection")
            
            video_files = downloader.get_video_files()
            selected_file = display_video_selection(video_files, max_count=5)
            
            if not selected_file:
                print("No file selected. Exiting.")
                sys.exit(0)
            
            success = downloader.download_file(selected_file)
        else:
            # Download latest video automatically
            print(f"Using SharePoint URL: {args.sharepoint_url}")
            print(f"Output directory: {args.output_dir}")
            
            video_files = downloader.get_video_files()
            if not video_files:
                print("No video files found.")
                sys.exit(1)
            
            latest = video_files[0]  # First item is the newest due to sorting
            print(f"Found {len(video_files)} video file(s)")
            print(f"Latest video file: {latest['FileLeafRef']}")
            print(f"Modified: {latest.get('Modified.', 'Unknown')}")
            
            success = downloader.download_file(latest)
        
        if success:
            print("Download completed successfully!")
        else:
            print("Download failed!")
            sys.exit(1)
            
    except Exception as e:
        print(f"Error during execution: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()