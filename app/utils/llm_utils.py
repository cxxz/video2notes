"""
LLM utility functions for Video2Notes application.

Provides client initialization and response handling for different LLM backends:
- AWS Bedrock (Claude models)
- Azure OpenAI
- OpenAI-compatible APIs
"""
import os
import logging
from typing import Optional

from openai import AzureOpenAI, OpenAI
from anthropic import AnthropicBedrock


def initialize_client(llm: str):
    """Initialize the appropriate LLM client based on the model prefix.

    Args:
        llm: Model identifier with provider prefix (e.g., 'bedrock/claude-4-sonnet',
             'azure/gpt-4', 'openai/gpt-4')

    Returns:
        Initialized client for the specified provider

    Raises:
        ValueError: If the provider prefix is unknown
    """
    if llm.startswith("bedrock/"):
        return AnthropicBedrock(aws_region="us-west-2")
    elif llm.startswith("azure/"):
        return AzureOpenAI(api_version="2025-03-01-preview")
    elif llm.startswith("openai/"):
        api_key = os.getenv("V2N_API_KEY", "random")
        base_url = os.getenv("V2N_API_BASE", "https://api.openai.com/v1")
        if base_url == "https://api.openai.com/v1":
            assert api_key.startswith("sk-"), "V2N_API_KEY must start with sk-"
        else:
            logging.info(f"Using custom LLM endpoint: {base_url}")
        return OpenAI(api_key=api_key, base_url=base_url)
    else:
        raise ValueError(f"Unknown endpoint: {llm}")


def get_llm_response(client, llm: str, prompt: str) -> Optional[str]:
    """Get LLM response using the client and return the result.

    Args:
        client: Initialized LLM client from initialize_client()
        llm: Model identifier with provider prefix
        prompt: The prompt to send to the LLM

    Returns:
        The response text from the LLM, or None if an error occurred
    """
    try:
        if llm.startswith("bedrock/"):
            model_id = _get_bedrock_model_id(llm)
            completion = client.messages.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
                temperature=0.1,
            )
            return completion.content[0].text
        else:
            # OpenAI/Azure logic
            if llm.startswith("openai/"):
                model_id = llm.replace("openai/", "")
            elif llm.startswith("azure/"):
                model_id = llm.replace("azure/", "")
            else:
                model_id = llm

            chat_completion = client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
            )
            return chat_completion.choices[0].message.content
    except Exception as e:
        logging.error(f"LLM error: {e}")
        return None


def _get_bedrock_model_id(llm: str) -> str:
    """Map LLM string to Bedrock model ID.

    Args:
        llm: Model identifier (e.g., 'bedrock/claude-4-sonnet')

    Returns:
        Full Bedrock model ID

    Raises:
        ValueError: If the model is unknown
    """
    if "claude-4-sonnet" in llm:
        return "us.anthropic.claude-sonnet-4-20250514-v1:0"
    elif "claude-3-7-sonnet" in llm:
        return "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
    else:
        raise ValueError(f"Unknown Bedrock model: {llm}")
