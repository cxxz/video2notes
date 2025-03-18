import os
import json
import argparse
import threading
import webbrowser
from flask import Flask, render_template_string, request, send_from_directory

def run_slide_selector(folder_path):
    """Run the slide selector web app for the given folder"""
    # Expand user path if needed
    folder = os.path.expanduser(folder_path)
    
    # Load the slides.json file from the folder
    json_path = os.path.join(folder, "slides.json")
    with open(json_path, "r", encoding="utf-8") as f:
        slides = json.load(f)
        
    # Get the folder's basename (e.g. "slides_vfmos-20250115_20250315180347")
    folder_basename = os.path.basename(folder)
    
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
             <input type="submit" value="Save Selection">
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
        output_json = os.path.join(folder, "pruned_slides.json")
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(pruned, f, indent=4)
    
        # Concatenate the OCR texts and save to a text file.
        concatenated_text = "\n\n".join(concatenated_texts)
        output_txt = os.path.join(folder, "ocr_text_selected_slides.txt")
        with open(output_txt, "w", encoding="utf-8") as f:
            f.write(concatenated_text)
    
        return f"<h2>Selection saved to {output_json} and OCR text saved to {output_txt}</h2><p><a href='/'>Back</a></p>"
    
    # Serve image files from the provided folder.
    @app.route("/images/<path:filename>")
    def get_image(filename):
        return send_from_directory(folder, filename)
    
    def open_browser():
        # Use 127.0.0.1 instead of localhost to avoid access issues
        webbrowser.open_new("http://127.0.0.1:5000")
        
    # Start browser after delay and run flask app
    threading.Timer(1.0, open_browser).start()
    print(f"\n=== Starting slide selection web app at http://127.0.0.1:5000 ===\n")
    print("Close this window or press Ctrl+C when you're done selecting slides.")
    app.run(debug=False)

# Main execution when script is run directly
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a slide selection webpage.")
    parser.add_argument("folder", help="Folder containing slides.json and images")
    args = parser.parse_args()
    folder = os.path.expanduser(args.folder)
    run_slide_selector(folder)