"""
SharePoint downloader module for the Video2Notes application.
This module provides the SharePointDownloader class for downloading videos from SharePoint.
"""
import json
import urllib.parse
from pathlib import Path
from datetime import datetime
import os
from playwright.sync_api import sync_playwright

# Default configuration
# Get the project root directory (2 levels up from this file)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORAGE_STATE = os.path.join(PROJECT_ROOT, "sharepoint_session.json")
DEFAULT_OUTPUT_DIR = "downloaded_videos"


class SharePointDownloader:
    """SharePoint video file downloader that can be used as a module or standalone script."""
    
    def __init__(self, sharepoint_url=None, output_dir=None, storage_state=None, headless=True):
        """
        Initialize the SharePoint downloader.
        
        Args:
            sharepoint_url (str): SharePoint URL to download from
            output_dir (str): Directory to save downloaded files
            storage_state (str): Path to Playwright storage state file
            headless (bool): Run browser in headless mode
        """
        self.sharepoint_url = sharepoint_url
        if self.sharepoint_url is None:
            raise ValueError("SharePoint URL must be provided.")
        self.sharepoint_site_base = self.sharepoint_url.split('/Shared%20Documents')[0]
        self.output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
        self.storage_state = storage_state or STORAGE_STATE
        self.headless = headless
        self.video_extensions = ['mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv', 'm4v']
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def _parse_modified_date(self, row):
        """Parse the modified date from a row."""
        try:
            return datetime.fromisoformat(row["Modified."].replace('Z', '+00:00'))
        except (KeyError, ValueError):
            # Fallback to epoch if parsing fails
            return datetime.min
    
    def get_video_files(self):
        """
        Get video files from SharePoint and return them sorted by modification date (newest first).
        
        Returns:
            list: List of video file dictionaries from SharePoint API
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                storage_state=self.storage_state,
                accept_downloads=True
            )
            page = context.new_page()

            # Set up request interception to capture the POST request
            captured_response = None
            
            def handle_response(response):
                nonlocal captured_response
                if "GetListUsingPath(DecodedUrl=@a1)" in response.url and "recordings" in response.url and response.request.method == "POST":
                    captured_response = response
                    print(f"Captured response from {response.url}")
            
            page.on("response", handle_response)
            
            page.goto(self.sharepoint_url)
            
            # Wait for the POST request to be captured
            page.wait_for_timeout(5000)  # Wait up to 5 seconds
            
            if not captured_response:
                browser.close()
                raise ValueError("Could not capture the GetListUsingPath POST request. Make sure the page loads properly.")
            
            # Get the JSON data from the captured response
            data = captured_response.json()
            browser.close()

            # Extract rows and sort by "Modified." field (newest first)
            rows = data["ListData"]["Row"]
            if not rows:
                raise ValueError("No files found in the folder.")

            # Save the rows to a json file, For debugging
            # with open("rows.json", "w") as f:
            #     json.dump(rows, f, indent=4)

            # Sort rows by Modified. field in descending order (newest first)
            rows.sort(key=self._parse_modified_date, reverse=True)

            # Filter for video files
            video_files = [row for row in rows if row.get(".fileType", "").lower() in self.video_extensions]
            
            if not video_files:
                raise ValueError("No video files found in the folder.")
            
            return video_files
    
    def download_file(self, file_info):
        """
        Download a file using Playwright with multiple fallback methods.
        
        Args:
            file_info (dict): File information from SharePoint API
            
        Returns:
            bool: True if download was successful, False otherwise
        """
        unique_id = file_info["UniqueId"].strip("{}")
        filename = file_info["FileLeafRef"]
        
        print(f"Downloading file: {filename}")
        print(f"UniqueId: {unique_id}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                storage_state=self.storage_state,
                accept_downloads=True
            )
            page = context.new_page()

            download_success = False
            
            # Method 1: Use the spItemUrl from the API response (most reliable)
            if not download_success and ".spItemUrl" in file_info:
                try:
                    sp_item_url = file_info[".spItemUrl"]
                    # Remove query parameters before appending /content
                    base_url = sp_item_url.split('?')[0]
                    download_url = base_url + "/content"
                    print(f"Trying spItemUrl: {download_url}")
                    
                    with page.expect_download(timeout=30000) as dl_info:
                        try:
                            page.goto(download_url)
                        except Exception as nav_error:
                            # net::ERR_ABORTED is normal for downloads - ignore it
                            if "net::ERR_ABORTED" not in str(nav_error):
                                raise nav_error
                    
                    download = dl_info.value
                    out_filename = download.suggested_filename or filename
                    out_path = self.output_dir / out_filename
                    download.save_as(str(out_path))
                    
                    print(f"Successfully downloaded: {out_path.resolve()}")
                    download_success = True
                    
                except Exception as e:
                    # Only treat as failure if it's not a download-related abort
                    if "Timeout" in str(e) or "net::ERR_ABORTED" not in str(e):
                        print(f"Method 1 (spItemUrl) failed: {e}")
                    else:
                        print(f"Method 1 (spItemUrl) - navigation aborted (normal for downloads)")
            
            # Method 2: Try using the FileRef path
            if not download_success:
                try:
                    file_ref = file_info["FileRef"]
                    encoded_file_ref = urllib.parse.quote(file_ref)
                    download_url = f"{self.sharepoint_site_base}/_layouts/15/download.aspx?SourceUrl=https://hpe.sharepoint.com{encoded_file_ref}"
                    print(f"Trying FileRef URL: {download_url}")
                    
                    with page.expect_download(timeout=30000) as dl_info:
                        try:
                            page.goto(download_url)
                        except Exception as nav_error:
                            # net::ERR_ABORTED is normal for downloads - ignore it
                            if "net::ERR_ABORTED" not in str(nav_error):
                                raise nav_error
                    
                    download = dl_info.value
                    out_filename = download.suggested_filename or filename
                    out_path = self.output_dir / out_filename
                    download.save_as(str(out_path))
                    
                    print(f"Successfully downloaded: {out_path.resolve()}")
                    download_success = True
                    
                except Exception as e:
                    # Only treat as failure if it's not a download-related abort
                    if "Timeout" in str(e) or "net::ERR_ABORTED" not in str(e):
                        print(f"Method 2 (FileRef) failed: {e}")
                    else:
                        print(f"Method 2 (FileRef) - navigation aborted (normal for downloads)")
            
            # Method 3: Use the _layouts/15/download.aspx endpoint with UniqueId (final fallback)
            if not download_success:
                try:
                    download_url = f"{self.sharepoint_site_base}/_layouts/15/download.aspx?UniqueId={unique_id}"
                    print(f"Trying download URL: {download_url}")
                    
                    with page.expect_download(timeout=30000) as dl_info:
                        try:
                            page.goto(download_url)
                        except Exception as nav_error:
                            # net::ERR_ABORTED is normal for downloads - ignore it
                            if "net::ERR_ABORTED" not in str(nav_error):
                                raise nav_error
                    
                    download = dl_info.value
                    out_filename = download.suggested_filename or filename
                    out_path = self.output_dir / out_filename
                    download.save_as(str(out_path))
                    
                    print(f"Successfully downloaded: {out_path.resolve()}")
                    download_success = True
                    
                except Exception as e:
                    # Only treat as failure if it's not a download-related abort
                    if "Timeout" in str(e) or "net::ERR_ABORTED" not in str(e):
                        print(f"Method 3 (UniqueId) failed: {e}")
                        print("All download methods failed!")
                    else:
                        print(f"Method 3 (UniqueId) - navigation aborted (normal for downloads)")

            if not download_success:
                print("Failed to download file with all available methods.")
                print("Available fields in the file data:")
                for key in file_info.keys():
                    if 'url' in key.lower() or 'path' in key.lower() or 'ref' in key.lower():
                        print(f"  {key}: {file_info[key]}")

            browser.close()
            return download_success