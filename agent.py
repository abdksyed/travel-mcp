import json

from openai import OpenAI

import config
from tools import TOOLS, search_flights


def main():
    client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)
    functions = {"search_flights": search_flights}
    messages = [
        {
            "role": "system",
            "content": (
                "You are a concise travel assistant. Use the flight search tool "
                "for flight questions. Its offers are fake demo data, not live fares."
            ),
        },
        {
            "role": "user",
            "content": "what flights are there from BOM to DEL on 10 November 2026?",
        },
    ]

    while True:
        response = client.chat.completions.create(
            model=config.MODEL,
            messages=messages,
            tools=TOOLS,
        )
        message = response.choices[0].message
        print("==============================")
        print(f"usage: {response.usage.model_dump_json()}")
        print("x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x")
        if not message.tool_calls:
            print(f"Agent: {message.content}")
            print("x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x")
            break

        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            arguments = json.loads(call.function.arguments)
            print(f"[TOOL_CALL] {call.function.name}({json.dumps(arguments)})")
            print("x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x")
            result = functions[call.function.name](**arguments)
            print(f"[TOOL_RESPONSE] {json.dumps(result)}")
            print("x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                }
            )


if __name__ == "__main__":
    main()
