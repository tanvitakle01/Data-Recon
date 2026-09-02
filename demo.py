import truststore
truststore.inject_into_ssl()

from openai import OpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

endpoint = "https://AI-Adoption-COE.services.ai.azure.com/openai/v1"
deployment_name = "DeepSeek-V4-Pro"
token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")

client = OpenAI(
    base_url=endpoint,
    api_key=token_provider
)

completion = client.chat.completions.create(
    model=deployment_name,
    messages=[
        {
            "role": "user",
            "content": "What is the capital of France?",
        }
    ],
)

print(completion.choices[0].message)