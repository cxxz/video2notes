import os
from openai import AzureOpenAI, OpenAI
from anthropic import AnthropicBedrock
from dotenv import load_dotenv

load_dotenv()

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