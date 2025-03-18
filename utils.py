import os
from openai import AzureOpenAI, OpenAI
from anthropic import AnthropicBedrock
from dotenv import load_dotenv

load_dotenv()

def initialize_client(model_id):
    """Initializes the appropriate OpenAI client based on the model."""
    if "anthropic.claude" in model_id:
        client = AnthropicBedrock(
            aws_region="us-west-2",
        )
    elif model_id.startswith("azure/"):
        client = AzureOpenAI(
            api_version="2024-02-15-preview"
        )
    elif "llama" in model_id.lower() or "qwen" in model_id.lower() or "deepseek" in model_id.lower():
        openai_api_base = os.getenv("OPENAI_BASE_URL")
        client = OpenAI(
            api_key="anything",
            base_url=openai_api_base,
        )
    else:
        raise ValueError(f"Unknown endpoint: {model_id}")
    return client

def get_llm_response(client, model_id, prompt):
    """Gets LLM response using the client and returns the result."""
    try:
        if "anthropic.claude" in model_id:
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
            model_id = model_id.replace("azure/", "")
            chat_completion = client.chat.completions.create(
                model=model_id,
                messages=[
                    # {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=8192,
                temperature=0.1,
                top_p=0.95,
            )
            response = chat_completion.choices[0].message.content
        return response
    except Exception as e:
        print(f"Error: {e}")
        return None