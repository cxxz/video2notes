import os
import json
import argparse
import threading
import webbrowser
import shutil
from utils import initialize_client, get_llm_response
from flask import Flask, render_template_string, request, send_from_directory

def extract_vocabulary(ocr_text, model_id = 'azure/gpt-4o'):
    """Extract technical words from the orc text."""

    extract_voc_prompt = f"""
Your task is to extract domain-specific vacabularies from the transcript below:
<transcript>
{ocr_text}
</transcript>

The terms and abbreviations include those that:
-  Appear infrequently in general knowledge
-  Are technical jargon or abbreviations with specific meanings
-  Can be easily confused with more common words that sound similar
-  Require precise spelling and recognition for downstream applications
-  Significantly impact the meaning of the entire transcription if misrecognized

Now extract 20 to 30 vocabulary terms from the transcript:
1. Output them in a comma-separated list
2. If they are abbreviations, do not spell out the full names.
"""

    client = initialize_client(model_id)
    return get_llm_response(client, model_id, extract_voc_prompt) 

def run_slide_selector(folder_path):
    """Run the slide selector web app for the given folder"""
    if folder_path.endswith("/"):
        folder_path = folder_path[:-1]
    
    # Load the slides.json file from the folder
    json_path = os.path.join(folder_path, "slides.json")
    with open(json_path, "r", encoding="utf-8") as f:
        slides = json.load(f)
        
    # Get the folder's basename (e.g. "slides_vfmos-20250115_20250315180347")
    folder_basename = os.path.basename(folder_path)
    
    # Adjust each slide's image path
    for slide in slides:
        prefix = folder_basename + os.sep
        if slide["image_path"].startswith(prefix):
            slide["relative_path"] = slide["image_path"][len(prefix):]
        else:
            slide["relative_path"] = slide["image_path"]
            
    app = Flask(__name__)
    
    # Main page: display all slides with a checkbox to the right of each image.
    @app.route("/")
    def index():
        html = """
        <html>
          <head>
             <title>Slide Selection</title>
             <style>
               body { font-family: Arial, sans-serif; }
               .slide {
                 margin-bottom: 20px;
                 display: flex;
                 align-items: center;
               }
               img { max-width: 1000px; display: block; }
               .checkbox { margin-left: 20px; }
               .button-group { display: flex; gap: 10px; }
             </style>
          </head>
          <body>
             <h1>Select Slides</h1>
             <form method="post" action="/save">
             {% for slide in slides %}
                <div class="slide">
                  <img src="{{ url_for('get_image', filename=slide.relative_path) }}" alt="Slide {{ slide.group_id }}">
                  <label class="checkbox">
                    <input type="checkbox" name="selected" value="{{ slide.group_id }}" checked>
                    Slide {{ slide.group_id }}
                  </label>
                </div>
             {% endfor %}
             <div class="button-group">
                <input type="submit" value="Save Selection">
                <button type="submit" formaction="/save-with-archive">Save Selection with Archiving</button>
             </div>
             </form>
          </body>
        </html>
        """
        return render_template_string(html, slides=slides)
    
    # Route to save the pruned slides JSON and concatenate ocr_text of selected slides.
    @app.route("/save", methods=["POST"])
    def save_selection():
        selected_ids = request.form.getlist("selected")
        try:
            selected_ids = set(int(x) for x in selected_ids)
        except ValueError:
            selected_ids = set()
    
        pruned = []
        concatenated_texts = []  # to hold ocr_text for each selected slide
        for slide in slides:
            if slide["group_id"] in selected_ids:
                pruned_slide = {
                    "group_id": slide.get("group_id"),
                    "timestamp": slide.get("timestamp"),
                    "image_path": slide.get("image_path"),
                    "ocr_text": slide.get("ocr_text")
                }
                pruned.append(pruned_slide)
                concatenated_texts.append(slide.get("ocr_text", ""))
    
        # Save the pruned slides to pruned_slides.json in the same folder.
        output_json = os.path.join(folder_path, "pruned_slides.json")
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(pruned, f, indent=4)
    
        # Concatenate the OCR texts and save to a text file.
        concatenated_text = "\n\n".join(concatenated_texts)
        output_txt = os.path.join(folder_path, "ocr_text_selected_slides.txt")
        with open(output_txt, "w", encoding="utf-8") as f:
            f.write(concatenated_text)
    
        return render_template_string("""
        <html>
          <head>
            <title>Selection Saved</title>
            <style>
              body { font-family: Arial, sans-serif; padding: 20px; }
              .btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; background-color: #0078D7; color: white; text-decoration: none; }
              .btn:hover { background-color: #005a9e; }
              .row { margin-top: 20px; }
              .row select { padding: 8px 16px; border-radius: 4px; border: 1px solid #ccc; }
              form { display: inline; }
            </style>
          </head>
          <body>
            <h2>Selection saved to {{ json_file }} and OCR text saved to {{ txt_file }}</h2>
            <div class="row">
              <a href="/" class="btn">Back</a>
            </div>
            <div class="row">
              <form action="/extract-vocabulary" method="post">
                <input type="hidden" name="ocr_text_file" value="{{ txt_file }}">
                <select name="model_id">
                  <option value="azure/gpt-4o">azure/gpt-4o</option>
                  <option value="bedrock/claude-3.7">bedrock/claude-3.7</option>
                </select>
                <button type="submit" class="btn">Extract Vocabulary</button>
              </form>
            </div>
            <div class="row">
              <form action="/shutdown" method="post">
                <button type="submit" class="btn">Close</button>
              </form>
            </div>
          </body>
        </html>
        """, json_file=output_json, txt_file=output_txt)
    
    @app.route("/save-with-archive", methods=["POST"])
    def save_with_archive():
        selected_ids = request.form.getlist("selected")
        try:
            selected_ids = set(int(x) for x in selected_ids)
        except ValueError:
            selected_ids = set()
        
        # Create the archive folder if it doesn't exist
        archive_folder = os.path.join(folder_path, "archived")
        if not os.path.exists(archive_folder):
            os.makedirs(archive_folder)
        
        # Process slides, move unselected slides to archive
        pruned = []
        concatenated_texts = []
        archived_files = []
        
        for slide in slides:
            if slide["group_id"] in selected_ids:
                # Selected slide - keep it and add to pruned list
                pruned_slide = {
                    "group_id": slide.get("group_id"),
                    "timestamp": slide.get("timestamp"),
                    "image_path": slide.get("image_path"),
                    "ocr_text": slide.get("ocr_text")
                }
                pruned.append(pruned_slide)
                concatenated_texts.append(slide.get("ocr_text", ""))
            else:
                # Unselected slide - move its image to archive folder
                image_path = slide["relative_path"]
                full_image_path = os.path.join(folder_path, image_path)
                if os.path.exists(full_image_path):
                    destination = os.path.join(archive_folder, os.path.basename(image_path))
                    shutil.move(full_image_path, destination)
                    archived_files.append(image_path)
        
        # Save the pruned slides to pruned_slides.json in the same folder
        output_json = os.path.join(folder_path, "pruned_slides.json")
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(pruned, f, indent=4)
        
        # Concatenate the OCR texts and save to a text file.
        concatenated_text = "\n\n".join(concatenated_texts)
        output_txt = os.path.join(folder_path, "ocr_text_selected_slides.txt")
        with open(output_txt, "w", encoding="utf-8") as f:
            f.write(concatenated_text)
        
        # Create response message
        archive_message = f"{len(archived_files)} unselected image files moved to {archive_folder}"
        
        return render_template_string("""
        <html>
          <head>
            <title>Selection Saved with Archiving</title>
            <style>
              body { font-family: Arial, sans-serif; padding: 20px; }
              .btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; background-color: #0078D7; color: white; text-decoration: none; }
              .btn:hover { background-color: #005a9e; }
              .row { margin-top: 20px; }
              .row select { padding: 8px 16px; border-radius: 4px; border: 1px solid #ccc; }
              form { display: inline; }
            </style>
          </head>
          <body>
            <h2>Selection saved with archiving</h2>
            <p>{{ archive_message }}</p>
            <p>Selected slides saved to {{ json_file }}</p>
            <p>OCR text saved to {{ txt_file }}</p>
            <div class="row">
              <a href="/" class="btn">Back</a>
            </div>
            <div class="row">
              <form action="/extract-vocabulary" method="post">
                <input type="hidden" name="ocr_text_file" value="{{ txt_file }}">
                <select name="model_id">
                  <option value="azure/gpt-4o">azure/gpt-4o</option>
                  <option value="bedrock/claude-3.7">bedrock/claude-3.7</option>
                </select>
                <button type="submit" class="btn">Extract Vocabulary</button>
              </form>
            </div>
            <div class="row">
              <form action="/shutdown" method="post">
                <button type="submit" class="btn">Close</button>
              </form>
            </div>
          </body>
        </html>
        """, archive_message=archive_message, json_file=output_json, txt_file=output_txt)
    
    @app.route("/extract-vocabulary", methods=["POST"])
    def extract_vocabulary_route():
        ocr_text_file = request.form.get("ocr_text_file")
        model_id = request.form.get("model_id", "azure/gpt-4o")
        
        # Read the OCR text file
        try:
            with open(ocr_text_file, "r", encoding="utf-8") as f:
                ocr_text = f.read()
                
            # Extract vocabulary using the selected model
            vocabulary = extract_vocabulary(ocr_text, model_id)
            
            # Save vocabulary to a text file in the same folder
            vocabulary_file = os.path.join(folder_path, "vocabulary.txt")
            with open(vocabulary_file, "w", encoding="utf-8") as f:
                f.write(vocabulary)
                
            return render_template_string("""
            <html>
              <head>
                <title>Vocabulary Extracted</title>
                <style>
                  body { font-family: Arial, sans-serif; padding: 20px; }
                  pre { background-color: #f4f4f4; padding: 15px; border-radius: 5px; }
                  .btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; background-color: #0078D7; color: white; text-decoration: none; }
                  .btn:hover { background-color: #005a9e; }
                  .row { margin-top: 20px; }
                  form { display: inline; }
                </style>
              </head>
              <body>
                <h2>Vocabulary extracted and saved to {{ vocab_file }}</h2>
                <h3>Extracted Vocabulary:</h3>
                <pre>{{ vocabulary }}</pre>
                <div class="row">
                  <a href="/" class="btn">Back to slides</a>
                </div>
                <div class="row">
                  <form action="/shutdown" method="post">
                    <button type="submit" class="btn">Close</button>
                  </form>
                </div>
              </body>
            </html>
            """, vocab_file=vocabulary_file, vocabulary=vocabulary)
            
        except Exception as e:
            return f"""
            <h2>Error extracting vocabulary</h2>
            <p>Error: {str(e)}</p>
            <p><a href="/">Back to slides</a></p>
            """
    
    @app.route("/shutdown", methods=["POST"])
    def shutdown():
        def shutdown_server():
            # Small delay to allow the response to be sent
            import time
            time.sleep(0.5)
            # Force exit the process
            import os
            os._exit(0)
        
        # Start a new thread to handle the shutdown
        threading.Thread(target=shutdown_server, daemon=True).start()
        return "<h1>Server shutting down...</h1>"

    # Serve image files from the provided folder.
    @app.route("/images/<path:filename>")
    def get_image(filename):
        return send_from_directory(folder_path, filename)
    
    def open_browser():
        # Use 127.0.0.1 instead of localhost to avoid access issues
        webbrowser.open_new("http://127.0.0.1:5000")
        
    # Start browser after delay
    threading.Timer(1.0, open_browser).start()
    
    # Run Flask in a separate thread that can be terminated
    from werkzeug.serving import make_server
    server = make_server('127.0.0.1', 5000, app)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    # Keep main thread alive
    try:
        while server_thread.is_alive():
            server_thread.join(1)
    except KeyboardInterrupt:
        print("Shutting down...")

# Main execution when script is run directly
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a slide selection webpage.")
    parser.add_argument("folder", help="Folder containing slides.json and images")
    args = parser.parse_args()
    # Modified folder assignment:
    if os.path.isabs(args.folder):
        folder = args.folder
    else:
        folder = os.path.expanduser(args.folder)
    print(f"CONG TEST: {folder}")
    run_slide_selector(folder)