import asyncio
import json
from pathlib import Path

from mcp import Client, StdioServerParameters
from openai import OpenAI

import config

here = Path(__file__).parent
params = StdioServerParameters(
    command="uv", args=["run", "python", "server_flights.py"], cwd=here
)

PROMPT = "find me a cheap flight from BOM to DEL on 10 November 2026 and tell me the airline"


async def main():
    llm = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

    async with Client(params) as c:
        print("[connect] flights via stdio")

        tools = []
        for t in (await c.list_tools()).tools:
            print("[list]   ", t.name, "|", t.description.splitlines()[0])
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
            )

        messages = [
            {"role": "system", "content": "You are a concise travel assistant."},
            {"role": "user", "content": PROMPT},
        ]

        while True:
            response = llm.chat.completions.create(
                model=config.MODEL, messages=messages, tools=tools
            )
            message = response.choices[0].message

            if not message.tool_calls:
                print("Agent:", message.content)
                print("usage:", response.usage.model_dump_json())
                break

            messages.append(message.model_dump(exclude_none=True))
            for call in message.tool_calls:
                arguments = json.loads(call.function.arguments)
                print(f"[tool]    {call.function.name}({json.dumps(arguments)})")

                r = await c.call_tool(call.function.name, arguments)
                # content is one block per list element, so structured_content is the whole answer
                content = json.dumps(r.structured_content)
                result = r.structured_content["result"]
                count = len(result) if isinstance(result, list) else 1
                print(f"         -> {count} results")

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": content,
                    }
                )


asyncio.run(main())