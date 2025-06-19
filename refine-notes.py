import re
import os
import argparse
import logging
from utils import initialize_client, get_llm_response

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Read markdown file content
def read_markdown_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

# Truncate the text into chunks based on character length and ensure each starts with '**SPEAKER'
def chunk_transcript(text, min_chars=2000, max_chars=3000):
    chunks = []
    speakers = re.split(r'(?=\*\*SPEAKER)', text)  # Split by speaker section

    current_chunk = ""
    for speaker_text in speakers:
        if len(current_chunk) + len(speaker_text) < max_chars:
            current_chunk += speaker_text
        else:
            if len(current_chunk) > min_chars:
                chunks.append(current_chunk)
                current_chunk = speaker_text
            else:
                current_chunk += speaker_text  # Merge if still below min_chars

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

def refine_text_with_llm(text_chunk, lec_summary, client, llm):
    refine_transcript_template = """The following piece of text is of a transcript from a lecture. The summary of the lecture is provided below:
<summary>
{summary}
</summary>
The text is as follows:
<text>
{text}
</text>
Your task is to refine the text. 
 - Correct any typo or grammar mistake. 
 - Remove any unnecessary repetition, fill in any missing information, and ensure the text is logically structured.
 - Do NOT change the meaning of the text.
 - Do NOT change the Markdown formatting such as bold, italic, or code blocks.
 - Do NOT remove any image from the text.
Please output only the refined text in your response, without any additional information, such as leading XML tags or triple quotes.

Here's the refined text:
"""
    user_prompt = refine_transcript_template.format(text=text_chunk, summary=lec_summary)
    response = get_llm_response(client, llm, user_prompt)
    return response

# Merge refined chunks and save to a new file
def save_refined_transcript(refined_chunks, output_file_path):
    with open(output_file_path, 'w', encoding='utf-8') as file:
        for chunk in refined_chunks:
            file.write(chunk + "\n\n")

# Main process
def process_markdown_transcript(transcript, output_file_path, lec_summary, client, llm, max_chars=None):
    # Step 1: Truncate transcript if needed
    if max_chars is not None:
        transcript = transcript[:max_chars]

    # Step 2: Truncate into chunks
    transcript_chunks = chunk_transcript(transcript)

    # Step 3: Refine each chunk using LLM API
    refined_chunks = []
    for chunk in transcript_chunks:
        logging.info(f"Before refine, length: {len(chunk)}\n{chunk[:500]}")
        refined_chunk = refine_text_with_llm(chunk, lec_summary, client, llm)
        logging.info(f"After refine, length: {len(refined_chunk)}\n{refined_chunk[:500]}\n=======\n")
        refined_chunks.append(refined_chunk)

    # Step 4: Save refined transcript back to markdown
    save_refined_transcript(refined_chunks, output_file_path)
    logging.info(f"Refined transcript saved to: {output_file_path}")

def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Process and refine a transcript using an LLM.")
    parser.add_argument("-i", "--input", required=True, help="Path to the input Markdown file")
    parser.add_argument("-o", "--output", required=False, default=".", help="Folder to save the output Markdown file")
    parser.add_argument("-m", "--model", required=False, default="bedrock/claude-4-sonnet", help="LLM model to use for refinement")
    parser.add_argument("--max_chars", type=int, default=None, help="Maximum number of characters to process")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    
    # Initialize the client
    client = initialize_client(args.model)

    # Read the transcript
    transcript = read_markdown_file(args.input)

    # Define a new prompt for summarizing the text
    summary_template = """Please summarize the following transcript into two to three paragraphs:
<transcript>
{transcript}
</transcript>

Here's a summary of the transcript in two to three paragraphs:
"""
    user_prompt = summary_template.format(transcript=transcript)

    # Call LLM to get a summary of the transcript
    logging.info(f"Getting a summary of the transcript using {args.model}...")
    lec_summary = get_llm_response(client, args.model, user_prompt)
    logging.info(f"Summary of the transcript:\n{lec_summary}\n=============\nNow working on refining the transcript...\n")
    input_file_name = os.path.basename(args.input)
    output_file_name = f"refined_{input_file_name}" if not args.output else f"{args.output}/refined_{input_file_name}"
    logging.info(f"Output file: {output_file_name}")
    # Process the markdown transcript
    process_markdown_transcript(transcript, output_file_name, lec_summary, client, args.model, args.max_chars)
