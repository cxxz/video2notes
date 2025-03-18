import re
import os
import argparse
from openai import AzureOpenAI, OpenAI
from anthropic import AnthropicBedrock
from dotenv import load_dotenv

load_dotenv()

def initialize_client(llm):
    """Initializes the appropriate OpenAI client based on the model."""
    if llm.startswith("Meta"):
        openai_api_base = os.getenv("OPENAI_BASE_URL")
        client = OpenAI(
            api_key="anything",
            base_url=openai_api_base,
        )
    elif llm.startswith("gpt-4"):
        client = AzureOpenAI(
            api_version="2024-02-15-preview"
        )
    elif "anthropic.claude" in llm:
        client = AnthropicBedrock(
            aws_region="us-west-2",
        )
    else:
        raise ValueError(f"Unknown reviewer endpoint: {llm}")
    return client

def get_llm_response(client, llm, prompt):
    """Gets LLM response using the client and returns the result."""
    try:
        if "anthropic.claude" in llm:
            completion = client.messages.create(
                model=llm,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4096,
                temperature=0.1,
            )
            response = completion.content[0].text
        else:
            chat_completion = client.chat.completions.create(
                model=llm,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4096,
                temperature=0.1,
                top_p=0.95,
            )
            response = chat_completion.choices[0].message.content
        return response
    except Exception as e:
        print(f"Error: {e}")
        return None

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

# Call OpenAI API to refine text
def refine_text_with_llm(text_chunk, lec_summary, client, llm):
    prompt_template = """The following piece of text is of a transcript from a lecture. The summary of the lecture is provided below:
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
Only output the refined text. Do not include any other information.

Here's the refined text:
"""
    user_prompt = prompt_template.format(text=text_chunk, summary=lec_summary)
    response = get_llm_response(client, llm, user_prompt)
    return response

# Merge refined chunks and save to a new file
def save_refined_transcript(refined_chunks, output_file_path):
    with open(output_file_path, 'w', encoding='utf-8') as file:
        for chunk in refined_chunks:
            file.write(chunk + "\n")

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
        print(f"Before refine, length: {len(chunk)}\n{chunk[:500]}")
        refined_chunk = refine_text_with_llm(chunk, lec_summary, client, llm)
        print(f"After refine, length: {len(refined_chunk)}\n{refined_chunk[:500]}\n=======\n")
        refined_chunks.append(refined_chunk)

    # Step 4: Save refined transcript back to markdown
    save_refined_transcript(refined_chunks, output_file_path)
    print(f"Refined transcript saved to: {output_file_path}")

def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Process and refine a transcript using an LLM.")
    parser.add_argument("-i", "--input", required=True, help="Path to the input Markdown file")
    parser.add_argument("-o", "--output", required=False, default=".", help="Folder to save the output Markdown file")
    parser.add_argument("-m", "--model", required=False, default="us.anthropic.claude-3-7-sonnet-20250219-v1:0", help="LLM model to use for refinement")
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
    print(f"Getting a summary of the transcript using {args.model}...")
    lec_summary = get_llm_response(client, args.model, user_prompt)
    print(f"Summary of the transcript:\n{lec_summary}\n=============\nNow working on refining the transcript...\n")

    input_file_name = os.path.basename(args.input)
    output_file_name = f"refined_{input_file_name}" if not args.output else f"{args.output}/refined_{input_file_name}"
    print(f"Output file: {output_file_name}")

    # Process the markdown transcript
    process_markdown_transcript(transcript, output_file_name, lec_summary, client, args.model, args.max_chars)
