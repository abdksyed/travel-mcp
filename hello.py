from openai import OpenAI

import config

client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

response = client.chat.completions.create(
    model=config.MODEL,
    messages=[
        {"role": "system", "content": "You are a concise travel assistant."},
        {"role": "user", "content": "what are the main classes of trains in India?"},
    ],
)

print(f"Agent: {response.choices[0].message.content}")
print(f"usage: {response.usage.model_dump_json()}")
