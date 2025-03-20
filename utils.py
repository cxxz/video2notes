import os
from typing import Dict, Tuple, List
from openai import AzureOpenAI, OpenAI
from anthropic import AnthropicBedrock
from dotenv import load_dotenv

load_dotenv()

import scrubadub
import scrubadub_spacy

def analyze_text_for_names(text: str, threshold: float = 0.65) -> Tuple[bool, Dict, str]:
    """
    Analyzes text to determine if it consists mostly of names.
    
    Args:
        text: The input text to analyze
        threshold: The proportion of text that needs to be names to return True (default: 0.7)
        
    Returns:
        Tuple containing:
        - Boolean indicating if text is mostly names
        - Dictionary with detected entities and their counts
        - Cleaned text with placeholders
    """
    # Initialize scrubber with SpacyNameDetector
    scrubber = scrubadub.Scrubber()
    
    
    # Clean the text and get the filth
    cleaned_text = scrubber.clean(text)
    # TOFIX: use alternative approach to remove all nonsense words, symptoms, and tags
    # print(f"Cleaned text: {cleaned_text}")

    scrubber.add_detector(scrubadub_spacy.detectors.SpacyNameDetector(model='en_core_web_lg'))
    filth_list = list(scrubber.iter_filth(text))
    
    # Count the different types of entities
    entity_counts = {}
    name_chars = 0
    
    non_whitespace_chars = sum(1 for char in cleaned_text if not char.isspace() and char not in [',', '.', '<', '>', '\n'])

    names = []

    for filth in filth_list:
        if filth.type not in entity_counts:
            entity_counts[filth.type] = 0
        entity_counts[filth.type] += 1
        
        # Count characters that are names
        if filth.type == 'name':
            name_chars += len(filth.text)
            names.append(filth.text)

        if filth.type == 'organization':
            non_whitespace_chars -= len(filth.text)
    
    # Calculate the proportion of text that is names
    # Remove whitespace for a more accurate calculation
    
    name_proportion = name_chars / non_whitespace_chars if non_whitespace_chars > 0 else 0
    # print(f"Name proportion: {name_proportion:.2f}")
    
    # Determine if text is mostly names
    is_mostly_names = name_proportion >= threshold
    
    return is_mostly_names, entity_counts, names


def initialize_client(llm):
    """Initializes the appropriate OpenAI client based on the model."""
    if llm.startswith("bedrock/"):
        client = AnthropicBedrock(
            aws_region="us-west-2",
        )
    elif llm.startswith("azure/"):
        client = AzureOpenAI(
            api_version="2024-02-15-preview"
        )
    elif llm.startswith("openai/"):
        api_key = os.getenv("V2N_API_KEY", "random")
        base_url = os.getenv("V2N_API_BASE", "https://api.openai.com/v1")
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
    else:
        raise ValueError(f"Unknown endpoint: {llm}")
    return client

def get_llm_response(client, llm, prompt):
    """Gets LLM response using the client and returns the result."""
    try:
        if llm.startswith("bedrock/"):
            model_id = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
            completion = client.messages.create(
                model=model_id,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                max_tokens=8192,
                temperature=0.1,
            )
            response = completion.content[0].text
        else:
            if llm.startswith("openai/"):
                model_id = llm.replace("openai/", "")
            elif llm.startswith("azure/"):
                model_id = llm.replace("azure/", "")
            else:
                model_id = llm
            # print(f"CONG TEST model_id: {model_id}")
            chat_completion = client.chat.completions.create(
                model=model_id,
                messages=[
                    # {"role": "system", "content": "You are a helpful assistant."},
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