import os
import sys
import json
import argparse
import threading
import webbrowser
import shutil

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import initialize_client, get_llm_response
from flask import Flask, render_template_string, request, send_from_directory, url_for
from dotenv import load_dotenv
load_dotenv()

SLIDE_SELECTOR_PORT = os.getenv('SLIDE_SELECTOR_PORT', 5002)
LOCAL_SERVER = os.getenv('LOCAL_SERVER', 'false')

def extract_vocabulary(ocr_text, model_id='bedrock/claude-4-sonnet'):
    """
    Extract domain-specific vocabulary terms from the OCR transcript.
    """
    extract_voc_prompt = f"""
Your task is to extract domain-specific vocabularies from the transcript below:
<transcript>
{ocr_text}
</transcript>

The terms and abbreviations include those that:
- Appear infrequently in general knowledge
- Are technical jargon or abbreviations with specific meanings
- Can be easily confused with more common words that sound similar
- Require precise spelling and recognition for downstream applications
- Significantly impact the meaning of the entire transcription if misrecognized

Now extract 20 to 30 vocabulary terms from the transcript:
1. Output them in a comma-separated list
2. If they are abbreviations, do not spell out the full names.
"""
    client = initialize_client(model_id)
    return get_llm_response(client, model_id, extract_voc_prompt)

def render_page(title, header_title, content):
    """
    Render a full HTML page with a common base layout.
    """
    base_template = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>{{ title }}</title>
      <style>
         body { 
             font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
             margin: 0; 
             padding: 0; 
             background: #f2f2f2; 
         }
         header { 
             padding: 20px; 
             background-color: #0078D7; 
             color: white; 
             text-align: center; 
         }
         .container { 
             margin: 20px auto; 
             max-width: 1000px; 
             background: white; 
             padding: 20px; 
             border-radius: 8px; 
             box-shadow: 0 2px 5px rgba(0,0,0,0.1); 
         }
         .slide { 
             margin-bottom: 20px; 
             display: flex; 
             align-items: center; 
             border-bottom: 1px solid #ddd; 
             padding-bottom: 20px;
         }
         img { 
             max-width: 100%; 
             height: auto; 
             display: block; 
         }
         .checkbox { 
             margin-left: 20px; 
             font-size: 1.2em; 
             white-space: nowrap; /* prevents "Slide X" from breaking into 2 lines */
         }
         /* Enlarge the checkbox */
         .checkbox input[type="checkbox"] {
             transform: scale(1.4);
             margin-right: 6px;
         }
         .button-group { 
             margin-top: 20px; 
         }
         .btn { 
             padding: 10px 20px; 
             border: none; 
             border-radius: 4px; 
             background-color: #0078D7; 
             color: white; 
             cursor: pointer; 
             text-decoration: none; 
             font-size: 1em;
         }
         .btn:hover { 
             background-color: #005a9e; 
         }
         form { 
             display: inline; 
         }
         .row { 
             margin-top: 20px;
         }
         .select-model {
             padding: 8px 12px; 
             border-radius: 4px; 
             margin-right: 8px;
         }
      </style>
    </head>
    <body>
      <header><h1>{{ header_title }}</h1></header>
      <div class="container">
        {{ content|safe }}
      </div>
    </body>
    </html>
    """
    return render_template_string(base_template, title=title, header_title=header_title, content=content)

def process_slides(selected_ids, slides, folder_path, archive=False):
    """
    Process the slides based on selected IDs.
    Returns:
      - pruned: List of slides that are selected.
      - concatenated_texts: Combined OCR texts from selected slides.
      - archive_message: A message about the number of archived files (if archive=True).
    """
    pruned = []
    concatenated_texts = []
    archived_files = []
    archive_message = ""
    archive_folder = os.path.join(folder_path, "archived") if archive else None
    if archive and not os.path.exists(archive_folder):
        os.makedirs(archive_folder)
    
    # Backup original slides.json to ori_slides.json
    original_slides_path = os.path.join(folder_path, "slides.json")
    backup_slides_path = os.path.join(folder_path, "ori_slides.json")
    if os.path.exists(original_slides_path) and not os.path.exists(backup_slides_path):
        shutil.copy2(original_slides_path, backup_slides_path)
    
    for slide in slides:
        if slide["group_id"] in selected_ids:
            pruned.append({
                "group_id": slide.get("group_id"),
                "timestamp": slide.get("timestamp"),
                "image_path": slide.get("image_path"),
                "ocr_text": slide.get("ocr_text")
            })
            concatenated_texts.append(slide.get("ocr_text", ""))
        elif archive:
            # Archive unselected slide image
            image_path = slide["relative_path"]
            full_image_path = os.path.join(folder_path, image_path)
            if os.path.exists(full_image_path):
                destination = os.path.join(archive_folder, os.path.basename(image_path))
                shutil.move(full_image_path, destination)
                archived_files.append(image_path)
                
    if archive:
        archive_message = f"{len(archived_files)} unselected image file(s) moved to '{archive_folder}'"
    return pruned, concatenated_texts, archive_message

def run_slide_selector(folder_path):
    """
    Run the slide selector web application.
    """
    if folder_path.endswith(os.sep):
        folder_path = folder_path[:-1]
    
    # Load slides.json from the folder.
    json_path = os.path.join(folder_path, "slides.json")
    with open(json_path, "r", encoding="utf-8") as f:
        slides = json.load(f)
        
    # Update each slide with a relative image path.
    folder_basename = os.path.basename(folder_path)
    for slide in slides:
        prefix = folder_basename + os.sep
        if slide["image_path"].startswith(prefix):
            slide["relative_path"] = slide["image_path"][len(prefix):]
        else:
            slide["relative_path"] = slide["image_path"]
            
    app = Flask(__name__)

    @app.route("/")
    def index():
        # Build HTML for each slide item.
        slide_items = ""
        for slide in slides:
            slide_items += f"""
            <div class="slide">
              <img src="{ url_for('get_image', filename=slide['relative_path']) }" alt="Slide {slide['group_id']}">
              <label class="checkbox">
                <input type="checkbox" name="selected" value="{slide['group_id']}" checked>
                Slide {slide['group_id']}
              </label>
            </div>
            """
        content = f"""
        <h2>Select Slides</h2>
        <form method="post" action="/save">
           {slide_items}
           <div class="button-group">
             <input type="submit" value="Save Selection" class="btn">
             <button type="submit" formaction="/save-with-archive" class="btn">Save Selection with Archiving</button>
           </div>
        </form>
        """
        return render_page("Slide Selection", "Slide Selection", content)
    
    def common_save_response(pruned, concatenated_texts, archive_message=""):
        # Save pruned slides as the new slides.json (original backed up as ori_slides.json)
        output_json = os.path.join(folder_path, "slides.json")
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(pruned, f, indent=4)
            
        concatenated_text = "\n\n".join(concatenated_texts)
        output_txt = os.path.join(folder_path, "ocr_text_selected_slides.txt")
        with open(output_txt, "w", encoding="utf-8") as f:
            f.write(concatenated_text)
            
        # Build the response page with options.
        archive_html = f"<p>{archive_message}</p>" if archive_message else ""
        backup_message = "<p>Original slides backed up as: <strong>ori_slides.json</strong></p>"
        content = f"""
        <h2>Selection Saved</h2>
        {archive_html}
        {backup_message}
        <p>Selected slides saved as new: <strong>{output_json}</strong></p>
        <p>OCR text saved to: <strong>{output_txt}</strong></p>
        
        <!-- Separate rows for each action -->
        <div class="row">
          <a href="/" class="btn">Back</a>
        </div>
        <div class="row">
          <form action="/extract-vocabulary" method="post">
            <input type="hidden" name="ocr_text_file" value="{output_txt}">
            <select name="model_id" class="select-model">
              <option value="bedrock/claude-4-sonnet">claude-4-sonnet</option>
              <option value="openai/gpt-4o-2024-08-06">gpt-4o</option>
            </select>
            <button type="submit" class="btn">Extract Vocabulary</button>
          </form>
        </div>
        <div class="row">
          <form action="/shutdown" method="post">
            <button type="submit" class="btn">Close</button>
          </form>
        </div>
        """
        return render_page("Selection Saved", "Selection Saved", content)
    
    @app.route("/save", methods=["POST"])
    def save_selection():
        selected = request.form.getlist("selected")
        try:
            selected_ids = set(int(x) for x in selected)
        except ValueError:
            selected_ids = set()
        pruned, concatenated_texts, _ = process_slides(selected_ids, slides, folder_path, archive=False)
        return common_save_response(pruned, concatenated_texts)
    
    @app.route("/save-with-archive", methods=["POST"])
    def save_with_archive():
        selected = request.form.getlist("selected")
        try:
            selected_ids = set(int(x) for x in selected)
        except ValueError:
            selected_ids = set()
        pruned, concatenated_texts, archive_message = process_slides(selected_ids, slides, folder_path, archive=True)
        return common_save_response(pruned, concatenated_texts, archive_message)
    
    @app.route("/extract-vocabulary", methods=["POST"])
    def extract_vocabulary_route():
        ocr_text_file = request.form.get("ocr_text_file")
        model_id = request.form.get("model_id", "openai/gpt-4o")

        try:
            with open(ocr_text_file, "r", encoding="utf-8") as f:
                ocr_text = f.read()
            vocabulary = extract_vocabulary(ocr_text, model_id)
            vocabulary_file = os.path.join(folder_path, "vocabulary.txt")
            with open(vocabulary_file, "w", encoding="utf-8") as f:
                f.write(vocabulary)
            content = f"""
            <h2>Vocabulary Extracted</h2>
            <p>Vocabulary saved to: <strong>{vocabulary_file}</strong></p>
            <h3>Extracted Vocabulary:</h3>
            <pre>{vocabulary}</pre>
            
            <!-- Separate rows for each action -->
            <div class="row">
              <a href="/" class="btn">Back to Slides</a>
            </div>
            <div class="row">
              <form action="/shutdown" method="post">
                <button type="submit" class="btn">Close</button>
              </form>
            </div>
            """
            return render_page("Vocabulary Extracted", "Vocabulary Extracted", content)
        except Exception as e:
            content = f"""
            <h2>Error Extracting Vocabulary</h2>
            <p>Error: {str(e)}</p>
            <div class="row">
              <a href="/" class="btn">Back to Slides</a>
            </div>
            """
            return render_page("Error", "Error", content)
    
    @app.route("/shutdown", methods=["POST"])
    def shutdown():
        def shutdown_server():
            import time
            time.sleep(0.5)
            os._exit(0)
        threading.Thread(target=shutdown_server, daemon=True).start()
        return "<h1>Server shutting down...</h1>"
    
    @app.route("/images/<path:filename>")
    def get_image(filename):
        return send_from_directory(folder_path, filename)
    
    # def open_browser():
    #     webbrowser.open_new(f"http://127.0.0.1:{SLIDE_SELECTOR_PORT}")
    
    # if LOCAL_SERVER == 'true':
    #     threading.Timer(1.0, open_browser).start()
    
    # Run Flask server in a separate thread.
    from werkzeug.serving import make_server
    server = make_server('0.0.0.0', SLIDE_SELECTOR_PORT, app)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    try:
        while server_thread.is_alive():
            server_thread.join(1)
    except KeyboardInterrupt:
        print("Shutting down...")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a slide selection webpage.")
    parser.add_argument("folder", help="Folder containing slides.json and images")
    args = parser.parse_args()
    folder = args.folder if os.path.isabs(args.folder) else os.path.expanduser(args.folder)
    run_slide_selector(folder)
